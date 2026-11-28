//! R05（ADK-Rust 3.0）：可见的任务清单。
//!
//!   cargo run --locked                    全部场景的摘要
//!   cargo run --locked -- normal          某个场景的完整轨迹（场景名见 CASES）
//!
//! 清单存在会话状态（session state）的 `plan` 键里，由 `todo_write` 工具整批校验后通过
//! `state_delta` 写入；每次请求模型之前，before_model 回调把最新清单放进请求。
//! 模型是按规则回复的 PlanLlm（只看得到请求内容），文件工具真实读取临时目录。
mod trace;

use std::{
    collections::{HashMap, HashSet},
    fs,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, BeforeModelCallback, BeforeModelResult, CallbackContext, Content, DeclarativePolicy,
    ErrorCategory, ErrorComponent, FinishReason, Llm, LlmRequest, LlmResponse, LlmResponseStream,
    Part, ToolContext, ToolEffect,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, GetRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const GOAL: &str = "读取 README，整理启动说明";
const README: &str = "项目：Rust Agent 练习\n启动命令：cargo run --release\n要求：Rust 1.99.1\n";
const PLAN_KEY: &str = "plan";
/// 清单在请求里的标记：模型从 system 内容里最后一处标记后面读清单。
const PLAN_MARK: &str = "当前清单：";
const CASES: &[&str] = &[
    "normal",
    "claims-only",
    "read-error",
    "budget-stop",
    "template-only",
    "next-run",
    "fresh-session",
    "two-active",
    "skip-completion",
    "unknown-status",
    "duplicate-id",
    "empty-content",
    "too-many",
    "remove-item",
    "changed-content",
    "stale-revision",
    "reopen-completed",
    "append-step",
    "yield-step",
    "permission-denied",
    "same-batch-naive",
    "same-batch",
    "wrong-type",
    "unknown-field",
];

// region types
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Status {
    Pending,
    InProgress,
    Completed,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Item {
    id: String,
    content: String,
    status: Status,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
struct Plan {
    goal: String,
    revision: u64,
    items: Vec<Item>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct WriteArgs {
    expected_revision: u64,
    items: Vec<Item>,
}
// endregion types

// region transition
fn can_move(from: Status, to: Status) -> bool {
    from == to
        || matches!(
            (from, to),
            (Status::Pending, Status::InProgress)
                | (Status::InProgress, Status::Completed)
                | (Status::InProgress, Status::Pending)
        )
}
// endregion transition

impl Plan {
    fn new() -> Self {
        Self {
            goal: GOAL.into(),
            revision: 0,
            items: vec![],
        }
    }

    // region validate
    /// 整份候选清单逐项检查，全部通过才替换；任何一项失败，原清单和版本都不变。
    fn write(&mut self, args: WriteArgs) -> std::result::Result<(), &'static str> {
        if args.expected_revision != self.revision {
            return Err("todo.revision_conflict");
        }
        if args.items.is_empty() || args.items.len() > 8 {
            return Err("todo.item_count");
        }
        let mut ids = HashSet::new();
        let mut active = 0;
        for item in &args.items {
            if item.id.is_empty()
                || item.id.len() > 24
                || !item
                    .id
                    .bytes()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'-')
            {
                return Err("todo.invalid_id");
            }
            if !ids.insert(item.id.as_str()) {
                return Err("todo.duplicate_id");
            }
            if item.content.trim().is_empty() || item.content.chars().count() > 120 {
                return Err("todo.invalid_content");
            }
            active += usize::from(item.status == Status::InProgress);
            match self.items.iter().find(|old| old.id == item.id) {
                Some(old) => {
                    if old.content != item.content {
                        return Err("todo.content_changed");
                    }
                    if !can_move(old.status, item.status) {
                        return Err("todo.invalid_transition");
                    }
                }
                None if item.status != Status::Pending => return Err("todo.new_item_not_pending"),
                None => {}
            }
        }
        if active > 1 {
            return Err("todo.multiple_active");
        }
        if self.items.iter().any(|old| !ids.contains(old.id.as_str())) {
            return Err("todo.removed_item");
        }
        // 前面任何一项失败都已经返回；走到这里才提交
        self.items = args.items;
        self.revision += 1;
        Ok(())
    }
    // endregion validate
}

// region tools
fn todo_error(code: &'static str) -> AdkError {
    AdkError::new(
        ErrorComponent::Tool,
        ErrorCategory::InvalidInput,
        code,
        format!("清单更新被拒绝：{code}"),
    )
}

/// 读出会话状态里的清单；还没有建单时是一份空清单（版本 0）。
/// 状态里的值读不出来时报错，而不是当成空清单——那样下一次按版本 0 的写入会把它覆盖掉。
fn stored_plan(ctx: &dyn ToolContext) -> std::result::Result<Plan, AdkError> {
    match ctx
        .session()
        .and_then(|session| session.state().get(PLAN_KEY))
    {
        None => Ok(Plan::new()),
        Some(value) => serde_json::from_value(value).map_err(|_| {
            AdkError::new(
                ErrorComponent::Tool,
                ErrorCategory::Internal,
                "todo.state_corrupt",
                "会话状态里的清单无法解析",
            )
        }),
    }
}

/// 同一批工具调用的事件要等整批执行完才产出，会话状态那时才合并；
/// 所以这里按本次运行记下 todo_write 刚写的清单，同一批里后面的调用读它。
type Written = Arc<Mutex<HashMap<String, Plan>>>;

/// `todo_write`：读当前清单，整批校验候选清单，通过后把新清单写进这次调用的 state_delta。
/// 这次调用的事件产出时，Runner 把 state_delta 合并进会话状态。
/// `remember_batch = false` 只用于对照场景 same-batch-naive。
fn todo_write(remember_batch: bool) -> FunctionTool {
    let written: Written = Arc::default();
    let handler = move |ctx: Arc<dyn ToolContext>, args: Value| {
        let written = written.clone();
        async move {
            let args: WriteArgs =
                serde_json::from_value(args).map_err(|_| todo_error("todo.invalid_arguments"))?;
            let stored = stored_plan(ctx.as_ref())?;
            let mut plan = match written.lock().unwrap().get(ctx.invocation_id()) {
                Some(recent) if remember_batch && recent.revision > stored.revision => {
                    recent.clone()
                }
                _ => stored,
            };
            plan.write(args).map_err(todo_error)?;
            written
                .lock()
                .unwrap()
                .insert(ctx.invocation_id().to_string(), plan.clone());
            let mut actions = ctx.actions();
            actions.state_delta.insert(PLAN_KEY.into(), json!(plan));
            ctx.set_actions(actions);
            Ok(json!(plan))
        }
    };
    FunctionTool::new(
        "todo_write",
        "提交完整的候选清单：expected_revision 是你看到的清单版本，items 是全部条目。",
        handler,
    )
}

fn todo_read() -> FunctionTool {
    let handler = |ctx: Arc<dyn ToolContext>, _args: Value| async move {
        Ok(json!(stored_plan(ctx.as_ref())?))
    };
    FunctionTool::new("todo_read", "读取当前清单。", handler).with_effect(ToolEffect::ReadOnly)
}

#[derive(Default)]
struct Reads(AtomicUsize);

fn read_file(root: Arc<PathBuf>, reads: Arc<Reads>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, reads) = (root.clone(), reads.clone());
        async move {
            if args["path"] != "README.md" {
                return Err(AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Forbidden,
                    "path.not_allowed",
                    "只允许读取练习目录的 README.md",
                ));
            }
            let content = fs::read_to_string(root.join("README.md")).map_err(|_| {
                AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::NotFound,
                    "file.missing",
                    "练习目录中不存在 README.md",
                )
            })?;
            reads.0.fetch_add(1, Ordering::SeqCst);
            Ok(json!({ "content": content }))
        }
    };
    FunctionTool::new("read_file", "读取练习目录的 README.md。", handler)
        .with_effect(ToolEffect::ReadOnly)
}

