//! D05（ADK-Rust 3.0）：协调者、工作者与任务交接。
//!
//!   cargo run --locked                 全部场景的摘要
//!   cargo run --locked -- handoff      某个场景的完整轨迹（场景名见 CASES）
//!
//! 升级审查团队用 `TeamSpec` 声明：协调者 lead、工作者 member_check、许可证专员 license。
//! lead → member_check 是委派（Delegate）：工作者当工具调用，结果交回 lead，lead 接着说话；
//! lead → license 是交接（Handoff）：控制权交给 license，lead 不再接着说话。
//! 三个成员都是 `LlmAgent`，模型是按规则回复的替身；工作者每次请求先停一小会儿，
//! 并记录同一时刻有几次请求在进行。运行时使用暂停的 Tokio 时钟，完成顺序是确定的。
mod trace;

use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use adk_agent::{CompiledTeam, LlmAgentBuilder, TeamExecutionSnapshot, TeamSpec};
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, FinishReason, Llm,
    LlmRequest, LlmResponse, LlmResponseStream, Part, ToolContext, ToolEffect,
    ToolExecutionStrategy,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const TURN2: &str = "好的，接下来呢？";

const CASES: &[&str] = &[
    "two",
    "three",
    "shared-context",
    "handoff",
    "handoff-note",
    "undeclared",
    "worker-failed",
    "budget",
    "cycle",
    "interrupted",
];

/// 每个场景的工作区成员清单：协调者按清单决定派几个工作者。
fn manifest(scenario: &str) -> &'static [&'static str] {
    match scenario {
        "two" | "shared-context" | "worker-failed" => &["api", "cli"],
        _ => &["api", "cli", "core"],
    }
}

// region spec
/// 团队定义是数据：成员、协调者、关系和策略。这里直接写成 JSON，再反序列化成 `TeamSpec`。
fn team_spec(scenario: &str) -> Result<TeamSpec> {
    // 委派边：工作者看不到 lead 的会话状态与对话（isolated），失败时把错误作为结果交回 lead
    let delegate_context = if scenario == "shared-context" {
        "shared"
    } else {
        "isolated"
    };
    let mut relationships = vec![
        json!({
            "from": "lead", "to": "member_check", "kind": "delegate",
            "policy": { "context": delegate_context, "failure": { "strategy": "returnError" } }
        }),
        json!({ "from": "lead", "to": "license", "kind": "handoff" }),
    ];
    if scenario == "cycle" {
        // 想让 license 处理完再把控制权“交回” lead
        relationships.push(json!({ "from": "license", "to": "lead", "kind": "handoff" }));
    }
    let mut budget = json!({});
    if scenario == "budget" {
        budget = json!({ "maxDelegations": 2 });
    }
    let spec = json!({
        "name": "upgrade_review",
        "coordinator": "lead",
        "members": [
            { "name": "lead" },
            { "name": "member_check", "description": "检查一个工作区成员的升级影响与许可证" },
            { "name": "license", "description": "处理许可证问题" }
        ],
        "relationships": relationships,
        "policy": {
            "maxTransferDepth": 2,
            "maxDelegationDepth": 1,
            "maxConcurrentDelegations": 2,
            "context": "isolated",
            "failure": "propagate",
            "budget": budget
        }
    });
    Ok(serde_json::from_value(spec)?)
}
// endregion spec

// region model
/// 替身模型：按系统消息里的“角色：xxx”扮演协调者、工作者或许可证专员。
struct TeamLlm {
    scenario: String,
    in_flight: AtomicUsize,
    peak: AtomicUsize,
    /// 工作者被派到的成员，按开始的先后
    started: Mutex<Vec<String>>,
    /// 工作者每次请求能不能看到 lead 会话里的审查备忘（状态键 audit_note）
    worker_saw: Mutex<Vec<&'static str>>,
    worker_messages: Mutex<Vec<usize>>,
    /// 每个工作者开始的时刻（暂停时钟上的毫秒数）
    worker_started_ms: Mutex<Vec<u128>>,
    clock: tokio::time::Instant,
    /// license 第一次回答时，系统消息里有没有交接说明
    license_knew: Mutex<Option<bool>>,
}

fn texts(content: &Content) -> String {
    content.parts.iter().filter_map(Part::text).collect()
}

fn role_of(request: &LlmRequest) -> String {
    request
        .contents
        .iter()
        .filter(|c| c.role == "system")
        .map(texts)
        .find_map(|t| t.split("角色：").nth(1).map(str::to_owned))
        .and_then(|t| t.split_whitespace().next().map(str::to_owned))
        .unwrap_or_default()
}

