//! R03（ADK-Rust 3.0）：工具权限与审批。同一份请求先过应用策略：允许、拒绝，或等待人批准。
//!
//! cargo run --locked -- approve        # 默认
//! 场景：read deny invalid-path unknown wait approve decline tamper replay write-error
//!
//! 模型是 ScriptedLlm（固定脚本）；策略是本文件里的 SummaryPolicy（实现 ToolPolicy）；
//! 审批记录放在 InMemoryApprovalStore；文件工具读写程序自建的临时目录。
mod trace;

use std::{
    fs,
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, ApprovalScope, ApprovalStore, Content, ErrorCategory, ErrorComponent,
    InMemoryApprovalStore, PolicyDecision, ToolApproval, ToolContext, ToolEffect, ToolPolicy,
    ToolPolicyRequest,
};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_runner::Runner;
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const SUMMARY_PATH: &str = "notes/summary.txt";
const SUMMARY: &str = "README 摘要：启动命令是 cargo run";
const README: &str = "# 课程练习项目\n启动命令：cargo run\n";
const SCENARIOS: [&str; 10] = [
    "read",
    "deny",
    "invalid-path",
    "unknown",
    "wait",
    "approve",
    "decline",
    "tamper",
    "replay",
    "write-error",
];

// region policy
/// 应用自己的策略：只看请求（工具名、参数），不做任何 I/O。
/// 读 README 直接允许；写摘要要等人批准；其余一律拒绝。
#[derive(Debug)]
struct SummaryPolicy;

#[async_trait]
impl ToolPolicy for SummaryPolicy {
    async fn evaluate(&self, request: &ToolPolicyRequest) -> PolicyDecision {
        let path = request.args["path"].as_str().unwrap_or_default();
        match request.tool_name.as_str() {
            "read_file" if path == "README.md" => PolicyDecision::Allow,
            "write_summary"
                if path == SUMMARY_PATH
                    && request.args["content"]
                        .as_str()
                        .is_some_and(|c| c.len() <= 1024) =>
            {
                PolicyDecision::require_approval("写入摘要需要人工批准")
            }
            _ => PolicyDecision::deny("action_outside_policy"),
        }
    }
}
// endregion policy

// region tools
#[derive(Default)]
struct Counters {
    read_attempts: AtomicUsize,
    write_attempts: AtomicUsize,
    write_successes: AtomicUsize,
}

fn tool_error(category: ErrorCategory, code: &'static str, message: String) -> AdkError {
    AdkError::new(ErrorComponent::Tool, category, code, message)
}

fn read_file_tool(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, _args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            counters.read_attempts.fetch_add(1, Ordering::SeqCst);
            let text = fs::read_to_string(root.join("README.md"))
                .map_err(|e| tool_error(ErrorCategory::NotFound, "file.missing", e.to_string()))?;
            Ok(json!({ "text": text }))
        }
    };
    FunctionTool::new("read_file", "读取练习目录的 README.md。", handler)
        .with_effect(ToolEffect::ReadOnly)
}

/// 写摘要：有副作用，没有声明 ToolEffect，框架按非幂等对待。
/// 处理函数只管写；能不能写由策略和审批决定，它被调用时已经通过了这两关。
fn write_summary_tool(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            counters.write_attempts.fetch_add(1, Ordering::SeqCst);
            let target = root.join(args["path"].as_str().unwrap_or_default());
            let content = args["content"].as_str().unwrap_or_default();
            let written = target
                .parent()
                .map_or(Ok(()), fs::create_dir_all)
                .and_then(|()| fs::write(&target, content));
            written.map_err(|e| {
                tool_error(
                    ErrorCategory::Unavailable,
                    "file.write_failed",
                    e.to_string(),
                )
            })?;
            counters.write_successes.fetch_add(1, Ordering::SeqCst);
            Ok(json!({ "written": args["path"] }))
        }
    };
    FunctionTool::new(
        "write_summary",
        "把摘要写进练习目录的 notes/summary.txt。",
        handler,
    )
}
// endregion tools

fn write(path: &str) -> ScriptedResponse {
    ScriptedResponse::function_call("write_summary", json!({ "path": path, "content": SUMMARY }))
}

