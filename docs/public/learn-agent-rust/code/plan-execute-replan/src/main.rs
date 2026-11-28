//! D04（ADK-Rust 3.0）：规划、执行与动态重规划，以及计划模式。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- discover     某个场景的完整轨迹（场景名见 CASES）
//!
//! 第一部分（Stable）：`LoopAgent` 每一轮先运行规划者（`LlmAgent`，用 write_plan 写计划、
//! 用 exit_loop 收工），再运行执行者（`CustomAgent`，执行计划里下一个待办步骤，结果记进账本）。
//! 计划由应用保管，write_plan 检查修订号、不许删改已完成的步骤。
//! 第二部分（Beta，adk-harness）：计划模式。只读调查，调用 exit_plan_mode 提交计划，
//! 人批准后从下一轮起切到询问模式，才能改文件。
//! 模型和“人”都是按规则回复的替身；文件真实写在临时目录里。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{Arc, Mutex},
};

use adk_agent::{CustomAgent, LlmAgentBuilder, LoopAgent};
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, Event,
    FinishReason, InvocationContext, Llm, LlmRequest, LlmResponse, LlmResponseStream, Part,
    ToolContext, ToolEffect,
};
use adk_harness::{
    ApprovalPrompt, ApprovalPrompter, HarnessAgent, HarnessMode, InstructionsConfig, PromptAnswer,
    Workspace,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, GetRequest, InMemorySessionService, SessionService};
use adk_tool::{ExitLoopTool, FunctionTool};
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const ROOT_README: &str = "# demo-workspace\n升级到 3.0。\n成员：member\n";
const MEMBER_README: &str = "# member\n依赖 tokio。\n另见：plugin/README.md\n";
const PLUGIN_README: &str = "# plugin\n用到了 3.0 删除的接口。\n";

const CASES: &[&str] = &[
    "discover",
    "drops-done",
    "missing-file",
    "stuck",
    "plan-mode-approved",
    "plan-mode-rejected",
    "plan-mode-invalid",
];

fn reply(parts: Vec<Part>) -> LlmResponseStream {
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts,
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    Box::pin(futures::stream::iter([Ok(response)]))
}

fn call(name: &str, args: Value, id: &str) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args,
        id: Some(id.into()),
        thought_signature: None,
    }
}

fn text(text: impl Into<String>) -> Part {
    Part::Text { text: text.into() }
}

fn text_of(content: &Content) -> String {
    content
        .parts
        .iter()
        .filter_map(Part::text)
        .collect::<Vec<_>>()
        .join("\n")
}

// region plan
/// 计划：修订号加一串步骤。由应用保管，规划者只能通过 write_plan 修改它。
#[derive(Clone, Default)]
struct Plan {
    revision: u64,
    /// （步骤 id，要读的文件，是否已完成）
    steps: Vec<(String, String, bool)>,
}

/// 账本：每个已执行步骤的结果。重规划不会改动它。
#[derive(Clone)]
struct Entry {
    step: String,
    file: String,
    note: String,
}

#[derive(Default)]
struct Board {
    plan: Plan,
    ledger: Vec<Entry>,
    rejected: Vec<String>,
}

impl Board {
    fn render_plan(&self) -> Value {
        json!({
            "revision": self.plan.revision,
            "steps": self.plan.steps.iter().map(|(id, file, done)| json!({ "id": id, "file": file, "done": done })).collect::<Vec<_>>()
        })
    }

    fn render_ledger(&self) -> Value {
        json!(
            self.ledger
                .iter()
                .map(|e| json!({ "step": e.step, "file": e.file, "note": e.note }))
                .collect::<Vec<_>>()
        )
    }