fn reply(parts: Vec<Part>) -> adk_core::Result<LlmResponseStream> {
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts,
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    Ok(Box::pin(futures::stream::iter([Ok(response)])))
}

fn text(t: impl Into<String>) -> Part {
    Part::Text { text: t.into() }
}

fn call(name: &str, args: Value, id: &str) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args,
        id: Some(id.into()),
        thought_signature: None,
    }
}

impl TeamLlm {
    /// 协调者：按清单一次派出全部工作者；拿到结果后，有许可证问题就交接，否则汇总。
    fn lead(&self, request: &LlmRequest) -> Vec<Part> {
        let last_user = request
            .contents
            .iter()
            .rev()
            .find(|c| c.role == "user")
            .map(texts)
            .unwrap_or_default();
        if last_user == TURN2 {
            return vec![text("lead：审查已经汇总完了，没有别的待办。")];
        }
        let responses: Vec<(String, Value)> = request
            .contents
            .iter()
            .flat_map(|c| c.parts.iter())
            .filter_map(|p| match p {
                Part::FunctionResponse {
                    function_response, ..
                } => Some((
                    function_response.name.clone(),
                    function_response.response.clone(),
                )),
                _ => None,
            })
            .collect();
        let noted = responses.iter().any(|(name, _)| name == "handoff_note");
        if responses
            .iter()
            .any(|(name, _)| name == "transfer_to_agent")
        {
            return vec![text(
                "lead：交接被拒绝，许可证问题先记下，由 lead 继续跟进。",
            )];
        }
        let results: Vec<&Value> = responses
            .iter()
            .filter(|(name, _)| name == "member_check")
            .map(|(_, v)| v)
            .collect();
        if results.is_empty() {
            // 一次回复里给每个成员各发一个委派调用：派几个由清单决定
            return manifest(&self.scenario)
                .iter()
                .map(|m| {
                    call(
                        "member_check",
                        json!({ "request": format!("检查成员 {m} 修订 r2") }),
                        &format!("check-{m}"),
                    )
                })
                .collect();
        }
        let mut lines = Vec::new();
        let mut license_issue = false;
        for result in results {
            if let Some(error) = result.get("error") {
                lines.push(format!("检查失败（{}）", error.as_str().unwrap_or("?")));
                continue;
            }
            let finding: Value = result["response"]
                .as_str()
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or(Value::Null);
            license_issue |= finding["license"] == "GPL-3.0";
            lines.push(format!(
                "{}：{}",
                finding["member"].as_str().unwrap_or("?"),
                finding["finding"].as_str().unwrap_or("?")
            ));
        }
        if license_issue && self.scenario == "handoff-note" && !noted {
            // 先把接手者需要知道的事写成交接说明，下一次回复再交接
            return vec![call(
                "handoff_note",
                json!({ "note": "core 引入了 GPL-3.0 依赖（member_check 的检查结果），需要判断能不能用" }),
                "note",
            )];
        }
        if license_issue {
            let target = if self.scenario == "undeclared" {
                "member_check"
            } else {
                "license"
            };
            return vec![call(
                "transfer_to_agent",
                json!({ "agent_name": target }),
                "handoff",
            )];
        }
        vec![text(format!("lead 汇总：{}", lines.join("；")))]
    }