/// 真的会写文件的工具。应用策略拒绝它：清单里写着“写入 summary.txt”也不等于获得了权限。
fn write_file(root: Arc<PathBuf>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let root = root.clone();
        async move {
            let text = args["content"].as_str().unwrap_or_default().to_owned();
            fs::write(root.join("summary.txt"), text).map_err(|e| {
                AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Internal,
                    "file.write_failed",
                    e.to_string(),
                )
            })?;
            Ok(json!({ "written": true }))
        }
    };
    FunctionTool::new("write_file", "写入练习目录的 summary.txt。", handler)
}
// endregion tools

// region visibility
/// 每次请求模型之前，读会话状态里的最新清单，作为一条 system 内容放进请求。
/// 回调里的 `ctx.state()` 是会话的当前状态：上一轮工具写入的清单这里已经看得到。
fn inject_latest_plan() -> BeforeModelCallback {
    Box::new(|ctx: Arc<dyn CallbackContext>, mut request: LlmRequest| {
        Box::pin(async move {
            let plan = ctx
                .state()
                .and_then(|state| state.get(PLAN_KEY))
                .unwrap_or_else(|| json!(Plan::new()));
            let at = request
                .contents
                .iter()
                .take_while(|content| content.role == "system")
                .count();
            request.contents.insert(
                at,
                Content::new("system").with_text(format!("{PLAN_MARK}{plan}")),
            );
            Ok(BeforeModelResult::Continue(request))
        })
    })
}
// endregion visibility

