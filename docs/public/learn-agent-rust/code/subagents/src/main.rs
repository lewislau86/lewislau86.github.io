//! R06（ADK-Rust 3.0）：子 Agent 与上下文隔离。
//!
//!   cargo run --locked                    全部场景的摘要
//!   cargo run --locked -- normal          某个场景的完整轨迹（场景名见 CASES）
//!
//! 父 Agent（coordinator）把“从 README 提取启动命令”交给子 Agent（reader）：
//! 主线用 AgentTool 把子 Agent 当成工具调用（新的会话、只回传最终回答），
//! 对照用 transfer_to_agent 把控制权交给子 Agent。两边的模型都是按规则回复的 RuleLlm，
//! 只看得到各自的请求；文件工具真实读取临时目录。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, Agent, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, FinishReason, Llm,
    LlmRequest, LlmResponse, LlmResponseStream, Part, RunBudget, Tool, ToolContext, ToolEffect,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::{AgentTool, AgentToolSessionSnapshot, FunctionTool};
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// 写在用户发给父 Agent 的问题里：用来检查父会话的内容有没有被带进子 Agent 的请求。
/// （instruction 不进会话历史，放在那里检查不出任何东西。）
const PARENT_MARK: &str = "PARENT_ONLY_NOTE";
/// 只写在练习 README 里：用来检查原文有没有被整段带回父 Agent 的请求。
const CHILD_MARK: &str = "CHILD_RAW_ONLY";
const TASK: &str = "读取 README.md，只返回启动命令。";
/// 子任务说明与回传结果的长度上限（UTF-8 字节），本章选择的接口约束。
const MAX_TASK_BYTES: usize = 256;
const MAX_REPORT_BYTES: usize = 160;

const CASES: &[&str] = &[
    "normal",
    "changed-readme",
    "missing-file",
    "child-loop-limit",
    "global-model-budget",
    "global-tool-budget",
    "parent-answer-budget",
    "cancel",
    "cancel-before-start",
    "forbidden-path",
    "recursive",
    "invalid-task",
    "oversized-result",
    "model-error",
    "transfer",
];

fn readme(scenario: &str) -> Option<String> {
    let command = match scenario {
        "missing-file" => return None,
        "changed-readme" => "cargo run --release",
        _ => "cargo run",
    };
    Some(format!(
        "# 课程练习项目\n启动命令：{command}\n内部记录：{CHILD_MARK}\n"
    ))
}

// region model
/// 按规则回复的模型。父子各用一个实例，各自只看得到自己的请求。
struct RuleLlm {
    role: &'static str,
    scenario: String,
    requests: Mutex<Vec<LlmRequest>>,
    /// cancel 场景：子模型提出读取时，宿主请求取消
    cancel_on_read: Option<CancellationToken>,
}