    /// 工作者：只看自己收到的请求，回一个 JSON 发现。
    async fn worker(&self, request: &LlmRequest) -> adk_core::Result<Part> {
        let asked = request
            .contents
            .iter()
            .rev()
            .find(|c| c.role == "user")
            .map(texts)
            .unwrap_or_default();
        let member = asked.split_whitespace().nth(1).unwrap_or("?").to_owned();
        // 指令模板 {audit_note?} 渲染自工作者自己的会话状态：看得到 lead 的状态，这里才有内容
        let saw_note = request
            .contents
            .iter()
            .filter(|c| c.role == "system")
            .any(|c| texts(c).contains("cli 曾有许可证争议"));
        self.worker_saw
            .lock()
            .unwrap()
            .push(if saw_note { "note" } else { "-" });
        // 除系统消息以外，工作者的请求里有几条消息（共享上下文时会复制 lead 的历史）
        let messages = request
            .contents
            .iter()
            .filter(|c| c.role != "system")
            .count();
        self.worker_messages.lock().unwrap().push(messages);
        self.worker_started_ms
            .lock()
            .unwrap()
            .push(self.clock.elapsed().as_millis());
        self.started.lock().unwrap().push(member.clone());
        let now = self.in_flight.fetch_add(1, Ordering::SeqCst) + 1;
        self.peak.fetch_max(now, Ordering::SeqCst);
        let order = ["api", "cli", "core"]
            .iter()
            .position(|m| *m == member)
            .unwrap_or(0) as u64;
        tokio::time::sleep(Duration::from_millis(30 + order * 40)).await;
        self.in_flight.fetch_sub(1, Ordering::SeqCst);
        if self.scenario == "worker-failed" && member == "cli" {
            return Err(AdkError::new(
                ErrorComponent::Model,
                ErrorCategory::Unavailable,
                "model.unavailable",
                "team-llm: cli 的检查服务没有响应",
            ));
        }
        let (license, finding) = match member.as_str() {
            "api" => ("MIT", "接口不变"),
            "cli" => ("MIT", "一个命令行参数改名"),
            _ => ("GPL-3.0", "新依赖使用 GPL-3.0"),
        };
        // three 和 budget 里 core 没有许可证问题
        let (license, finding) =
            if member == "core" && matches!(self.scenario.as_str(), "three" | "budget") {
                ("MIT", "核心库只改了内部实现")
            } else {
                (license, finding)
            };
        Ok(text(
            json!({ "member": member, "license": license, "finding": finding }).to_string(),
        ))
    }

    fn license(&self, request: &LlmRequest) -> Part {
        // 交接说明经指令模板 {handoff_note?} 进入系统消息。这里查请求里的全部消息：
        // 没有交接说明时，历史里也找不到工作者交回的 GPL-3.0 结果
        let knew = request
            .contents
            .iter()
            .any(|c| texts(c).contains("GPL-3.0"));
        self.license_knew.lock().unwrap().get_or_insert(knew);
        let last_user = request
            .contents
            .iter()
            .rev()
            .find(|c| c.role == "user")
            .map(texts)
            .unwrap_or_default();
        match (knew, last_user == TURN2) {
            (true, false) => {
                text("license：收到交接说明，core 引入了 GPL-3.0 依赖，升级先暂停，等许可证结论。")
            }
            (true, true) => text("license：请先提交 core 那个依赖的许可证说明，我来判断能不能用。"),
            (false, false) => {
                text("license：我只看到“审查升级 r2”，不知道是哪个许可证问题，请补充说明。")
            }
            (false, true) => text("license：还是需要你说明是哪个成员、什么许可证。"),
        }
    }
}

#[async_trait]
impl Llm for TeamLlm {
    fn name(&self) -> &str {
        "team-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let parts = match role_of(&request).as_str() {
            "lead" => self.lead(&request),
            "member_check" => vec![self.worker(&request).await?],
            _ => vec![self.license(&request)],
        };
        reply(parts)
    }
}
// endregion model

// region note
/// handoff_note：lead 交接前把接手者需要知道的事写进会话状态。license 的指令模板会读到它。
fn handoff_note() -> FunctionTool {
    FunctionTool::new(
        "handoff_note",
        "交接前写一段说明给接手者：note 写清是什么问题、证据从哪里来。",
        |ctx: Arc<dyn ToolContext>, args: Value| async move {
            let mut actions = ctx.actions();
            actions
                .state_delta
                .insert("handoff_note".into(), args["note"].clone());
            ctx.set_actions(actions);
            Ok(json!({ "status": "noted" }))
        },
    )
    // 同一段说明写两次，结果一样
    .with_effect(ToolEffect::Idempotent)
}
// endregion note

// region team
/// 三个成员都是普通的 `LlmAgent`；`TeamSpec::compile` 按名字把它们绑到声明的成员上。
/// lead 一次回复里的几个委派调用并发执行（`Parallel`），同时进行的委派不超过策略里的 2 个。
fn build_team(
    spec: &TeamSpec,
    model: Arc<TeamLlm>,
) -> Result<std::result::Result<CompiledTeam, adk_agent::TeamError>> {
    let lead = LlmAgentBuilder::new("lead")
        .instruction("角色：lead 协调升级审查：按成员清单把检查派给工作者，汇总结果；许可证问题交给 license。")
        .model(model.clone())
        .tool(Arc::new(handoff_note()))
        .tool_execution_strategy(ToolExecutionStrategy::Parallel)
        .build()?;
    let worker = LlmAgentBuilder::new("member_check")
        .instruction(
            "角色：member_check 只检查请求里的那一个成员，回一个 JSON 发现。备忘：{audit_note?}",
        )
        .model(model.clone())
        .build()?;
    let license = LlmAgentBuilder::new("license")
        .instruction("角色：license 接手许可证问题，直到问题有结论。交接说明：{handoff_note?}")
        .model(model)
        .build()?;
    let agents: [Arc<dyn Agent>; 3] = [Arc::new(lead), Arc::new(worker), Arc::new(license)];
    Ok(spec.compile(agents))
}
// endregion team