// region model
/// 按规则回复的模型：只看请求里的清单和工具结果，和真实模型一样拿不到运行时的内部状态。
struct PlanLlm {
    claims_only: bool,
    requests: Mutex<Vec<LlmRequest>>,
}

/// 请求里最后一处“当前清单：”后面的清单（只看 system 内容）；没有或读不出来就当作空清单。
fn plan_in(request: &LlmRequest) -> Plan {
    request
        .contents
        .iter()
        .filter(|content| content.role == "system")
        .flat_map(|content| content.parts.iter().filter_map(Part::text))
        .filter_map(|text| text.rsplit_once(PLAN_MARK).map(|(_, plan)| plan))
        .next_back()
        .and_then(|json| serde_json::from_str(json).ok())
        .unwrap_or_else(Plan::new)
}

fn tool_results(request: &LlmRequest) -> Vec<&Part> {
    request
        .contents
        .iter()
        .flat_map(|content| &content.parts)
        .filter(|part| matches!(part, Part::FunctionResponse { .. }))
        .collect()
}

fn initial_items() -> Vec<Item> {
    [
        ("read", "读取 README"),
        ("summarize", "整理启动说明"),
        ("check", "核对说明与原文"),
    ]
    .into_iter()
    .map(|(id, content)| Item {
        id: id.into(),
        content: content.into(),
        status: Status::Pending,
    })
    .collect()
}

fn function_call(name: &str, args: Value, turn: usize) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args,
        id: Some(format!("call-{turn}")),
        thought_signature: None,
    }
}

impl PlanLlm {
    fn decide(&self, request: &LlmRequest, turn: usize) -> Part {
        let results = tool_results(request);
        // 上一个工具调用失败：不再推进，如实报告
        if let Some(code) = results
            .last()
            .and_then(|part| part.tool_result_error_code())
        {
            return Part::Text {
                text: format!("任务未完成：{code}"),
            };
        }
        let plan = plan_in(request);
        let write = |items: Vec<Item>| {
            function_call(
                "todo_write",
                json!({ "expected_revision": plan.revision, "items": items }),
                turn,
            )
        };
        let mut items = plan.items.clone();
        if items.is_empty() {
            return write(initial_items());
        }
        match turn {
            2 => items[0].status = Status::InProgress,
            3 if self.claims_only => return function_call("todo_read", json!({}), turn),
            3 => return function_call("read_file", json!({ "path": "README.md" }), turn),
            4 => {
                items[0].status = Status::Completed;
                items[1].status = Status::InProgress;
            }
            5 => {
                items[1].status = Status::Completed;
                items[2].status = Status::InProgress;
            }
            6 => items[2].status = Status::Completed,
            _ => {
                let content = results.iter().find_map(|part| match part {
                    Part::FunctionResponse {
                        function_response, ..
                    } => function_response.response["content"].as_str(),
                    _ => None,
                });
                return Part::Text {
                    text: content.map_or_else(
                        || "清单已完成，但缺少 README 读取证据。".into(),
                        |text| format!("启动说明：\n{text}"),
                    ),
                };
            }
        }
        write(items)
    }
}