fn last_result(request: &LlmRequest) -> Option<(String, Value)> {
    request
        .contents
        .iter()
        .flat_map(|content| &content.parts)
        .filter_map(|part| match part {
            Part::FunctionResponse {
                function_response, ..
            } => Some((
                function_response.name.clone(),
                function_response.response.clone(),
            )),
            _ => None,
        })
        .next_back()
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

/// 结果里的错误说明：工具失败时框架给模型的是 {"error": ...}。
fn error_of(result: &Value) -> Option<String> {
    result["error"].as_str().map(str::to_owned)
}

impl RuleLlm {
    fn parent(&self, request: &LlmRequest) -> Part {
        match last_result(request) {
            None if self.scenario == "transfer" => call(
                "transfer_to_agent",
                json!({ "agent_name": "reader" }),
                "parent/transfer-1",
            ),
            None => {
                let task = if self.scenario == "invalid-task" {
                    ""
                } else {
                    TASK
                };
                call("reader", json!({ "request": task }), "parent/delegate-1")
            }
            Some((_, result)) => match result["response"].as_str() {
                Some(report) if report.starts_with("启动命令：") => text(format!(
                    "项目的{}（由子 Agent 读取 README 得到）",
                    report.trim_end_matches('。')
                )),
                Some(report) if report.starts_with("任务未完成") => text(report),
                Some(report) => text(format!("任务未完成：{report}")),
                None => text(format!(
                    "任务未完成：{}",
                    error_of(&result).unwrap_or_else(|| "子 Agent 没有返回结果".into())
                )),
            },
        }
    }

    fn child(&self, request: &LlmRequest) -> adk_core::Result<Part> {
        if self.scenario == "model-error" {
            return Err(AdkError::new(
                ErrorComponent::Model,
                ErrorCategory::Unavailable,
                "model.unavailable",
                "rule-llm: simulated provider failure",
            ));
        }
        Ok(match last_result(request) {
            None => {
                if let Some(token) = &self.cancel_on_read {
                    token.cancel();
                }
                match self.scenario.as_str() {
                    "forbidden-path" => call(
                        "read_file",
                        json!({ "path": "private.txt" }),
                        "child-1/read-1",
                    ),
                    // 子 Agent 试图再委派：它的工具里根本没有 reader
                    "recursive" => call("reader", json!({ "request": TASK }), "child-1/delegate-1"),
                    _ => call(
                        "read_file",
                        json!({ "path": "README.md" }),
                        "child-1/read-1",
                    ),
                }
            }
            Some((_, result)) => {
                let readme = result["text"].as_str().unwrap_or_default();
                match readme.lines().find_map(|l| l.strip_prefix("启动命令：")) {
                    Some(command) if self.scenario == "oversized-result" => {
                        text(format!("启动命令：{command}。{}", "补充说明。".repeat(20)))
                    }
                    Some(command) => text(format!("启动命令：{command}")),
                    None => text(format!(
                        "任务未完成：{}",
                        error_of(&result).unwrap_or_else(|| "README 里没有启动命令".into())
                    )),
                }
            }
        })
    }
}

#[async_trait]
impl Llm for RuleLlm {
    fn name(&self) -> &str {
        self.role
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        self.requests.lock().unwrap().push(request.clone());
        let part = if self.role == "parent" {
            self.parent(&request)
        } else {
            self.child(&request)?
        };
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

// region tool
#[derive(Default)]
struct Counters {
    read_attempts: AtomicUsize,
    read_successes: AtomicUsize,
}

/// 子 Agent 唯一的工具：只允许读 README.md，执行前再检查一次路径。
fn read_file(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            // 每次读取请求都计数，包括下面被拒绝的
            counters.read_attempts.fetch_add(1, Ordering::SeqCst);
            if args["path"] != "README.md" {
                return Err(AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Forbidden,
                    "path.not_allowed",
                    "只允许读取练习目录的 README.md",
                ));
            }
            let text = fs::read_to_string(root.join("README.md")).map_err(|_| {
                AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::NotFound,
                    "file.missing",
                    "练习目录中不存在 README.md",
                )
            })?;
            counters.read_successes.fetch_add(1, Ordering::SeqCst);
            Ok(json!({ "text": text }))
        }
    };
    FunctionTool::new("read_file", "读取练习目录的 README.md。", handler)
        .with_effect(ToolEffect::ReadOnly)
}
// endregion tool

// region contract
/// 宿主给委派定的契约：任务说明非空且不超过上限，回传结果不超过上限。
/// 包在 AgentTool 外面，其余行为（名字、参数、委派标记）原样转给它。
struct Delegate {
    inner: AgentTool,
}

fn contract_error(code: &'static str, message: &str) -> AdkError {
    AdkError::new(
        ErrorComponent::Tool,
        ErrorCategory::InvalidInput,
        code,
        message.to_owned(),
    )
}