    /// 检查新计划：修订号必须是当前加一；已完成的步骤一个不能少、文件不能改；步骤 id 不能重复。
    fn accept(
        &mut self,
        revision: u64,
        steps: &[(String, String)],
    ) -> std::result::Result<(), String> {
        if revision != self.plan.revision + 1 {
            return Err(format!(
                "revision_conflict:expected={}",
                self.plan.revision + 1
            ));
        }
        let mut ids: Vec<&str> = steps.iter().map(|(id, _)| id.as_str()).collect();
        ids.sort();
        ids.dedup();
        if ids.len() != steps.len() {
            return Err("duplicate_step".into());
        }
        for (id, file, done) in &self.plan.steps {
            if *done && !steps.iter().any(|(i, f)| i == id && f == file) {
                return Err(format!("done_step_removed:{id}"));
            }
        }
        let done: Vec<String> = self
            .plan
            .steps
            .iter()
            .filter(|s| s.2)
            .map(|s| s.0.clone())
            .collect();
        self.plan = Plan {
            revision,
            steps: steps
                .iter()
                .map(|(id, file)| (id.clone(), file.clone(), done.contains(id)))
                .collect(),
        };
        Ok(())
    }
}
// endregion plan

// region planner
/// write_plan：规划者提交一份完整的新计划。应用检查后才替换，并把计划镜像进会话状态。
fn write_plan(board: Arc<Mutex<Board>>) -> FunctionTool {
    FunctionTool::new(
        "write_plan",
        "提交完整的新计划：revision 是新的修订号，steps 是全部步骤（id、file）。",
        move |ctx: Arc<dyn ToolContext>, args: Value| {
            let board = board.clone();
            async move {
                let revision = args["revision"].as_u64().unwrap_or(0);
                let steps: Vec<(String, String)> = args["steps"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|s| {
                        (
                            s["id"].as_str().unwrap_or("").to_owned(),
                            s["file"].as_str().unwrap_or("").to_owned(),
                        )
                    })
                    .collect();
                let mut board = board.lock().unwrap();
                match board.accept(revision, &steps) {
                    Ok(()) => {
                        let mut actions = ctx.actions();
                        actions
                            .state_delta
                            .insert("plan".into(), board.render_plan());
                        ctx.set_actions(actions);
                        Ok(json!({ "status": "accepted", "revision": revision }))
                    }
                    Err(reason) => {
                        board.rejected.push(reason.clone());
                        Err(AdkError::new(
                            ErrorComponent::Tool,
                            ErrorCategory::InvalidInput,
                            "plan.rejected",
                            reason,
                        ))
                    }
                }
            }
        },
    )
    // 同一修订号的同一份计划重复提交，第二次会因修订号不对被拒，计划不会被改两次
    .with_effect(ToolEffect::Idempotent)
}

/// 规划者的替身模型：读系统消息里的计划与账本，决定写新计划、继续还是收工。
struct PlannerLlm {
    scenario: String,
    /// 每次调用时，系统消息里看到的计划修订号（模板按规划者的每一次运行渲染）
    saw: Mutex<Vec<u64>>,
}

/// 账本里提到、但计划里还没有的文件（“成员：x” → x/README.md，“另见：路径”）。
fn discovered(plan: &Value, ledger: &Value) -> Vec<String> {
    let planned: Vec<&str> = plan["steps"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|s| s["file"].as_str())
        .collect();
    let mut found = Vec::new();
    for entry in ledger.as_array().into_iter().flatten() {
        let note = entry["note"].as_str().unwrap_or_default();
        for line in note.lines() {
            let file = line
                .strip_prefix("成员：")
                .map(|m| format!("{}/README.md", m.trim()))
                .or_else(|| line.strip_prefix("另见：").map(|p| p.trim().to_owned()));
            if let Some(file) = file
                && !planned.contains(&file.as_str())
                && !found.contains(&file)
            {
                found.push(file);
            }
        }
    }
    found
}