/// 每个场景的模型脚本：一条回复对应一次模型调用，跨越本场景的全部运行。
fn script(name: &str) -> Vec<ScriptedResponse> {
    let read = || ScriptedResponse::function_call("read_file", json!({ "path": "README.md" }));
    let text = ScriptedResponse::text;
    match name {
        "read" => vec![read(), text("启动命令是 cargo run。")],
        "deny" => vec![read(), write("README.md"), text("没有写入：策略拒绝。")],
        "invalid-path" => vec![
            read(),
            write("../outside.txt"),
            text("没有写入：策略拒绝。"),
        ],
        "unknown" => vec![
            read(),
            ScriptedResponse::function_call("bash", json!({ "path": "README.md" })),
            text("没有可用的 bash 工具。"),
        ],
        "wait" => vec![read(), write(SUMMARY_PATH)],
        "approve" | "decline" | "tamper" => vec![read(), write(SUMMARY_PATH), text("处理完毕。")],
        // 第三次运行里，模型又提出同一个写入
        "replay" | "write-error" => {
            vec![
                read(),
                write(SUMMARY_PATH),
                text("处理完毕。"),
                write(SUMMARY_PATH),
            ]
        }
        other => panic!("unknown scenario {other}"),
    }
}

struct Lab {
    runner: Runner,
    store: Arc<InMemoryApprovalStore>,
    scope: ApprovalScope,
    lines: Vec<String>,
    tool_results: usize,
}

impl Lab {
    async fn new(name: &str, root: Arc<PathBuf>, counters: Arc<Counters>) -> Result<Self> {
        // region wiring
        let agent = LlmAgentBuilder::new("assistant")
            .instruction("先读 README，再把一句话摘要写进 notes/summary.txt。")
            .model(Arc::new(ScriptedLlm::new("scripted", script(name))))
            .tool(Arc::new(read_file_tool(root.clone(), counters.clone())))
            .tool(Arc::new(write_summary_tool(root, counters)))
            .build()?;
        let sessions = Arc::new(adk_session::InMemorySessionService::new());
        adk_session::SessionService::create(
            sessions.as_ref(),
            adk_session::CreateRequest {
                app_name: "r03".into(),
                user_id: "reader".into(),
                session_id: Some("s1".into()),
                state: Default::default(),
            },
        )
        .await?;
        let store = Arc::new(InMemoryApprovalStore::new());
        let runner = Runner::builder()
            .app_name("r03")
            .agent(Arc::new(agent))
            .session_service(sessions)
            .tool_policy(Arc::new(SummaryPolicy))
            .approval_store(store.clone())
            .without_intra_compaction()
            .build()?;
        // endregion wiring
        let scope = ApprovalScope::new("r03", "reader", "s1");
        Ok(Self {
            runner,
            store,
            scope,
            lines: vec![],
            tool_results: 0,
        })
    }

    /// 一次运行：空文本表示“只为恢复等待中的调用而运行”，不加新的用户消息。
    async fn run(&mut self, label: &str, text: &str) -> Result<()> {
        self.lines.push(format!("-- run {label}"));
        let input = Content::new("user").with_text(text);
        let mut stream = self.runner.run_str("reader", "s1", input).await?;
        while let Some(item) = stream.next().await {
            let event = item?;
            self.tool_results += event.tool_results().len();
            self.lines.extend(
                trace::event_lines(&event)
                    .into_iter()
                    .filter(|l| !l.contains("] held ")),
            );
        }
        for pending in self.store.pending(&self.scope).await? {
            let r = &pending.request;
            self.lines.push(format!(
                "pending call_id={} tool={} args={}",
                r.function_call_id.as_deref().unwrap_or("-"),
                r.tool_name,
                r.args
            ));
        }
        Ok(())
    }

    // region approve
    /// 审批人看到等待中的请求，按请求的指纹记下决定。指纹覆盖执行的 Agent、工具来源、工具名与参数。
    async fn decide(&mut self, approval: ToolApproval, tamper: bool) -> Result<()> {
        let pending = self.store.pending(&self.scope).await?;
        let first = pending.first().ok_or("nothing is waiting for approval")?;
        let fingerprint = if tamper {
            // 审批人批准的是改过内容的请求：指纹不同，等待中的那次调用得不到决定
            let mut changed = first.request.clone();
            changed.args["content"] = json!("改过的摘要");
            changed.fingerprint()
        } else {
            first.fingerprint.clone()
        };
        self.lines
            .push(format!("decide {:?} tampered={tamper}", approval.decision));
        self.store
            .decide(&self.scope, &fingerprint, approval)
            .await?;
        Ok(())
    }
    // endregion approve
}