#[async_trait]
impl Tool for Delegate {
    fn name(&self) -> &str {
        self.inner.name()
    }
    fn description(&self) -> &str {
        self.inner.description()
    }
    fn parameters_schema(&self) -> Option<Value> {
        self.inner.parameters_schema()
    }
    fn is_agent_delegation(&self) -> bool {
        self.inner.is_agent_delegation()
    }
    fn egress(&self, args: &Value) -> adk_core::egress::ToolEgress {
        self.inner.egress(args)
    }
    fn timeout_override(&self) -> Option<Option<std::time::Duration>> {
        self.inner.timeout_override()
    }
    fn response_schema(&self) -> Option<Value> {
        self.inner.response_schema()
    }

    async fn execute(&self, ctx: Arc<dyn ToolContext>, args: Value) -> adk_core::Result<Value> {
        let task = args["request"].as_str().unwrap_or_default();
        if task.trim().is_empty() || task.len() > MAX_TASK_BYTES {
            return Err(contract_error(
                "delegate.invalid_task",
                "子任务说明必须非空且不超过 256 字节",
            ));
        }
        let result = self.inner.execute(ctx, args).await?;
        if result["response"]
            .as_str()
            .is_some_and(|report| report.len() > MAX_REPORT_BYTES)
        {
            return Err(contract_error(
                "delegate.output_limit",
                "子 Agent 的回传超过 160 字节，未交给父 Agent",
            ));
        }
        Ok(result)
    }
}
// endregion contract

// region wiring
struct Lab {
    runner: Runner,
    parent: Arc<RuleLlm>,
    child: Arc<RuleLlm>,
    counters: Arc<Counters>,
}

fn model(role: &'static str, scenario: &str, cancel: Option<CancellationToken>) -> Arc<RuleLlm> {
    Arc::new(RuleLlm {
        role,
        scenario: scenario.into(),
        requests: Mutex::new(Vec::new()),
        cancel_on_read: cancel,
    })
}

