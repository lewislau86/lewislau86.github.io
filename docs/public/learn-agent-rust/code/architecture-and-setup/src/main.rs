//! R00（ADK-Rust 3.0）：一次“读取 README，回答怎么启动”的完整往返，看清每一块放在哪里。
//!
//! cargo run --locked                      # normal：允许读取
//! cargo run --locked -- --deny            # 应用策略拒绝读取
//! cargo run --locked -- --missing-file    # 练习目录里没有 README
//!
//! 模型是 ScriptedLlm（固定脚本，不联网）；工具真实读取程序自建的临时目录；会话只在内存里。
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
    AdkError, Content, DeclarativePolicy, ErrorCategory, ErrorComponent, Part, ToolContext,
    ToolEffect, ToolResultStatus,
};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_runner::Runner;
use adk_session::{CreateRequest, GetRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const QUESTION: &str = "读取 README.md，告诉我如何启动项目。";
const README: &str = "# 课程练习项目\n启动命令：cargo run\n";

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Normal,
    Deny,
    MissingFile,
}

// region tool
/// 读取次数与成功次数由工具自己记录，和框架的事件分开核对。
#[derive(Default)]
struct Counters {
    read_attempts: AtomicUsize,
    read_successes: AtomicUsize,
}

fn read_file_tool(root: Arc<PathBuf>, counters: Arc<Counters>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let (root, counters) = (root.clone(), counters.clone());
        async move {
            if args["path"] != "README.md" {
                return Err(AdkError::new(
                    ErrorComponent::Tool,
                    ErrorCategory::Forbidden,
                    "path.not_allowed",
                    "只允许读取练习目录的 README.md",
                ));
            }
            counters.read_attempts.fetch_add(1, Ordering::SeqCst);
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

// region wiring
fn script(mode: Mode) -> Vec<ScriptedResponse> {
    let read = ScriptedResponse::function_call("read_file", json!({ "path": "README.md" }));
    let answer = match mode {
        Mode::Normal => "README 里的启动命令是：cargo run",
        Mode::Deny => "任务未完成：应用策略拒绝读取 README.md",
        Mode::MissingFile => "任务未完成：练习目录中不存在 README.md",
    };
    vec![read, ScriptedResponse::text(answer)]
}

/// 组装一次运行：模型（ScriptedLlm）、工具（FunctionTool）、Agent（LlmAgent）、
/// 应用策略（DeclarativePolicy）、会话（InMemorySessionService），交给 Runner。
async fn wire(mode: Mode, root: Arc<PathBuf>, counters: Arc<Counters>) -> Result<Wired> {
    let model = Arc::new(ScriptedLlm::new("scripted", script(mode)));
    let agent = LlmAgentBuilder::new("assistant")
        .instruction("回答前先用 read_file 读取 README.md，只根据读到的内容回答。")
        .model(model.clone())
        .tool(Arc::new(read_file_tool(root, counters)))
        .build()?;
    // 策略属于应用：允许还是拒绝 read_file，由这里决定，而不是由模型决定
    let policy = match mode {
        Mode::Deny => DeclarativePolicy::builder().deny("read_file", "应用策略拒绝读取 README.md"),
        _ => DeclarativePolicy::builder().allow("read_file"),
    };
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r00".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let runner = Runner::builder()
        .app_name("r00")
        .agent(Arc::new(agent))
        .session_service(sessions.clone())
        .tool_policy(Arc::new(policy.build()))
        .without_intra_compaction()
        .build()?;
    Ok(Wired {
        runner,
        model,
        sessions,
    })
}

struct Wired {
    runner: Runner,
    model: Arc<ScriptedLlm>,
    sessions: Arc<InMemorySessionService>,
}
// endregion wiring

fn parse() -> Result<Mode> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args
        .iter()
        .map(String::as_str)
        .collect::<Vec<_>>()
        .as_slice()
    {
        [] => Ok(Mode::Normal),
        ["--deny"] => Ok(Mode::Deny),
        ["--missing-file"] => Ok(Mode::MissingFile),
        _ => Err("usage: architecture-and-setup [--deny | --missing-file]".into()),
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let mode = match parse() {
        Ok(mode) => mode,
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(2);
        }
    };
    let workspace = tempfile::tempdir()?;
    if mode != Mode::MissingFile {
        fs::write(workspace.path().join("README.md"), README)?;
    }
    let root = Arc::new(workspace.path().canonicalize()?);
    let counters = Arc::new(Counters::default());
    let wired = wire(mode, root, counters.clone()).await?;

    let label = match mode {
        Mode::Normal => "normal",
        Mode::Deny => "deny",
        Mode::MissingFile => "missing-file",
    };
    println!("模式：{label}；模型：ScriptedLlm（固定脚本）");
    let mut answer = String::new();
    let mut statuses = Vec::new();
    let mut stream = wired
        .runner
        .run_str("reader", "s1", Content::new("user").with_text(QUESTION))
        .await?;
    while let Some(event) = stream.next().await {
        let event = event?;
        for line in trace::event_lines(&event) {
            println!("{line}");
        }
        for part in event
            .content()
            .map(|c| c.parts.as_slice())
            .unwrap_or_default()
        {
            if let Part::FunctionResponse { .. } = part {
                let code = part.tool_result_error_code().map(str::to_owned);
                statuses.push((part.tool_result_status(), code));
            }
        }
        if event.is_final_response() && event.author == "assistant" {
            let text: String = event
                .content()
                .map(|c| c.parts.iter().filter_map(Part::text).collect())
                .unwrap_or_default();
            answer = text;
        }
    }
    for line in trace::request_lines(&wired.model.requests()) {
        println!("{line}");
    }
    let session = wired
        .sessions
        .get(GetRequest {
            app_name: "r00".into(),
            user_id: "reader".into(),
            session_id: "s1".into(),
            num_recent_events: None,
            after: None,
        })
        .await?;
    let (attempts, successes) = (
        counters.read_attempts.load(Ordering::SeqCst),
        counters.read_successes.load(Ordering::SeqCst),
    );
    // 任务结果由应用根据观察判断：进程正常退出、模型给出回答，都不等于读到了并答对了
    let refused = statuses
        .iter()
        .any(|(status, _)| *status == Some(ToolResultStatus::Refused));
    let missing = statuses
        .iter()
        .any(|(_, code)| code.as_deref() == Some("file.missing"));
    let outcome = if successes == 1 && answer.ends_with("cargo run") {
        "completed"
    } else if refused {
        "denied"
    } else if missing {
        "missing_file"
    } else {
        "incomplete"
    };
    println!(
        "统计：model_calls={} tool_results={} read_attempts={attempts} read_successes={successes} session_events={} outcome={outcome}",
        wired.model.requests().len(),
        statuses.len(),
        session.events().len()
    );
    println!("状态：会话只保存在当前进程的 InMemorySessionService 里；进程退出后不保留。");
    wired.runner.close().await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn counts(mode: Mode) -> (usize, usize, usize) {
        let workspace = tempfile::tempdir().unwrap();
        if mode != Mode::MissingFile {
            fs::write(workspace.path().join("README.md"), README).unwrap();
        }
        let counters = Arc::new(Counters::default());
        let root = Arc::new(workspace.path().canonicalize().unwrap());
        let wired = wire(mode, root, counters.clone()).await.unwrap();
        let mut stream = wired
            .runner
            .run_str("reader", "s1", Content::new("user").with_text(QUESTION))
            .await
            .unwrap();
        while stream.next().await.is_some() {}
        (
            wired.model.requests().len(),
            counters.read_attempts.load(Ordering::SeqCst),
            counters.read_successes.load(Ordering::SeqCst),
        )
    }

    #[tokio::test]
    async fn a_denied_read_never_touches_the_file() {
        assert_eq!(counts(Mode::Deny).await, (2, 0, 0));
    }

    #[tokio::test]
    async fn a_missing_file_is_an_attempt_without_success() {
        assert_eq!(counts(Mode::MissingFile).await, (2, 1, 0));
    }

    #[tokio::test]
    async fn normal_reads_once_in_two_model_calls() {
        assert_eq!(counts(Mode::Normal).await, (2, 1, 1));
    }
}