impl PlannerLlm {
    fn decide(&self, request: &LlmRequest) -> Vec<Part> {
        let system: String = request
            .contents
            .iter()
            .filter(|c| c.role == "system")
            .map(text_of)
            .collect();
        let plan: Value = system
            .split("计划：")
            .nth(1)
            .and_then(|t| t.lines().next())
            .and_then(|l| serde_json::from_str(l).ok())
            .unwrap_or(json!({ "revision": 0, "steps": [] }));
        let ledger: Value = system
            .split("账本：")
            .nth(1)
            .and_then(|t| t.lines().next())
            .and_then(|l| serde_json::from_str(l).ok())
            .unwrap_or(json!([]));
        self.saw
            .lock()
            .unwrap()
            .push(plan["revision"].as_u64().unwrap_or(0));
        let last = request.contents.last();
        // 刚提交过计划：成功就把这一轮交给执行者；被拒就按错误修正后再交
        if let Some(Part::FunctionResponse {
            function_response, ..
        }) = last.and_then(|c| c.parts.first())
            && function_response.response.get("error").is_none()
        {
            return vec![text("计划已更新，交给执行者。")];
        }
        let rejected_before = last
            .and_then(|c| c.parts.first())
            .is_some_and(|p| matches!(p, Part::FunctionResponse { function_response, .. } if function_response.response.get("error").is_some()));
        let revision = plan["revision"].as_u64().unwrap_or(0);
        let steps: Vec<Value> = plan["steps"].as_array().cloned().unwrap_or_default();
        if revision == 0 {
            return vec![call(
                "write_plan",
                json!({ "revision": 1, "steps": [{ "id": "s1", "file": "README.md" }] }),
                "plan-1",
            )];
        }
        if steps.iter().any(|s| s["done"] == false) {
            return vec![text("还有待办步骤，交给执行者。")];
        }
        let new_files = discovered(&plan, &ledger);
        if !new_files.is_empty() {
            let mut next: Vec<Value> = steps
                .iter()
                .map(|s| json!({ "id": s["id"], "file": s["file"] }))
                .collect();
            // drops-done：第一次重规划时只写新步骤，把已完成的步骤丢了
            if self.scenario == "drops-done" && !rejected_before {
                next.clear();
            }
            for (i, file) in new_files.iter().enumerate() {
                next.push(json!({ "id": format!("s{}", steps.len() + i + 1), "file": file }));
            }
            return vec![call(
                "write_plan",
                json!({ "revision": revision + 1, "steps": next }),
                // 被拒后重交要换一个调用 id：同一次运行里调用 id 不能重复
                &format!(
                    "plan-{}{}",
                    revision + 1,
                    if rejected_before { "-retry" } else { "" }
                ),
            )];
        }
        if self.scenario == "stuck" {
            // 什么都做完了，替身却不肯收工
            return vec![text("再看看还有没有遗漏。")];
        }
        vec![call("exit_loop", json!({}), "done")]
    }
}

#[async_trait]
impl Llm for PlannerLlm {
    fn name(&self) -> &str {
        "planner-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        Ok(reply(self.decide(&request)))
    }
}
// endregion planner