async fn scenario(name: &str) -> Result<Vec<String>> {
    let workspace = tempfile::tempdir()?;
    fs::write(workspace.path().join("README.md"), README)?;
    if name == "write-error" {
        // 目标位置是一个目录：批准之后，写入仍会失败
        fs::create_dir_all(workspace.path().join(SUMMARY_PATH))?;
    }
    let root = Arc::new(workspace.path().canonicalize()?);
    let counters = Arc::new(Counters::default());
    let mut lab = Lab::new(name, root.clone(), counters.clone()).await?;
    lab.run("1", "读一下 README，把摘要写进 notes/summary.txt。")
        .await?;
    match name {
        "approve" | "replay" | "write-error" => lab.decide(ToolApproval::approve(), false).await?,
        "decline" => lab.decide(ToolApproval::deny(), false).await?,
        "tamper" => lab.decide(ToolApproval::approve(), true).await?,
        _ => {}
    }
    if matches!(
        name,
        "approve" | "decline" | "tamper" | "replay" | "write-error"
    ) {
        lab.run("2 (resume)", "").await?;
    }
    if matches!(name, "replay" | "write-error") {
        lab.run("3", "再写一次摘要。").await?;
    }
    let summary = fs::read_to_string(root.join(SUMMARY_PATH)).ok();
    let mut lines = std::mem::take(&mut lab.lines);
    lines.push(format!(
        "统计：read_attempts={} write_attempts={} write_successes={} tool_results={} pending={} summary_matches={} readme_unchanged={}",
        counters.read_attempts.load(Ordering::SeqCst),
        counters.write_attempts.load(Ordering::SeqCst),
        counters.write_successes.load(Ordering::SeqCst),
        lab.tool_results,
        lab.store.pending(&lab.scope).await?.len(),
        summary.as_deref() == Some(SUMMARY),
        fs::read_to_string(root.join("README.md"))? == README,
    ));
    lab.runner.close().await;
    Ok(lines)
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let name = match args.as_slice() {
        [] => "approve".to_string(),
        [one] if SCENARIOS.contains(&one.as_str()) => one.clone(),
        _ => {
            eprintln!("usage: permissions [{}]", SCENARIOS.join("|"));
            std::process::exit(2);
        }
    };
    println!("场景：{name}；模型：ScriptedLlm；策略：SummaryPolicy；审批：InMemoryApprovalStore");
    for line in scenario(&name).await? {
        println!("{line}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stat(lines: &[String], key: &str) -> String {
        let last = lines.last().unwrap();
        last.split_whitespace()
            .find_map(|kv| kv.strip_prefix(&format!("{key}=")).map(str::to_owned))
            .or_else(|| {
                last.split('：')
                    .nth(1)?
                    .split_whitespace()
                    .find_map(|kv| kv.strip_prefix(&format!("{key}=")).map(str::to_owned))
            })
            .unwrap()
    }

    #[tokio::test]
    async fn denied_and_unknown_calls_never_reach_the_file() {
        for name in ["deny", "invalid-path", "unknown"] {
            let lines = scenario(name).await.unwrap();
            assert_eq!(stat(&lines, "write_attempts"), "0", "{name}");
            assert_eq!(stat(&lines, "readme_unchanged"), "true", "{name}");
        }
    }

    #[tokio::test]
    async fn waiting_writes_nothing_and_keeps_the_request() {
        let lines = scenario("wait").await.unwrap();
        assert_eq!(
            (stat(&lines, "write_attempts"), stat(&lines, "pending")),
            ("0".into(), "1".into())
        );
    }

    #[tokio::test]
    async fn an_approval_for_other_arguments_does_not_release_the_call() {
        let lines = scenario("tamper").await.unwrap();
        assert_eq!(
            (stat(&lines, "write_attempts"), stat(&lines, "pending")),
            ("0".into(), "1".into())
        );
    }

    #[tokio::test]
    async fn one_approval_authorizes_one_execution() {
        let lines = scenario("replay").await.unwrap();
        assert_eq!(
            (stat(&lines, "write_successes"), stat(&lines, "pending")),
            ("1".into(), "1".into())
        );
    }

    #[tokio::test]
    async fn a_failed_write_still_consumes_the_approval() {
        let lines = scenario("write-error").await.unwrap();
        assert_eq!(
            (
                stat(&lines, "write_attempts"),
                stat(&lines, "write_successes"),
                stat(&lines, "pending")
            ),
            ("1".into(), "0".into(), "1".into())
        );
    }

    #[tokio::test]
    async fn declining_returns_a_result_without_writing() {
        let lines = scenario("decline").await.unwrap();
        assert_eq!(
            (stat(&lines, "write_attempts"), stat(&lines, "pending")),
            ("0".into(), "0".into())
        );
    }
}