#[async_trait]
impl Llm for PlanLlm {
    fn name(&self) -> &str {
        "plan-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let turn = {
            let mut requests = self.requests.lock().unwrap();
            requests.push(request.clone());
            requests.len()
        };
        let part = self.decide(&request, turn);
        let mut response = LlmResponse::new(Content {
            role: "model".into(),
            parts: vec![part],
        });
        response.finish_reason = Some(FinishReason::Stop);
        response.turn_complete = true;
        Ok(Box::pin(futures::stream::iter([Ok(response)])))
    }
}
// endregion model

// region wiring
#[derive(Clone, Copy, PartialEq)]
enum Visibility {
    /// before_model 回调每次请求前放入最新清单（主线）
    Live,
    /// 只用 instruction 模板里的 {plan?}：本次运行开始时渲染一次
    TemplateOnly,
}

struct Lab {
    runner: Runner,
    sessions: Arc<InMemorySessionService>,
    model: Arc<PlanLlm>,
    reads: Arc<Reads>,
}

fn lab(
    root: Arc<PathBuf>,
    model: Arc<PlanLlm>,
    visibility: Visibility,
    max_iterations: Option<u32>,
) -> Result<Lab> {
    let reads = Arc::new(Reads::default());
    let mut agent = LlmAgentBuilder::new("assistant")
        .model(model.clone())
        .tool(Arc::new(todo_write(true)))
        .tool(Arc::new(todo_read()))
        .tool(Arc::new(read_file(root.clone(), reads.clone())))
        .tool(Arc::new(write_file(root)));
    agent = match visibility {
        Visibility::Live => agent
            .instruction("先用 todo_write 列出计划，按清单逐步推进。")
            .before_model_callback(inject_latest_plan()),
        Visibility::TemplateOnly => agent.instruction(format!(
            "先用 todo_write 列出计划，按清单逐步推进。\n{PLAN_MARK}{{plan?}}"
        )),
    };
    if let Some(max) = max_iterations {
        agent = agent.max_iterations(max);
    }
    let policy = DeclarativePolicy::builder()
        .allow("todo_write")
        .allow("todo_read")
        .allow("read_file")
        .deny("write_file", "本章只读：不允许写文件");
    let sessions = Arc::new(InMemorySessionService::new());
    let runner = Runner::builder()
        .app_name("r05")
        .agent(Arc::new(agent.build()?))
        .session_service(sessions.clone())
        .tool_policy(Arc::new(policy.build()))
        .without_intra_compaction()
        .build()?;
    Ok(Lab {
        runner,
        sessions,
        model,
        reads,
    })
}

async fn open_session(lab: &Lab, id: &str, plan: Option<&Plan>) -> Result<()> {
    let state: HashMap<String, Value> = plan
        .map(|plan| HashMap::from([(PLAN_KEY.to_string(), json!(plan))]))
        .unwrap_or_default();
    lab.sessions
        .create(CreateRequest {
            app_name: "r05".into(),
            user_id: "reader".into(),
            session_id: Some(id.into()),
            state,
        })
        .await?;
    Ok(())
}

async fn session_plan(lab: &Lab, id: &str) -> Result<Option<Plan>> {
    let session = lab
        .sessions
        .get(GetRequest {
            app_name: "r05".into(),
            user_id: "reader".into(),
            session_id: id.into(),
            num_recent_events: None,
            after: None,
        })
        .await?;
    Ok(session
        .state()
        .get(PLAN_KEY)
        .and_then(|value| serde_json::from_value(value).ok()))
}
// endregion wiring

// region run
/// 一次运行的可核对结果。
struct Report {
    stop: String,
    answer: Option<String>,
    trace: Vec<String>,
    /// 每次请求模型时，模型在请求里看到的清单
    seen: Vec<Plan>,
}

async fn run_once(lab: &Lab, session: &str) -> Result<Report> {
    let already = lab.model.requests.lock().unwrap().len();
    let question = Content::new("user").with_text(GOAL);
    let mut stream = lab.runner.run_str("reader", session, question).await?;
    let (mut trace, mut stop, mut answer) = (Vec::new(), "ended".to_string(), None);
    while let Some(event) = stream.next().await {
        match event {
            Ok(event) => {
                trace.extend(trace::event_lines(&event));
                if event.is_final_response() && event.author == "assistant" {
                    answer = event
                        .content()
                        .map(|c| c.parts.iter().filter_map(Part::text).collect::<String>())
                        .filter(|text| !text.is_empty());
                    if answer.is_some() {
                        stop = "answer".into();
                    }
                }
            }
            Err(error) => {
                trace.push(format!("[run] error   {}", error.code));
                stop = error.code.to_string();
                break;
            }
        }
    }
    let seen = lab.model.requests.lock().unwrap()[already..]
        .iter()
        .map(plan_in)
        .collect();
    Ok(Report {
        stop,
        answer,
        trace,
        seen,
    })
}
// endregion run