// region receipt
/// 执行回执里的关系执行，按开始先后排列。`long` 为真时写成“来源→目标 种类 状态”，否则只写“种类:状态”。
/// （交接的执行 id 是随机的 UUID，这里不打印 id。）
fn edges(snapshot: &TeamExecutionSnapshot, long: bool) -> Vec<String> {
    snapshot
        .edges
        .iter()
        .map(|e| {
            let kind = format!("{:?}", e.kind).to_lowercase();
            let status = format!("{:?}", e.status).to_lowercase();
            if long {
                format!("{}→{} {kind} {status}", e.from, e.to)
            } else {
                format!("{kind}:{status}")
            }
        })
        .collect()
}
// endregion receipt

// region run
struct Turn {
    invocation: String,
    answered_by: String,
    error: Option<String>,
}

async fn turn(
    runner: &Runner,
    message: &str,
    lines: &mut Vec<String>,
    stop_at_first_worker_event: bool,
) -> Result<Turn> {
    lines.push(format!("--- turn: {message}"));
    let mut out = Turn {
        invocation: String::new(),
        answered_by: String::new(),
        error: None,
    };
    let mut stream = runner
        .run_with_config(
            "user".try_into()?,
            "s1".try_into()?,
            Content::new("user").with_text(message),
            None,
        )
        .await?;
    while let Some(event) = stream.next().await {
        let event = match event {
            Ok(event) => event,
            Err(error) => {
                lines.push(format!("[error] {error}"));
                out.error = Some(error.code.to_string());
                break;
            }
        };
        if out.invocation.is_empty() {
            out.invocation = event.invocation_id.clone();
        }
        // 执行回执每次变化都镜像进会话状态，轨迹里不逐条打印，结束时单独打印一行
        let event_lines: Vec<String> = trace::event_lines(&event)
            .into_iter()
            .filter(|l| !l.contains("state   __adk_team_execution_v1"))
            .collect();
        if !(event_lines.len() == 1 && event_lines[0].ends_with("] final")) {
            lines.extend(event_lines);
        }
        if let Some(target) = &event.actions.transfer_to_agent {
            lines.push(format!("[{}] handoff → {target}", event.author));
        }
        if event.is_final_response()
            && event.author != "member_check"
            && event
                .content()
                .is_some_and(|c| c.parts.iter().any(|p| p.text().is_some()))
        {
            out.answered_by = event.author.clone();
        }
        if stop_at_first_worker_event && event.author == "member_check" {
            lines.push("[host] 进程在这里中断：事件流被丢弃，其余委派还没有结果".into());
            break;
        }
    }
    Ok(out)
}

