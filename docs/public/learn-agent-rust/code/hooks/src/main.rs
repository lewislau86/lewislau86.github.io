//! R04（ADK-Rust 3.0）：生命周期与回调。把检查、记录与收尾挂在框架的四个位置上，看清它们的顺序和失败后果。
//!
//! cargo run --locked -- normal          # 默认
//! 场景见 SCENARIOS；每个场景改变一个回调的行为（拦下、出错、panic、超时、改写）或制造一次工具失败。
//!
//! 模型是 ScriptedLlm；策略是本文件里的 WritePolicy；文件工具写程序自建的临时目录。
mod trace;

use std::{
    fs,
    path::PathBuf,
    pin::Pin,
    sync::{
        Arc, Mutex,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};

use adk_agent::LlmAgentBuilder;
use adk_core::{
    AdkError, CallbackContext, Content, ErrorCategory, ErrorComponent, Part, PolicyDecision,
    ToolContext, ToolPolicy, ToolPolicyRequest,
};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::{Future, StreamExt};
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const SUMMARY_PATH: &str = "notes/summary.txt";
const SUMMARY: &str = "README 摘要：启动命令是 cargo run";
const SCENARIOS: [&str; 15] = [
    "normal",
    "prompt-block",
    "prompt-error",
    "permission-deny",
    "pre-block",
    "pre-error",
    "pre-panic",
    "pre-timeout",
    "post-error",
    "post-timeout",
    "post-rewrite",
    "tool-error",
    "stop-error",
    "stop-timeout",
    "stop-rewrite",
];

// region contracts
/// 一个回调这次怎么表现。框架只看它的返回值：继续、给出内容、或者出错。
#[derive(Clone, Copy)]
enum Behavior {
    /// 返回 Ok(None)：继续
    Continue,
    /// 返回 Ok(Some(内容))：在 before 位置表示“拦下，用这段内容代替”，在 after 位置表示“改写结果”
    Respond(&'static str),
    /// 返回 Err：回调自己出了问题
    Fail,
    /// 回调里 panic
    Panic,
    /// 回调卡住；框架不给回调限时，所以回调自己用 tokio::time::timeout 设上限，超时按出错处理
    Hang,
}

type Callback = Box<
    dyn Fn(
            Arc<dyn CallbackContext>,
        ) -> Pin<Box<dyn Future<Output = adk_core::Result<Option<Content>>> + Send>>
        + Send
        + Sync,
>;

type HookLog = Arc<Mutex<Vec<String>>>;

/// 生成一个回调：先在日志里记一行（位置、名字、工具、行为），再按 behavior 返回。
fn hook(log: HookLog, point: &'static str, name: &'static str, behavior: Behavior) -> Callback {
    Box::new(move |ctx: Arc<dyn CallbackContext>| {
        let log = log.clone();
        let tool = ctx.tool_name().map(str::to_owned);
        Box::pin(async move {
            let outcome = match behavior {
                Behavior::Continue => "continue",
                Behavior::Respond(_) => "respond",
                Behavior::Fail => "error",
                Behavior::Panic => "panic",
                Behavior::Hang => "timeout",
            };
            let on = tool.map(|t| format!(" tool={t}")).unwrap_or_default();
            log.lock()
                .unwrap()
                .push(format!("hook {point}/{name}{on} -> {outcome}"));
            let fail = |category, code, message: &str| {
                Err(AdkError::new(
                    ErrorComponent::Agent,
                    category,
                    code,
                    message,
                ))
            };
            match behavior {
                Behavior::Continue => Ok(None),
                Behavior::Respond(text) => Ok(Some(Content::new("model").with_text(text))),
                Behavior::Fail => fail(ErrorCategory::Internal, "hook.failed", "回调内部错误"),
                Behavior::Panic => panic!("hook {name} panicked"),
                Behavior::Hang => {
                    let stuck = std::future::pending::<()>();
                    match tokio::time::timeout(Duration::from_millis(40), stuck).await {
                        Ok(()) => Ok(None),
                        Err(_) => {
                            fail(ErrorCategory::Timeout, "hook.timeout", "回调超过 40ms 上限")
                        }
                    }
                }
            }
        })
    })
}
// endregion contracts

// region policy
/// 权限来自策略，不来自回调：只允许把摘要写到 notes/summary.txt。
#[derive(Debug)]
struct WritePolicy;

#[async_trait]
impl ToolPolicy for WritePolicy {
    async fn evaluate(&self, request: &ToolPolicyRequest) -> PolicyDecision {
        match (request.tool_name.as_str(), request.args["path"].as_str()) {
            ("write_summary", Some(SUMMARY_PATH)) => PolicyDecision::Allow,
            _ => PolicyDecision::deny("action_outside_policy"),
        }
    }
}
// endregion policy

#[derive(Default)]
struct Counters {
    write_attempts: AtomicUsize,
    write_successes: AtomicUsize,
}

fn write_summary_tool(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            counters.write_attempts.fetch_add(1, Ordering::SeqCst);
            let target = root.join(args["path"].as_str().unwrap_or_default());
            let written = target
                .parent()
                .map_or(Ok(()), fs::create_dir_all)
                .and_then(|()| fs::write(&target, SUMMARY));
            written.map_err(|e| {
                AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Unavailable,
                    "file.write_failed",
                    e.to_string(),
                )
            })?;
            counters.write_successes.fetch_add(1, Ordering::SeqCst);
            Ok(json!({ "written": args["path"] }))
        }
    };
    FunctionTool::new("write_summary", "把摘要写进练习目录。", handler)
}