fn workspace(with_readme: bool) -> Result<(tempfile::TempDir, Arc<PathBuf>)> {
    let directory = tempfile::tempdir()?;
    if with_readme {
        fs::write(directory.path().join("README.md"), README)?;
    }
    let root = Arc::new(directory.path().canonicalize()?);
    Ok((directory, root))
}

fn new_model(claims_only: bool) -> Arc<PlanLlm> {
    Arc::new(PlanLlm {
        claims_only,
        requests: Mutex::new(Vec::new()),
    })
}

fn statuses(plan: &Plan) -> String {
    if plan.items.is_empty() {
        return "未建单".into();
    }
    plan.items
        .iter()
        .map(|item| {
            let status = serde_json::to_value(item.status).unwrap();
            format!("{}={}", item.id, status.as_str().unwrap())
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// 主流程类场景：一次（或两次）完整运行。返回摘要行和详细轨迹。
async fn flow(name: &str) -> Result<(String, Vec<String>)> {
    let (_dir, root) = workspace(name != "read-error")?;
    let visibility = if name == "template-only" {
        Visibility::TemplateOnly
    } else {
        Visibility::Live
    };
    let budget = (name == "budget-stop").then_some(3);
    let lab = lab(
        root.clone(),
        new_model(name == "claims-only"),
        visibility,
        budget,
    )?;
    open_session(&lab, "s1", None).await?;
    let report = run_once(&lab, "s1").await?;
    let plan = session_plan(&lab, "s1").await?.unwrap_or_else(Plan::new);
    let reads = lab.reads.0.load(Ordering::SeqCst);
    let all_completed =
        !plan.items.is_empty() && plan.items.iter().all(|i| i.status == Status::Completed);
    // 独立验收：真实读过一次，并且回答等于“启动说明”加读到的原文
    let expected = fs::read_to_string(root.join("README.md")).ok();
    let goal_verified = reads == 1
        && expected
            .as_ref()
            .is_some_and(|text| report.answer.as_deref() == Some(&format!("启动说明：\n{text}")));
    let mut detail = report.trace.clone();
    for (i, seen) in report.seen.iter().enumerate() {
        detail.push(format!(
            "request {}: revision={} {}",
            i + 1,
            seen.revision,
            statuses(seen)
        ));
    }
    let mut line = format!(
        "{name}: stop={} model_calls={} revision={} reads={reads} completed={all_completed} goal_verified={goal_verified} seen_revisions={:?}",
        report.stop,
        report.seen.len(),
        plan.revision,
        report.seen.iter().map(|p| p.revision).collect::<Vec<_>>()
    );
    match name {
        "template-only" => {
            // 下一次运行开始时模板重新渲染：这时才看到上一次运行留下的版本 1
            let again = run_once(&lab, "s1").await?;
            line = format!(
                "{line} next_run_first_seen={}",
                again.seen.first().map_or(0, |p| p.revision)
            );
        }
        "next-run" => {
            // 同一个会话再运行一次：清单还在会话状态里
            let again = run_once(&lab, "s1").await?;
            line = format!(
                "next-run: first_run_revision={} second_run_first_seen={}",
                plan.revision,
                again.seen.first().map_or(0, |p| p.revision)
            );
        }
        "fresh-session" => {
            open_session(&lab, "s2", None).await?;
            let other = session_plan(&lab, "s2").await?;
            line = format!(
                "fresh-session: s1_revision={} s2_plan={}",
                plan.revision,
                other.map_or("none".into(), |p| p.revision.to_string())
            );
        }
        _ => {}
    }
    Ok((line, detail))
}

// region candidates
/// 校验类场景：先在会话状态里放好一份清单，模型只提交一次候选，然后核对结果和状态。
async fn candidate(name: &str) -> Result<(String, Vec<String>)> {
    let (_dir, root) = workspace(true)?;
    let mut seed = Plan::new();
    seed.write(WriteArgs {
        expected_revision: 0,
        items: initial_items(),
    })?;
    let advance = |plan: &mut Plan, status: Status| {
        let mut items = plan.items.clone();
        items[0].status = status;
        plan.write(WriteArgs {
            expected_revision: plan.revision,
            items,
        })
    };
    if matches!(name, "reopen-completed" | "yield-step") {
        advance(&mut seed, Status::InProgress)?;
    }
    if name == "reopen-completed" {
        advance(&mut seed, Status::Completed)?;
    }
    if name == "permission-denied" {
        let mut items = seed.items.clone();
        items.push(Item {
            id: "write".into(),
            content: "写入 summary.txt".into(),
            status: Status::Pending,
        });
        seed.write(WriteArgs {
            expected_revision: seed.revision,
            items,
        })?;
    }
    if name.starts_with("same-batch") {
        return same_batch(name, root, seed).await;
    }
    let mut items = seed.items.clone();
    let mut args = None;
    match name {
        "two-active" => {
            items[0].status = Status::InProgress;
            items[1].status = Status::InProgress;
        }
        "skip-completion" => items[0].status = Status::Completed,
        "duplicate-id" => items[1].id = items[0].id.clone(),
        "empty-content" => items[0].content = "  ".into(),
        "too-many" => items.extend((3..9).map(|i| Item {
            id: format!("extra-{i}"),
            content: "新增步骤".into(),
            status: Status::Pending,
        })),
        "remove-item" => {
            items.pop();
        }
        "changed-content" => items[0].content = "悄悄换了目标".into(),
        "reopen-completed" => items[0].status = Status::InProgress,
        "append-step" => items.push(Item {
            id: "verify-env".into(),
            content: "补查环境要求".into(),
            status: Status::Pending,
        }),
        "yield-step" => {
            items[0].status = Status::Pending;
            items[1].status = Status::InProgress;
        }
        "stale-revision" => args = Some(json!({ "expected_revision": 0, "items": items })),
        "unknown-status" => {
            let mut value = json!({ "expected_revision": seed.revision, "items": items });
            value["items"][0]["status"] = json!("done");
            args = Some(value);
        }
        "unknown-field" => {
            args =
                Some(json!({ "expected_revision": seed.revision, "items": items, "force": true }))
        }
        "wrong-type" => args = Some(json!({ "expected_revision": "one", "items": items })),
        "permission-denied" => {}
        _ => return Err(format!("unknown scenario: {name}").into()),
    }
    let (tool, args) = if name == "permission-denied" {
        (
            "write_file",
            json!({ "path": "summary.txt", "content": "hello" }),
        )
    } else {
        (
            "todo_write",
            args.unwrap_or_else(|| json!({ "expected_revision": seed.revision, "items": items })),
        )
    };
    let model = Arc::new(adk_model::ScriptedLlm::new(
        "scripted",
        vec![
            adk_model::ScriptedResponse::function_call(tool, args),
            adk_model::ScriptedResponse::text("已提交"),
        ],
    ));
    let runner_lab = scripted_lab(root.clone(), model, true)?;
    open_session(&runner_lab, "s1", Some(&seed)).await?;
    let report = run_once(&runner_lab, "s1").await?;
    let after = session_plan(&runner_lab, "s1").await?.expect("seeded plan");
    let result = report
        .trace
        .iter()
        .find(|line| line.contains("] result "))
        .cloned()
        .unwrap_or_default();
    let status = result
        .split_whitespace()
        .find_map(|word| word.strip_prefix("status="))
        .unwrap_or("-")
        .to_string();
    let code = result
        .split_whitespace()
        .find_map(|word| word.strip_prefix("code="))
        .unwrap_or("-")
        .to_string();
    let unchanged = after == seed;
    let summary_exists = root.join("summary.txt").exists();
    Ok((
        format!(
            "{name}: status={status} code={code} unchanged={unchanged} revision={}->{} summary_exists={summary_exists}",
            seed.revision, after.revision
        ),
        report.trace,
    ))
}

// region same-batch
/// 一次模型回复里两个 todo_write，都基于版本 1：一个开始读取，一个新增步骤。
/// 两个调用的事件要等整批执行完才产出，所以第二个调用读会话状态时，第一个的写入还没合并。
async fn same_batch(name: &str, root: Arc<PathBuf>, seed: Plan) -> Result<(String, Vec<String>)> {
    let mut start = seed.items.clone();
    start[0].status = Status::InProgress;
    let mut append = seed.items.clone();
    append.push(Item {
        id: "verify-env".into(),
        content: "补查环境要求".into(),
        status: Status::Pending,
    });
    let model = Arc::new(adk_model::ScriptedLlm::new(
        "scripted",
        vec![
            adk_model::ScriptedResponse::function_calls([
                (
                    "todo_write",
                    json!({ "expected_revision": 1, "items": start }),
                ),
                (
                    "todo_write",
                    json!({ "expected_revision": 1, "items": append }),
                ),
            ]),
            adk_model::ScriptedResponse::text("已提交"),
        ],
    ));
    let lab = scripted_lab(root, model, name == "same-batch")?;
    open_session(&lab, "s1", Some(&seed)).await?;
    let report = run_once(&lab, "s1").await?;
    let after = session_plan(&lab, "s1").await?.expect("seeded plan");
    let results: Vec<String> = report
        .trace
        .iter()
        .filter(|line| line.contains("] result "))
        .map(|line| {
            let field = |key: &str| {
                line.split_whitespace()
                    .find_map(|w| w.strip_prefix(key))
                    .map(str::to_owned)
            };
            field("code=").unwrap_or_else(|| field("status=").unwrap_or_default())
        })
        .collect();
    let started = after.items[0].status == Status::InProgress;
    let appended = after.items.iter().any(|item| item.id == "verify-env");
    Ok((
        format!(
            "{name}: results={} revision={}->{} read_started={started} step_appended={appended} lost_update={}",
            results.join(","),
            seed.revision,
            after.revision,
            results.iter().all(|r| r == "ok") && !(started && appended)
        ),
        report.trace,
    ))
}
// endregion same-batch

/// 校验类场景用脚本模型：只提交一次候选，不需要看清单。
fn scripted_lab(
    root: Arc<PathBuf>,
    model: Arc<adk_model::ScriptedLlm>,
    remember_batch: bool,
) -> Result<Lab> {
    let reads = Arc::new(Reads::default());
    let agent = LlmAgentBuilder::new("assistant")
        .model(model)
        .tool(Arc::new(todo_write(remember_batch)))
        .tool(Arc::new(todo_read()))
        .tool(Arc::new(read_file(root.clone(), reads.clone())))
        .tool(Arc::new(write_file(root)))
        .build()?;
    let policy = DeclarativePolicy::builder()
        .allow("todo_write")
        .allow("todo_read")
        .allow("read_file")
        .deny("write_file", "本章只读：不允许写文件");
    let sessions = Arc::new(InMemorySessionService::new());
    let runner = Runner::builder()
        .app_name("r05")
        .agent(Arc::new(agent))
        .session_service(sessions.clone())
        .tool_policy(Arc::new(policy.build()))
        .without_intra_compaction()
        .build()?;
    Ok(Lab {
        runner,
        sessions,
        model: new_model(false),
        reads,
    })
}
// endregion candidates

async fn scenario(name: &str) -> Result<(String, Vec<String>)> {
    if CASES.iter().position(|c| *c == name).is_some_and(|i| i < 7) {
        flow(name).await
    } else {
        candidate(name).await
    }
}

async fn cli(args: &[String]) -> Result<()> {
    match args {
        [] => {
            for name in CASES {
                println!("{}", scenario(name).await?.0);
            }
            Ok(())
        }
        [name] if CASES.contains(&name.as_str()) => {
            let (line, detail) = scenario(name).await?;
            for row in detail {
                println!("{row}");
            }
            println!("{line}");
            Ok(())
        }
        _ => Err(format!("usage: learn-agent-r05 [{}]", CASES.join("|")).into()),
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

    #[test]
    fn exhaustive_transition_matrix() {
        use Status::*;
        let states = [Pending, InProgress, Completed];
        let expected = [
            [true, true, false],
            [true, true, true],
            [false, false, true],
        ];
        for (i, from) in states.into_iter().enumerate() {
            for (j, to) in states.into_iter().enumerate() {
                assert_eq!(can_move(from, to), expected[i][j]);
            }
        }
    }

    #[test]
    fn reject_entire_batch_after_valid_first_change() {
        let mut plan = Plan::new();
        plan.write(WriteArgs {
            expected_revision: 0,
            items: initial_items(),
        })
        .unwrap();
        let before = plan.clone();
        let mut items = plan.items.clone();
        items[0].status = Status::InProgress;
        items[2].content = " ".into();
        assert_eq!(
            plan.write(WriteArgs {
                expected_revision: 1,
                items
            }),
            Err("todo.invalid_content")
        );
        assert_eq!(plan, before);
    }

    #[tokio::test]
    async fn the_model_sees_the_latest_plan_before_every_request() {
        let (_dir, root) = workspace(true).unwrap();
        let lab = lab(root, new_model(false), Visibility::Live, None).unwrap();
        open_session(&lab, "s1", None).await.unwrap();
        let report = run_once(&lab, "s1").await.unwrap();
        let revisions: Vec<u64> = report.seen.iter().map(|p| p.revision).collect();
        assert_eq!(revisions, [0, 1, 2, 2, 3, 4, 5]);
        assert_eq!(report.stop, "answer");
    }

    #[tokio::test]
    async fn a_template_renders_once_per_run() {
        let (_dir, root) = workspace(true).unwrap();
        let lab = lab(root, new_model(false), Visibility::TemplateOnly, None).unwrap();
        open_session(&lab, "s1", None).await.unwrap();
        let report = run_once(&lab, "s1").await.unwrap();
        assert!(report.seen.iter().all(|p| p.revision == 0));
        let again = run_once(&lab, "s1").await.unwrap();
        assert_eq!(again.seen.first().map(|p| p.revision), Some(1));
        assert!(
            report
                .trace
                .iter()
                .any(|l| l.contains("code=todo.revision_conflict"))
        );
    }

    #[tokio::test]
    async fn rejected_candidates_leave_the_plan_unchanged() {
        for name in CASES
            .iter()
            .filter(|name| !name.starts_with("same-batch"))
            .skip(7)
        {
            let (line, _) = scenario(name).await.unwrap();
            let expect_change = matches!(*name, "append-step" | "yield-step");
            assert_eq!(line.contains("unchanged=true"), !expect_change, "{line}");
            assert!(line.contains("summary_exists=false"), "{line}");
            let accepted = line.contains("status=ok");
            let refused = line.contains("status=refused");
            assert!(
                accepted == expect_change && (accepted || refused || line.contains("code=todo.")),
                "{line}"
            );
        }
    }

    #[tokio::test]
    async fn a_second_write_in_the_same_batch_sees_the_first() {
        let (naive, _) = scenario("same-batch-naive").await.unwrap();
        assert!(
            naive.contains("results=ok,ok") && naive.contains("lost_update=true"),
            "{naive}"
        );
        let (fixed, _) = scenario("same-batch").await.unwrap();
        assert!(
            fixed.contains("results=ok,todo.revision_conflict")
                && fixed.contains("read_started=true"),
            "{fixed}"
        );
    }

    #[tokio::test]
    async fn answer_uses_changed_readme_not_a_canned_command() {
        let (_dir, root) = workspace(false).unwrap();
        fs::write(root.join("README.md"), "启动命令：just dev\n").unwrap();
        let lab = lab(root, new_model(false), Visibility::Live, None).unwrap();
        open_session(&lab, "s1", None).await.unwrap();
        let report = run_once(&lab, "s1").await.unwrap();
        assert_eq!(
            report.answer.as_deref(),
            Some("启动说明：\n启动命令：just dev\n")
        );
    }

    #[test]
    fn identifier_and_content_limits_are_checked() {
        for (id, content) in [
            ("UPPER".into(), "步骤".into()),
            ("x".repeat(25), "步骤".into()),
            ("ok".into(), "字".repeat(121)),
        ] {
            let mut plan = Plan::new();
            let items = vec![Item {
                id,
                content,
                status: Status::Pending,
            }];
            assert!(
                plan.write(WriteArgs {
                    expected_revision: 0,
                    items
                })
                .is_err()
            );
            assert_eq!(plan, Plan::new());
        }
        assert_eq!(
            Plan::new().write(WriteArgs {
                expected_revision: 0,
                items: vec![]
            }),
            Err("todo.item_count")
        );
    }
}