// region executor
/// 执行者：由代码执行计划里第一个待办步骤（读文件），结果记进账本，计划与账本镜像进会话状态。
/// 文件不存在就把失败记进账本并上报（escalate），整个循环停下。
fn executor(board: Arc<Mutex<Board>>, root: Arc<PathBuf>) -> Result<Arc<dyn Agent>> {
    Ok(Arc::new(
        CustomAgent::builder("executor")
            .handler(move |ctx: Arc<dyn InvocationContext>| {
                let (board, root) = (board.clone(), root.clone());
                async move {
                    let mut event = Event::new(ctx.invocation_id());
                    event.author = "executor".into();
                    let mut board = board.lock().unwrap();
                    let next = board.plan.steps.iter().position(|s| !s.2);
                    let message = match next {
                        None => "没有待办步骤。".to_string(),
                        Some(index) => {
                            let (id, file, _) = board.plan.steps[index].clone();
                            match fs::read_to_string(root.join(&file)) {
                                Ok(body) => {
                                    let note: String =
                                        body.lines().skip(1).collect::<Vec<_>>().join("\n");
                                    board.plan.steps[index].2 = true;
                                    board.ledger.push(Entry {
                                        step: id.clone(),
                                        file: file.clone(),
                                        note,
                                    });
                                    format!("执行 {id}：读完 {file}")
                                }
                                Err(_) => {
                                    board.ledger.push(Entry {
                                        step: id.clone(),
                                        file: file.clone(),
                                        note: "missing".into(),
                                    });
                                    event.actions.escalate = true;
                                    format!("执行 {id} 失败：{file} 不存在")
                                }
                            }
                        }
                    };
                    event
                        .actions
                        .state_delta
                        .insert("plan".into(), board.render_plan());
                    event
                        .actions
                        .state_delta
                        .insert("ledger".into(), board.render_ledger());
                    event.llm_response.content = Some(Content::new("model").with_text(message));
                    Ok(Box::pin(futures::stream::iter([Ok(event)])) as adk_core::EventStream)
                }
            })
            .build()?,
    ))
}
// endregion executor

// region loop
fn plan_execute(
    board: Arc<Mutex<Board>>,
    root: Arc<PathBuf>,
    model: Arc<PlannerLlm>,
) -> Result<Arc<dyn Agent>> {
    // 每一轮开始时，规划者的 {plan?}、{ledger?} 模板读到的都是最新的会话状态
    let planner = LlmAgentBuilder::new("planner")
        .instruction("你负责计划。\n计划：{plan?}\n账本：{ledger?}")
        .model(model)
        .tool(Arc::new(write_plan(board.clone())))
        .tool(Arc::new(ExitLoopTool::new()))
        .build()?;
    Ok(Arc::new(
        LoopAgent::new(
            "plan_execute",
            vec![Arc::new(planner), executor(board, root)?],
        )
        .with_max_iterations(6),
    ))
}
// endregion loop