// region registration
/// 每个场景只改变一个回调的行为。注册顺序就是执行顺序。
fn behaviors(name: &str) -> (Behavior, Behavior, Behavior, Behavior) {
    use Behavior::*;
    // (input-check, before-check, after-check, stop-log)
    match name {
        "prompt-block" => (Respond("这条请求不处理。"), Continue, Continue, Continue),
        "prompt-error" => (Fail, Continue, Continue, Continue),
        "pre-block" => (
            Continue,
            Respond("before-check 拦下了这次写入"),
            Continue,
            Continue,
        ),
        "pre-error" => (Continue, Fail, Continue, Continue),
        "pre-panic" => (Continue, Panic, Continue, Continue),
        "pre-timeout" => (Continue, Hang, Continue, Continue),
        "post-error" => (Continue, Continue, Fail, Continue),
        "post-timeout" => (Continue, Continue, Hang, Continue),
        "post-rewrite" => (
            Continue,
            Continue,
            Respond("（结果已被 after-check 改写）"),
            Continue,
        ),
        "stop-error" => (Continue, Continue, Continue, Fail),
        "stop-timeout" => (Continue, Continue, Continue, Hang),
        "stop-rewrite" => (
            Continue,
            Continue,
            Continue,
            Respond("（回答已被 stop-log 改写）"),
        ),
        _ => (Continue, Continue, Continue, Continue),
    }
}

fn build_agent(
    name: &str,
    log: HookLog,
    root: Arc<PathBuf>,
    counters: Arc<Counters>,
) -> adk_core::Result<adk_agent::LlmAgent> {
    let (input_check, before_check, after_check, stop) = behaviors(name);
    let path = if name == "permission-deny" {
        "README.md"
    } else {
        SUMMARY_PATH
    };
    let script = [
        ScriptedResponse::function_call("write_summary", json!({ "path": path })),
        ScriptedResponse::text("摘要已写入。"),
    ];
    let l = || log.clone();
    LlmAgentBuilder::new("assistant")
        .model(Arc::new(ScriptedLlm::new("scripted", script)))
        .tool(Arc::new(write_summary_tool(root, counters)))
        // 输入：Agent 开始之前
        .before_callback(hook(l(), "before_agent", "input-log", Behavior::Continue))
        .before_callback(hook(l(), "before_agent", "input-check", input_check))
        // 工具执行之前（在策略检查之前运行）
        .before_tool_callback(hook(l(), "before_tool", "before-check", before_check))
        .before_tool_callback(hook(l(), "before_tool", "before-log", Behavior::Continue))
        // 工具执行之后
        .after_tool_callback(hook(l(), "after_tool", "after-check", after_check))
        .after_tool_callback(hook(l(), "after_tool", "after-log", Behavior::Continue))
        // Agent 结束时
        .after_callback(hook(l(), "after_agent", "stop-log", stop))
        .build()
}
// endregion registration