async fn run(scenario: &str) -> Result<(Vec<String>, String)> {
    let model = Arc::new(TeamLlm {
        scenario: scenario.into(),
        in_flight: AtomicUsize::new(0),
        peak: AtomicUsize::new(0),
        started: Mutex::new(Vec::new()),
        worker_saw: Mutex::new(Vec::new()),
        worker_messages: Mutex::new(Vec::new()),
        worker_started_ms: Mutex::new(Vec::new()),
        clock: tokio::time::Instant::now(),
        license_knew: Mutex::new(None),
    });
    let mut lines = Vec::new();
    let spec = team_spec(scenario)?;
    let team = match build_team(&spec, model.clone())? {
        Ok(team) => Arc::new(team),
        Err(error) => {
            lines.push(format!("[compile] {error}"));
            let kind = format!("{error:?}");
            let kind = kind.split('(').next().unwrap_or("?");
            let summary = format!("{scenario}: stop=invalid_spec:{kind}");
            lines.push(summary.clone());
            return Ok((lines, summary));
        }
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "d05".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            // lead 一侧的会话状态：一条只该 lead 看到的审查备忘
            state: [(
                "audit_note".to_string(),
                json!("上次审查：cli 曾有许可证争议"),
            )]
            .into(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("d05")
        .agent(team.clone())
        .session_service(sessions)
        .tool_policy(Arc::new(
            DeclarativePolicy::builder()
                .allow("member_check")
                .allow("handoff_note")
                .build(),
        ))
        .without_intra_compaction()
        .build()?;
    let task = format!("审查升级 r2。工作区成员：{}", manifest(scenario).join(","));
    let interrupted = scenario == "interrupted";
    let first = turn(&runner, &task, &mut lines, interrupted).await?;
    let receipt = team
        .execution_snapshot(&first.invocation)
        .ok_or("no team receipt")?;
    lines.push(format!("[receipt] {}", edges(&receipt, true).join("；")));
    let messages = model.worker_messages.lock().unwrap().clone();
    if !messages.is_empty() {
        lines.push(format!(
            "[workers] 每次请求除系统消息外的消息数：{messages:?}"
        ));
        lines.push(format!(
            "[workers] 开始时刻（毫秒）：{:?}",
            model.worker_started_ms.lock().unwrap()
        ));
    }
    let outcome = if interrupted {
        let plan = team
            .resume_plan(&first.invocation)
            .ok_or("no resume plan")?;
        lines.push(format!("[resume] {plan:?}"));
        let action = format!("{plan:?}");
        format!(
            "stop=interrupted:{}",
            action.split(' ').next().unwrap_or("?")
        )
    } else if let Some(code) = &first.error {
        format!("stop=error:{code}")
    } else {
        let second = turn(&runner, TURN2, &mut lines, false).await?;
        let analysis = team
            .analyze_execution(&first.invocation)?
            .ok_or("no analysis")?;
        lines.push(format!("[analysis] {analysis:?}"));
        format!(
            "turn1={} turn2={}{} coverage={}%",
            first.answered_by,
            second.answered_by,
            match *model.license_knew.lock().unwrap() {
                Some(true) => " license_knew=yes",
                Some(false) => " license_knew=no",
                None => "",
            },
            analysis.coverage_basis_points / 100
        )
    };
    let summary = format!(
        "{scenario}: workers=[{}] peak={} worker_saw=[{}] edges=[{}] {outcome}",
        model.started.lock().unwrap().join(","),
        model.peak.load(Ordering::SeqCst),
        model.worker_saw.lock().unwrap().join(","),
        edges(&receipt, false).join(","),
    );
    lines.push(summary.clone());
    Ok((lines, summary))
}
// endregion run

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
        _ => Err(format!("usage: orchestrator-workers-handoffs [{}]", CASES.join("|")).into()),
    }
}

// 用暂停的时钟：停顿按到期先后推进，不受机器快慢影响，完成顺序是确定的
#[tokio::main(flavor = "current_thread", start_paused = true)]
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

    #[tokio::test(start_paused = true)]
    async fn the_manifest_decides_how_many_workers_and_the_policy_caps_concurrency() {
        let two = summary("two").await;
        let three = summary("three").await;
        assert!(two.contains("workers=[api,cli] peak=2"), "{two}");
        assert!(three.contains("workers=[api,cli,core] peak=2"), "{three}");
        assert!(
            three.ends_with("turn1=lead turn2=lead coverage=50%"),
            "{three}"
        );
    }

    #[tokio::test(start_paused = true)]
    async fn the_context_policy_decides_what_a_worker_sees() {
        assert!(summary("two").await.contains("worker_saw=[-,-]"));
        assert!(
            summary("shared-context")
                .await
                .contains("worker_saw=[note,note]")
        );
    }

    #[tokio::test(start_paused = true)]
    async fn a_handoff_keeps_control_with_the_target_and_only_declared_edges_hand_off() {
        let handoff = summary("handoff").await;
        assert!(
            handoff.ends_with(
                "handoff:completed] turn1=license turn2=license license_knew=no coverage=100%"
            ),
            "{handoff}"
        );
        assert!(
            summary("handoff-note")
                .await
                .contains("turn1=license turn2=license license_knew=yes")
        );
        assert!(summary("undeclared").await.contains("turn1=lead"));
        assert!(
            summary("cycle")
                .await
                .ends_with("stop=invalid_spec:CyclicTopology")
        );
    }

    #[tokio::test(start_paused = true)]
    async fn failures_budgets_and_interruptions_show_up_in_the_receipt() {
        let failed = summary("worker-failed").await;
        assert!(failed.contains("delegate:failed] turn1=lead"), "{failed}");
        assert!(
            summary("budget")
                .await
                .ends_with("stop=error:agent.team.budget_exceeded")
        );
        assert!(
            summary("interrupted")
                .await
                .ends_with("stop=interrupted:UnsafeDelegate")
        );
    }
}