async fn lab(scenario: &str, root: Arc<PathBuf>) -> Result<Lab> {
    let counters = Arc::new(Counters::default());
    let token = CancellationToken::new();
    let cancel_on_read = (scenario == "cancel").then(|| token.clone());
    if scenario == "cancel-before-start" {
        token.cancel();
    }
    let parent_model = model("parent", scenario, None);
    let child_model = model("child", scenario, cancel_on_read);

    let mut reader = LlmAgentBuilder::new("reader")
        .description("读取 README 并只返回启动命令")
        .instruction("你是 reader。用 read_file 读取 README.md，只返回启动命令。")
        .model(child_model.clone())
        .tool(Arc::new(read_file(root, counters.clone())));
    if scenario == "child-loop-limit" {
        // 子 Agent 自己的循环上限：只允许请求一次模型
        reader = reader.max_iterations(1);
    }
    let reader: Arc<dyn Agent> = Arc::new(reader.build()?);

    let mut coordinator = LlmAgentBuilder::new("coordinator")
        .instruction("你是 coordinator。把读文件的工作交给 reader。")
        .model(parent_model.clone());
    coordinator = if scenario == "transfer" {
        // 交接控制权：reader 成为子 Agent，父模型多了一个 transfer_to_agent 工具
        coordinator.sub_agent(reader)
    } else {
        // 当工具调用：reader 在新的空会话里运行（默认的 Isolated），只把最终回答交回来；
        // forward_events 让子事件出现在轨迹里供宿主诊断，父模型的历史不包含它们
        let tool = AgentTool::new(reader)
            .session_snapshot(AgentToolSessionSnapshot::Isolated)
            .forward_events(true);
        coordinator.tool(Arc::new(Delegate { inner: tool }))
    };

    let budget = match scenario {
        "global-model-budget" => Some(RunBudget::new().max_model_calls(2)),
        "global-tool-budget" => Some(RunBudget::new().max_tool_calls(1)),
        "parent-answer-budget" => Some(RunBudget::new().max_model_calls(3)),
        _ => None,
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r06".into(),
            user_id: "user".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    // 策略对父子都生效：子 Agent 的工具调用同样经过它
    let policy = DeclarativePolicy::builder()
        .allow("reader")
        .allow("read_file")
        .build();
    let mut runner = Runner::builder()
        .app_name("r06")
        .agent(Arc::new(coordinator.build()?))
        .session_service(sessions)
        .tool_policy(Arc::new(policy))
        .cancellation_token(token)
        .without_intra_compaction();
    if let Some(budget) = budget {
        runner = runner.budget(budget);
    }
    Ok(Lab {
        runner: runner.build()?,
        parent: parent_model,
        child: child_model,
        counters,
    })
}
// endregion wiring

// region run
/// 一个场景的可核对结果。
struct Outcome {
    lines: Vec<String>,
    summary: String,
}

fn mentions(requests: &[LlmRequest], mark: &str) -> bool {
    requests
        .iter()
        .any(|request| serde_json::to_string(&request.contents).is_ok_and(|s| s.contains(mark)))
}

async fn run(scenario: &str) -> Result<Outcome> {
    let workspace = tempfile::tempdir()?;
    if let Some(text) = readme(scenario) {
        fs::write(workspace.path().join("README.md"), text)?;
    }
    fs::write(workspace.path().join("private.txt"), "不允许子任务读取\n")?;
    let root = Arc::new(workspace.path().canonicalize()?);
    let lab = lab(scenario, root).await?;

    let mut lines = Vec::new();
    let (mut stop, mut answer, mut answered_by) = ("ended".to_string(), None, "-".to_string());
    let question = Content::new("user").with_text(format!("项目怎么启动？（{PARENT_MARK}）"));
    let mut stream = lab.runner.run_str("user", "s1", question).await?;
    while let Some(event) = stream.next().await {
        match event {
            Ok(event) => {
                lines.extend(trace::event_lines(&event));
                // 只有发给用户的最终回答才算；转发来的子事件带着自己的分支
                if event.is_final_response()
                    && event.branch.is_empty()
                    && event.author != "user"
                    && let Some(text) = event
                        .content()
                        .map(|c| c.parts.iter().filter_map(Part::text).collect::<String>())
                        .filter(|t| !t.is_empty())
                {
                    answer = Some(text);
                    answered_by = event.author.clone();
                    stop = "final_answer".into();
                }
            }
            Err(error) => {
                lines.push(format!("[run] error   {}", error.code));
                stop = error.code.to_string();
                break;
            }
        }
    }
    let parent = lab.parent.requests.lock().unwrap().clone();
    let child = lab.child.requests.lock().unwrap().clone();
    for (who, requests) in [("parent", &parent), ("child", &child)] {
        for line in trace::request_lines(requests) {
            lines.push(format!("{who} {line}"));
        }
        // 第一次请求里的用户消息：它是从哪里来的，一眼可见
        if let Some(user) = requests.first().and_then(|r| {
            r.contents
                .iter()
                .rfind(|c| c.role == "user")
                .map(|c| c.parts.iter().filter_map(Part::text).collect::<String>())
        }) {
            lines.push(format!("{who} request 0 user text: {user:?}"));
        }
    }
    let reads = lab.counters.read_attempts.load(Ordering::SeqCst);
    let successes = lab.counters.read_successes.load(Ordering::SeqCst);
    // 练习目标：真的读到了 README，并且最终回答里有 README 里写的那条命令
    let expected = readme(scenario).and_then(|text| {
        text.lines()
            .find_map(|l| l.strip_prefix("启动命令："))
            .map(str::to_owned)
    });
    let goal_met = successes == 1
        && answer
            .as_deref()
            .and_then(|a| a.split_once("启动命令："))
            .map(|(_, rest)| rest.split('（').next().unwrap_or_default().trim())
            .zip(expected.as_deref())
            .is_some_and(|(said, cmd)| said == cmd);
    let summary = format!(
        "{scenario}: stop={stop} answered_by={answered_by} parent_model_calls={} child_model_calls={} reads={reads}/{successes} parent_saw_child_raw={} child_saw_parent_note={} goal_met={goal_met}",
        parent.len(),
        child.len(),
        mentions(&parent, CHILD_MARK),
        mentions(&child, PARENT_MARK),
    );
    if let Some(answer) = answer {
        lines.push(format!("answer: {answer}"));
    }
    lines.push(summary.clone());
    Ok(Outcome { lines, summary })
}
// endregion run

async fn cli(args: &[String]) -> Result<()> {
    match args {
        [] => {
            for name in CASES {
                println!("{}", run(name).await?.summary);
            }
            Ok(())
        }
        [name] if CASES.contains(&name.as_str()) => {
            for line in run(name).await?.lines {
                println!("{line}");
            }
            Ok(())
        }
        _ => Err(format!("usage: learn-agent-r06 [{}]", CASES.join("|")).into()),
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
        run(name).await.unwrap().summary
    }

    #[tokio::test]
    async fn the_parent_sees_only_the_report_and_the_child_starts_fresh() {
        let line = summary("normal").await;
        assert!(line.contains("parent_saw_child_raw=false"), "{line}");
        assert!(line.contains("child_saw_parent_note=false"), "{line}");
        assert!(line.contains("goal_met=true"), "{line}");
    }

    #[tokio::test]
    async fn the_answer_follows_the_file() {
        let outcome = run("changed-readme").await.unwrap();
        assert!(outcome.summary.contains("goal_met=true"));
        assert!(
            outcome
                .lines
                .iter()
                .any(|l| l.contains("cargo run --release"))
        );
    }

    #[tokio::test]
    async fn parent_and_child_share_one_run_budget() {
        // 父 1 次 + 子 1 次就用完了 2 次额度：子 Agent 没有自己的一份新额度
        let line = summary("global-model-budget").await;
        assert!(line.contains("stop=budget.model_calls"), "{line}");
        assert!(
            line.contains("parent_model_calls=1 child_model_calls=1"),
            "{line}"
        );
        let line = summary("parent-answer-budget").await;
        assert!(line.contains("stop=budget.model_calls"), "{line}");
        assert!(
            line.contains("parent_model_calls=1 child_model_calls=2"),
            "{line}"
        );
        assert!(
            line.contains("reads=1/1") && line.contains("goal_met=false"),
            "{line}"
        );
    }

    #[tokio::test]
    async fn cancellation_stops_before_the_read() {
        let outcome = run("cancel").await.unwrap();
        assert!(outcome.summary.contains("reads=0/0"), "{}", outcome.summary);
        assert!(
            outcome
                .lines
                .iter()
                .any(|l| l.contains("reader status=outcome_unknown"))
        );
        let line = summary("cancel-before-start").await;
        assert!(
            line.contains("parent_model_calls=0") && line.contains("reads=0/0"),
            "{line}"
        );
    }

    #[tokio::test]
    async fn the_child_cannot_read_elsewhere_or_delegate_again() {
        let outcome = run("forbidden-path").await.unwrap();
        assert!(outcome.summary.contains("reads=1/0"), "{}", outcome.summary);
        assert!(
            outcome
                .lines
                .iter()
                .any(|l| l.contains("code=path.not_allowed"))
        );
        let outcome = run("recursive").await.unwrap();
        assert!(
            outcome
                .lines
                .iter()
                .any(|l| l.contains("[reader] result") && l.contains("status=not_run"))
        );
    }

    #[tokio::test]
    async fn the_host_contract_rejects_bad_tasks_and_oversized_reports() {
        let line = summary("invalid-task").await;
        assert!(line.contains("child_model_calls=0"), "{line}");
        let outcome = run("oversized-result").await.unwrap();
        assert!(
            outcome
                .lines
                .iter()
                .any(|l| l.contains("code=delegate.output_limit")),
            "oversized report must not reach the parent"
        );
    }

    #[tokio::test]
    async fn transfer_hands_over_the_conversation_to_the_child() {
        // 交接之后，子 Agent 看到的是用户原话（带着父会话里的标记），并直接回答用户
        let line = summary("transfer").await;
        assert!(line.contains("answered_by=reader"), "{line}");
        assert!(line.contains("child_saw_parent_note=true"), "{line}");
    }
}