async fn scenario(name: &str) -> Result<Vec<String>> {
    let workspace = tempfile::tempdir()?;
    if name == "tool-error" {
        fs::create_dir_all(workspace.path().join(SUMMARY_PATH))?;
    }
    let root = Arc::new(workspace.path().canonicalize()?);
    let counters = Arc::new(Counters::default());
    let log: HookLog = Arc::default();
    let agent = build_agent(name, log.clone(), root.clone(), counters.clone())?;
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r04".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("r04")
        .agent(Arc::new(agent))
        .session_service(sessions)
        .tool_policy(Arc::new(WritePolicy))
        .without_intra_compaction()
        .build()?;

    let mut lines = Vec::new();
    let (mut result_status, mut stop, mut answer) =
        ("none".to_string(), "ended_without_answer".to_string(), None);
    let input = Content::new("user").with_text("把摘要写进 notes/summary.txt。");
    let mut stream = runner.run_str("reader", "s1", input).await?;
    while let Some(item) = stream.next().await {
        match item {
            Ok(event) => {
                for part in event
                    .content()
                    .map(|c| c.parts.as_slice())
                    .unwrap_or_default()
                {
                    if let Part::FunctionResponse { .. } = part {
                        let status = part
                            .tool_result_status()
                            .and_then(|s| serde_json::to_value(s).ok());
                        result_status = status
                            .and_then(|v| v.as_str().map(str::to_owned))
                            .unwrap_or_else(|| "ok".into());
                    }
                }
                let text = event
                    .content()
                    .and_then(|c| c.parts.iter().find_map(Part::text));
                if let (true, Some(text)) = (
                    event.is_final_response() && event.author == "assistant",
                    text,
                ) {
                    answer = Some(text.to_owned());
                    stop = "final_answer".into();
                }
                lines.extend(trace::event_lines(&event));
            }
            Err(error) => {
                stop = error.code.to_string();
                break;
            }
        }
    }
    runner.close().await;
    let hooks = log.lock().unwrap().clone();
    let failures = hooks
        .iter()
        .filter(|h| h.ends_with("error") || h.ends_with("panic") || h.ends_with("timeout"))
        .count();
    let written = fs::read_to_string(root.join(SUMMARY_PATH)).ok();
    let mut out = hooks;
    out.extend(lines);
    // 任务完成：摘要真的写进去了、得到了最终回答、而且没有回调失败
    let task_ok = written.as_deref() == Some(SUMMARY) && answer.is_some() && failures == 0;
    out.push(format!(
        "统计：write_attempts={} write_successes={} hook_failures={failures} result_status={result_status} stop={stop} summary_written={} task_ok={task_ok}",
        counters.write_attempts.load(Ordering::SeqCst),
        counters.write_successes.load(Ordering::SeqCst),
        written.as_deref() == Some(SUMMARY),
    ));
    Ok(out)
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let name = match args.as_slice() {
        [] => "normal".to_string(),
        [one] if SCENARIOS.contains(&one.as_str()) => one.clone(),
        _ => {
            eprintln!("usage: hooks [{}]", SCENARIOS.join("|"));
            std::process::exit(2);
        }
    };
    println!("场景：{name}；模型：ScriptedLlm；策略：WritePolicy");
    for line in scenario(&name).await? {
        println!("{line}");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn stat(lines: &[String], key: &str) -> String {
        let stats = lines.last().unwrap();
        let start = stats.find(&format!("{key}=")).unwrap() + key.len() + 1;
        stats[start..].split_whitespace().next().unwrap().to_owned()
    }

    fn hooks(lines: &[String]) -> Vec<&str> {
        lines
            .iter()
            .filter_map(|l| l.strip_prefix("hook "))
            .collect()
    }

    #[tokio::test]
    async fn normal_runs_every_hook_once_in_registration_order() {
        let lines = scenario("normal").await.unwrap();
        let order: Vec<&str> = hooks(&lines)
            .iter()
            .map(|h| h.split(' ').next().unwrap())
            .collect();
        assert_eq!(
            order,
            [
                "before_agent/input-log",
                "before_agent/input-check",
                "before_tool/before-check",
                "before_tool/before-log",
                "after_tool/after-check",
                "after_tool/after-log",
                "after_agent/stop-log"
            ]
        );
    }

    #[tokio::test]
    async fn hooks_that_continue_cannot_grant_permission() {
        // 回调都放行，策略照样拒绝；被策略拒绝的调用不触发 after_tool
        let lines = scenario("permission-deny").await.unwrap();
        assert_eq!(
            (
                stat(&lines, "write_attempts"),
                stat(&lines, "result_status")
            ),
            ("0".into(), "refused".into())
        );
        assert!(!hooks(&lines).iter().any(|h| h.starts_with("after_tool")));
    }

    #[tokio::test]
    async fn a_broken_before_tool_hook_fails_closed() {
        for name in ["pre-error", "pre-panic", "pre-timeout"] {
            let lines = scenario(name).await.unwrap();
            assert_eq!(
                (
                    stat(&lines, "write_attempts"),
                    stat(&lines, "result_status")
                ),
                ("0".into(), "not_run".into()),
                "{name}"
            );
        }
    }

    #[tokio::test]
    async fn a_broken_after_tool_hook_withholds_the_result_but_not_the_file() {
        let lines = scenario("post-error").await.unwrap();
        assert_eq!(
            (
                stat(&lines, "result_status"),
                stat(&lines, "summary_written")
            ),
            ("withheld".into(), "true".into())
        );
        assert!(
            !hooks(&lines)
                .iter()
                .any(|h| h.starts_with("after_tool/after-log"))
        );
    }

    #[tokio::test]
    async fn a_tool_failure_still_runs_after_hooks() {
        let lines = scenario("tool-error").await.unwrap();
        assert_eq!(stat(&lines, "result_status"), "failed");
        assert!(
            hooks(&lines)
                .iter()
                .any(|h| h.starts_with("after_tool/after-log"))
        );
    }

    #[tokio::test]
    async fn the_stop_hook_does_not_run_when_the_agent_fails() {
        let lines = scenario("prompt-error").await.unwrap();
        assert!(!hooks(&lines).iter().any(|h| h.starts_with("after_agent")));
        assert_eq!(stat(&lines, "stop"), "hook.failed");
    }

    #[tokio::test]
    async fn a_failing_stop_hook_ends_the_run_after_the_answer() {
        let lines = scenario("stop-error").await.unwrap();
        assert!(lines.iter().any(|l| l.contains("] text ")));
        assert_eq!(
            (stat(&lines, "stop"), stat(&lines, "task_ok")),
            ("hook.failed".into(), "false".into())
        );
    }
}