async fn run_replan(scenario: &str) -> Result<(Vec<String>, String)> {
    let dir = tempfile::tempdir()?;
    let root = Arc::new(dir.path().canonicalize()?);
    fs::write(root.join("README.md"), ROOT_README)?;
    if scenario != "missing-file" {
        fs::create_dir_all(root.join("member"))?;
        fs::write(root.join("member/README.md"), MEMBER_README)?;
    }
    fs::create_dir_all(root.join("plugin"))?;
    fs::write(root.join("plugin/README.md"), PLUGIN_README)?;
    let board = Arc::new(Mutex::new(Board::default()));
    let model = Arc::new(PlannerLlm {
        scenario: scenario.into(),
        saw: Mutex::new(Vec::new()),
    });
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d04".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("d04")
        .agent(plan_execute(board.clone(), root, model.clone())?)
        .session_service(sessions)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder()
                .allow("write_plan")
                .allow("exit_loop")
                .build(),
        ))
        .without_intra_compaction()
        .build()?;
    let task = "检查工作区升级要读的全部 README，边读边补计划。";
    let mut lines = vec![format!("--- run: {task}")];
    let (mut revisions, mut stop, mut iterations) = (Vec::new(), "loop_limit".to_string(), 0);
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(task),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = event?;
        for line in trace::event_lines(&event) {
            // 计划与账本的 JSON 很长，轨迹里只留修订号与步骤数
            if line.contains("state   plan =") || line.contains("state   ledger =") {
                continue;
            }
            lines.push(line);
        }
        if event.author == "executor" {
            iterations += 1;
        }
        if event.actions.escalate {
            lines.push(format!("[{}] escalate", event.author));
            stop = if event.author == "executor" {
                "step_failed".into()
            } else {
                "completed".into()
            };
        }
        if let Some(plan) = event.actions.state_delta.get("plan")
            && event.author == "planner"
        {
            revisions.push(plan["revision"].to_string());
        }
    }
    let board = board.lock().unwrap();
    let executed: Vec<String> = board
        .ledger
        .iter()
        .map(|e| format!("{}:{}", e.step, e.file))
        .collect();
    lines.push(format!("ledger: {}", executed.join(", ")));
    let summary = format!(
        "{scenario}: revisions=[{}] rejected=[{}] executed=[{}] iterations={iterations} planner_saw=[{}] stop={stop}",
        revisions.join(","),
        board.rejected.join(","),
        board
            .ledger
            .iter()
            .map(|e| if e.note == "missing" {
                format!("{}(missing)", e.file)
            } else {
                e.file.clone()
            })
            .collect::<Vec<_>>()
            .join(","),
        model
            .saw
            .lock()
            .unwrap()
            .iter()
            .map(u64::to_string)
            .collect::<Vec<_>>()
            .join(","),
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

// region plan_mode_model
/// 计划模式的替身模型：
/// 第一轮只读调查，试着提前改文件（会被计划模式拒绝），然后调用 exit_plan_mode 提交计划；
/// 下一轮（“开始执行”）按计划写文件。
struct PlanModeLlm {
    invalid_steps: bool,
}

impl PlanModeLlm {
    fn decide(&self, request: &LlmRequest) -> Part {
        // 历史里每个工具结果：（工具名，是否成功）
        let results: Vec<(&str, bool)> = request
            .contents
            .iter()
            .flat_map(|c| c.parts.iter())
            .filter_map(|p| match p {
                Part::FunctionResponse {
                    function_response, ..
                } => Some((
                    function_response.name.as_str(),
                    function_response.response.get("error").is_none(),
                )),
                _ => None,
            })
            .collect();
        let starting = request
            .contents
            .iter()
            .any(|c| c.role == "user" && text_of(c).contains("开始执行"));
        if starting {
            // 第二轮：写一次文件，然后照实报告结果
            return match results.last() {
                Some(("write_file", ok))
                    if results.iter().filter(|r| r.0 == "write_file").count() >= 2 =>
                {
                    text(if *ok {
                        "已按计划写好 UPGRADE.md。"
                    } else {
                        "写文件被拒绝：现在还不能改文件。"
                    })
                }
                _ => call(
                    "write_file",
                    json!({ "path": "UPGRADE.md", "content": "1. 升级 tokio\n2. 跑测试\n" }),
                    "write-2",
                ),
            };
        }
        match results.last() {
            None => call("read_file", json!({ "path": "README.md" }), "read-1"),
            Some(("read_file", _)) => call(
                "write_file",
                json!({ "path": "UPGRADE.md", "content": "草稿" }),
                "write-1",
            ),
            Some(("write_file", _)) => {
                let second_depends_on = if self.invalid_steps { "9" } else { "1" };
                let steps = json!([
                    { "id": "1", "title": "升级依赖", "instruction": "升级 tokio", "depends_on": [] },
                    { "id": "2", "title": "跑测试", "instruction": "cargo test", "depends_on": [second_depends_on] }
                ]);
                call(
                    "exit_plan_mode",
                    json!({ "plan": "先升级 tokio，再跑测试，结果写进 UPGRADE.md。", "steps": steps, "next_mode": "ask" }),
                    "plan",
                )
            }
            Some(("exit_plan_mode", false)) => text("计划没有通过，仍在计划模式。"),
            _ => text("计划已批准，等你说开始。"),
        }
    }
}

#[async_trait]
impl Llm for PlanModeLlm {
    fn name(&self) -> &str {
        "plan-mode-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        Ok(reply(vec![self.decide(&request)]))
    }
}

// endregion plan_mode_model

// region plan_mode
/// 替身的“人”：按场景批准或拒绝计划；改文件的请求一律批准。
#[derive(Debug)]
struct Person {
    approve_plan: bool,
    asked: Mutex<Vec<String>>,
}

#[async_trait]
impl ApprovalPrompter for Person {
    async fn prompt(&self, prompt: ApprovalPrompt) -> adk_core::Result<PromptAnswer> {
        let tool = prompt.request.tool_name.clone();
        let approve = tool != "exit_plan_mode" || self.approve_plan;
        self.asked.lock().unwrap().push(format!(
            "{tool}@{}:{}",
            prompt.mode,
            if approve { "approve" } else { "deny" }
        ));
        Ok(if approve {
            PromptAnswer::ApproveOnce
        } else {
            PromptAnswer::Deny {
                message: Some("计划不够细".into()),
            }
        })
    }
}

async fn run_plan_mode(scenario: &str) -> Result<(Vec<String>, String)> {
    let dir = tempfile::tempdir()?;
    fs::write(dir.path().join("README.md"), ROOT_README)?;
    let person = Arc::new(Person {
        approve_plan: scenario != "plan-mode-rejected",
        asked: Mutex::new(Vec::new()),
    });
    let agent = HarnessAgent::builder("assistant")
        .model(Arc::new(PlanModeLlm {
            invalid_steps: scenario == "plan-mode-invalid",
        }))
        .workspace(Workspace::new(dir.path()))
        .project_instructions(InstructionsConfig {
            user_file: None,
            require_trust: false,
            ..InstructionsConfig::default()
        })
        .mode(HarnessMode::Plan)
        .prompter(person.clone())
        .without_shell()
        .without_todos()
        .without_compaction()
        .without_intra_compaction()
        .build()?;
    let sessions = Arc::new(InMemorySessionService::new());
    let harness = agent.into_harness("d04", sessions.clone())?;
    // endregion plan_mode
    let user: adk_core::UserId = "user".try_into()?;
    let session = harness.open_session(&user, None).await?;
    let mut lines = Vec::new();
    let mut steps = Vec::new();
    for message in ["先调研，制定升级计划。", "开始执行。"] {
        if message == "开始执行。" {
            // 第一轮之后，会话状态里的计划与模式
            let state = sessions
                .get(GetRequest {
                    app_name: "d04".into(),
                    user_id: "user".into(),
                    session_id: session.to_string(),
                    num_recent_events: None,
                    after: None,
                })
                .await?
                .state()
                .all();
            match state.get("harness:plan") {
                Some(plan) => lines.push(format!(
                    "[state]  harness:plan steps={} planHash={}…",
                    plan["steps"].as_array().map_or(0, Vec::len),
                    plan["planHash"]
                        .as_str()
                        .unwrap_or("")
                        .chars()
                        .take(12)
                        .collect::<String>()
                )),
                None => lines.push("[state]  harness:plan 没有写入".into()),
            }
        }
        lines.push(format!("--- turn: {message}"));
        let mut stream = harness.send(&user, &session, message).await?;
        while let Some(event) = stream.next().await {
            let event = event?;
            for part in event.content().map(|c| c.parts.clone()).unwrap_or_default() {
                match &part {
                    Part::FunctionCall { name, args, .. } => {
                        let shown = if name == "exit_plan_mode" {
                            json!({ "steps": args["steps"].as_array().map(|s| s.len()) })
                        } else {
                            json!({ "path": args["path"] })
                        };
                        lines.push(format!("[call]   {name} {shown}"));
                    }
                    Part::FunctionResponse {
                        function_response, ..
                    } => {
                        let status = part
                            .tool_result_status()
                            .and_then(|s| serde_json::to_value(s).ok())
                            .and_then(|v| v.as_str().map(str::to_owned))
                            .unwrap_or_else(|| "ok".into());
                        let code = part
                            .tool_result_error_code()
                            .map(|c| format!("({c})"))
                            .unwrap_or_default();
                        let mode = function_response.response["mode"]
                            .as_str()
                            .map(|m| format!(" mode→{m}"))
                            .unwrap_or_default();
                        let detail = function_response.response["error"]
                            .as_str()
                            .map(|e| format!(" — {}", e.chars().take(150).collect::<String>()))
                            .unwrap_or_default();
                        lines.push(format!(
                            "[result] {} {status}{code}{mode}{detail}",
                            function_response.name
                        ));
                        steps.push(format!("{}:{status}{code}", function_response.name));
                    }
                    Part::Text { text } if event.author == "assistant" => {
                        lines.push(format!("[text]   {text}"))
                    }
                    _ => {}
                }
            }
        }
    }
    let asked = person.asked.lock().unwrap().clone();
    for line in &asked {
        lines.push(format!("person asked: {line}"));
    }
    let written = dir.path().join("UPGRADE.md").exists();
    let summary = format!(
        "{scenario}: tools=[{}] asked=[{}] file_written={}",
        steps.join(","),
        asked.join(","),
        if written { "yes" } else { "no" }
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    if scenario.starts_with("plan-mode") {
        run_plan_mode(scenario).await
    } else {
        run_replan(scenario).await
    }
}

async fn cli(args: &[String]) -> Result<()> {
    match args {
        [] => {
            for name in CASES {
                println!("{}", run(name).await?.1);
            }
            Ok(())
        }
        [name] if CASES.contains(&name.as_str()) => {
            for line in run(name).await?.0 {
                println!("{line}");
            }
            Ok(())
        }
        _ => Err(format!("usage: plan-execute-replan [{}]", CASES.join("|")).into()),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if let Err(error) = cli(&args).await {
        eprintln!("{error}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn summary(name: &str) -> String {
        run(name).await.unwrap().1
    }

    #[test]
    fn a_new_plan_keeps_every_done_step() {
        let mut board = Board::default();
        board
            .accept(1, &[("s1".into(), "README.md".into())])
            .unwrap();
        board.plan.steps[0].2 = true;
        assert_eq!(
            board.accept(2, &[("s2".into(), "x".into())]),
            Err("done_step_removed:s1".into())
        );
        assert_eq!(
            board.accept(3, &[]),
            Err("revision_conflict:expected=2".into())
        );
        board
            .accept(
                2,
                &[("s1".into(), "README.md".into()), ("s2".into(), "x".into())],
            )
            .unwrap();
        assert!(board.plan.steps[0].2 && !board.plan.steps[1].2);
    }

    #[tokio::test]
    async fn replanning_follows_what_was_read_and_keeps_the_ledger() {
        assert!(summary("discover").await.contains(
            "revisions=[1,2,3] rejected=[] executed=[README.md,member/README.md,plugin/README.md]"
        ));
        assert!(
            summary("drops-done")
                .await
                .contains("rejected=[done_step_removed:s1,done_step_removed:s1]")
        );
    }

    #[tokio::test]
    async fn a_failed_step_or_a_planner_that_never_stops_ends_the_loop() {
        assert!(summary("missing-file").await.ends_with("stop=step_failed"));
        assert!(
            summary("stuck")
                .await
                .contains("iterations=6 planner_saw=[0,0,1,1,2,2,3,3,3] stop=loop_limit")
        );
    }

    #[tokio::test]
    async fn plan_mode_allows_edits_only_after_an_approved_plan() {
        let approved = summary("plan-mode-approved").await;
        assert!(
            approved.contains("write_file:refused,exit_plan_mode:ok,write_file:ok"),
            "{approved}"
        );
        assert!(approved.ends_with("file_written=yes"), "{approved}");
        assert!(
            summary("plan-mode-rejected")
                .await
                .ends_with("file_written=no")
        );
        assert!(
            summary("plan-mode-invalid")
                .await
                .contains("exit_plan_mode:failed(harness.plan.invalid)")
        );
    }
}
