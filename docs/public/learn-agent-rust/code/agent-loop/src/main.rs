//! R01（ADK-Rust 3.0）：最小 Agent 循环。看清“请求 → 执行 → 结果回传 → 再请求”的每一步，以及循环怎样停下。
//!
//! cargo run --locked                                   # normal
//! cargo run --locked -- --scenario repeat --max-tool-calls 2
//! 场景：normal changed-readme missing-file repeat two-tools duplicate-id unknown-tool invalid-path
//! 预算：--max-model-calls N  --max-tool-calls N；循环上限：--max-iterations N
//!
//! 模型是本文件里的 RuleLlm：实现 adk_core::Llm，只根据收到的请求内容按固定规则回复，不联网。
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
    AdkError, Content, ErrorCategory, ErrorComponent, FinishReason, Llm, LlmRequest, LlmResponse,
    LlmResponseStream, Part, RunBudget, ToolContext, ToolEffect,
};
use adk_runner::Runner;
use adk_session::{CreateRequest, GetRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use async_trait::async_trait;
use futures::StreamExt;
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const QUESTION: &str = "读取 README.md，告诉我如何启动项目。";
const SCENARIOS: [&str; 9] = [
    "normal",
    "changed-readme",
    "missing-file",
    "repeat",
    "two-tools",
    "duplicate-id",
    "unknown-tool",
    "invalid-path",
    "model-error",
];

// region model
/// 一个按规则回复的模型。它和真实模型一样只能看到 LlmRequest：消息历史与工具声明。
struct RuleLlm {
    scenario: String,
    requests: Mutex<Vec<LlmRequest>>,
}

/// 请求里已经有的工具结果：（工具名，结果 JSON）。
fn tool_results(request: &LlmRequest) -> Vec<(String, Value)> {
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
        .collect()
}

fn reply(parts: Vec<Part>) -> LlmResponse {
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts,
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    response
}

fn call(name: &str, path: &str, id: &str) -> Part {
    Part::FunctionCall {
        name: name.into(),
        args: json!({ "path": path }),
        id: Some(id.into()),
        thought_signature: None,
    }
}

/// 从最后一条工具结果写回答：读到启动命令就照实回答，否则报告未完成。
fn answer(results: &[(String, Value)]) -> Part {
    let (_, last) = results.last().expect("answer needs a tool result");
    let text = match last["text"].as_str() {
        Some(readme) => match readme.lines().find_map(|l| l.strip_prefix("启动命令：")) {
            Some(command) => format!("README 里的启动命令是：{command}"),
            None => "任务未完成：README 里没有启动命令".to_string(),
        },
        None => format!(
            "任务未完成：{}",
            last["error"].as_str().unwrap_or("工具没有返回内容")
        ),
    };
    Part::Text { text }
}

#[async_trait]
impl Llm for RuleLlm {
    fn name(&self) -> &str {
        "rule-llm"
    }

    async fn generate_content(
        &self,
        request: LlmRequest,
        _stream: bool,
    ) -> adk_core::Result<LlmResponseStream> {
        let results = tool_results(&request);
        self.requests.lock().unwrap().push(request);
        let n = results.len();
        let parts = match (self.scenario.as_str(), n) {
            ("model-error", _) => {
                return Err(AdkError::new(
                    ErrorComponent::Model,
                    ErrorCategory::Unavailable,
                    "model.unavailable",
                    "rule-llm: simulated provider failure",
                ));
            }
            // 反复请求：不管看到什么，都再读一次
            ("repeat", _) => vec![call("read_file", "README.md", &format!("read-{}", n + 1))],
            ("two-tools", 0) => vec![
                call("read_file", "README.md", "read-1"),
                call("read_file", "README.md", "read-2"),
            ],
            // 第二轮沿用第一轮的调用 ID
            ("duplicate-id", 0 | 1) => vec![call("read_file", "README.md", "read-1")],
            ("unknown-tool", 0) => vec![call("shell", "README.md", "read-1")],
            ("invalid-path", 0) => vec![call("read_file", "../README.md", "read-1")],
            (_, 0) => vec![call("read_file", "README.md", "read-1")],
            _ => vec![answer(&results)],
        };
        Ok(Box::pin(futures::stream::iter([Ok(reply(parts))])))
    }
}
// endregion model

// region tool
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

// region limits
/// 预算装在 Runner 上，由 LlmAgent 在行动之前检查：模型调用在每次请求模型之前，工具调用按整批申请。
/// 循环上限是 LlmAgent 自己的设置（默认 100 轮，每轮调用一次模型）。
struct Limits {
    max_model_calls: Option<u64>,
    max_tool_calls: Option<u64>,
    max_iterations: Option<u32>,
}

fn budget(limits: &Limits) -> Option<RunBudget> {
    let mut budget = RunBudget::new();
    if let Some(max) = limits.max_model_calls {
        budget = budget.max_model_calls(max);
    }
    if let Some(max) = limits.max_tool_calls {
        budget = budget.max_tool_calls(max);
    }
    (limits.max_model_calls.is_some() || limits.max_tool_calls.is_some()).then_some(budget)
}
// endregion limits

/// 一次运行的可核对结果。
struct Outcome {
    lines: Vec<String>,
    model_calls: usize,
    tool_results: usize,
    read_attempts: usize,
    read_successes: usize,
    session_events: usize,
    stop: String,
    goal_met: bool,
}

fn readme_for(scenario: &str) -> Option<&'static str> {
    match scenario {
        "missing-file" => None,
        "changed-readme" => Some("# 课程练习项目\n启动命令：cargo run --release\n"),
        _ => Some("# 课程练习项目\n启动命令：cargo run\n"),
    }
}

async fn run(scenario: &str, limits: &Limits) -> Result<Outcome> {
    let workspace = tempfile::tempdir()?;
    let readme = readme_for(scenario);
    if let Some(text) = readme {
        fs::write(workspace.path().join("README.md"), text)?;
    }
    let root = Arc::new(workspace.path().canonicalize()?);
    let counters = Arc::new(Counters::default());
    let model = Arc::new(RuleLlm {
        scenario: scenario.into(),
        requests: Mutex::new(Vec::new()),
    });
    // region wiring
    let mut agent = LlmAgentBuilder::new("assistant")
        .instruction("回答前先用 read_file 读取 README.md，只根据读到的内容回答。")
        .model(model.clone())
        .tool(Arc::new(read_file_tool(root, counters.clone())));
    if let Some(max) = limits.max_iterations {
        agent = agent.max_iterations(max);
    }
    let agent = agent.build()?;
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r01".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let mut builder = Runner::builder()
        .app_name("r01")
        .agent(Arc::new(agent))
        .session_service(sessions.clone())
        .without_intra_compaction();
    if let Some(budget) = budget(limits) {
        builder = builder.budget(budget);
    }
    let runner = builder.build()?;
    // endregion wiring

    // region events
    let mut lines = Vec::new();
    // 只有真的看到 assistant 的最终文本才算 final_answer；没有错误也没有回答，记作 ended_without_answer
    let (mut tool_results, mut stop, mut last_answer) =
        (0, String::from("ended_without_answer"), None);
    let mut stream = runner
        .run_str("reader", "s1", Content::new("user").with_text(QUESTION))
        .await?;
    while let Some(item) = stream.next().await {
        match item {
            Ok(event) => {
                tool_results += event.tool_results().len();
                if event.is_final_response() && event.author == "assistant" {
                    let text = event
                        .content()
                        .and_then(|c| c.parts.iter().find_map(Part::text));
                    if let Some(text) = text {
                        last_answer = Some(text.to_owned());
                        stop = "final_answer".into();
                    }
                }
                lines.extend(trace::event_lines(&event));
            }
            // 预算用完、模型出错：运行以错误结束，错误码就是停止原因
            Err(error) => {
                stop = error.code.to_string();
                break;
            }
        }
    }
    // endregion events
    runner.close().await;
    lines.extend(trace::request_lines(&model.requests.lock().unwrap()));
    let session = sessions
        .get(GetRequest {
            app_name: "r01".into(),
            user_id: "reader".into(),
            session_id: "s1".into(),
            num_recent_events: None,
            after: None,
        })
        .await?;
    let read_successes = counters.read_successes.load(Ordering::SeqCst);
    // 练习目标：真的读到了文件，并且回答和读到的启动命令一致
    let expected = readme.and_then(|r| r.lines().find_map(|l| l.strip_prefix("启动命令：")));
    let goal_met = read_successes > 0
        && stop == "final_answer"
        && matches!((&last_answer, expected), (Some(a), Some(c)) if *a == format!("README 里的启动命令是：{c}"));
    let model_calls = model.requests.lock().unwrap().len();
    Ok(Outcome {
        lines,
        model_calls,
        tool_results,
        read_attempts: counters.read_attempts.load(Ordering::SeqCst),
        read_successes,
        session_events: session.events().len(),
        stop,
        goal_met,
    })
}

fn parse() -> std::result::Result<(String, Limits), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (mut scenario, mut limits) = (
        "normal".to_string(),
        Limits {
            max_model_calls: None,
            max_tool_calls: None,
            max_iterations: None,
        },
    );
    let mut i = 0;
    while i < args.len() {
        let value = args.get(i + 1).ok_or("missing value")?;
        match args[i].as_str() {
            // model-error 只在测试里用，命令行不接受
            "--scenario" if SCENARIOS.contains(&value.as_str()) && value != "model-error" => {
                scenario = value.clone()
            }
            "--max-model-calls" => {
                limits.max_model_calls = Some(value.parse().map_err(|_| "bad number")?)
            }
            "--max-tool-calls" => {
                limits.max_tool_calls = Some(value.parse().map_err(|_| "bad number")?)
            }
            "--max-iterations" => {
                limits.max_iterations = Some(value.parse().map_err(|_| "bad number")?)
            }
            _ => return Err(format!("bad argument {} {}", args[i], value)),
        }
        i += 2;
    }
    Ok((scenario, limits))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let (scenario, limits) = match parse() {
        Ok(parsed) => parsed,
        Err(error) => {
            eprintln!(
                "usage: agent-loop [--scenario NAME] [--max-model-calls N] [--max-tool-calls N] [--max-iterations N] ({error})"
            );
            std::process::exit(2);
        }
    };
    let show = |v: Option<u64>| v.map_or("不限".to_string(), |n| n.to_string());
    println!("场景：{scenario}；模型：RuleLlm（按规则读取请求内容的脚本模型）");
    println!(
        "预算：model_calls={} tool_calls={}；循环上限：{}",
        show(limits.max_model_calls),
        show(limits.max_tool_calls),
        limits
            .max_iterations
            .map_or("默认 100".to_string(), |n| n.to_string())
    );
    let o = run(&scenario, &limits).await?;
    for line in &o.lines {
        println!("{line}");
    }
    println!(
        "统计：model_calls={} tool_results={} read_attempts={} read_successes={} session_events={}",
        o.model_calls, o.tool_results, o.read_attempts, o.read_successes, o.session_events
    );
    println!("停止：{}；fixture_goal_met={}", o.stop, o.goal_met);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn limits(model: Option<u64>, tool: Option<u64>) -> Limits {
        Limits {
            max_model_calls: model,
            max_tool_calls: tool,
            max_iterations: None,
        }
    }

    #[tokio::test]
    async fn zero_model_budget_makes_no_call() {
        let o = run("normal", &limits(Some(0), None)).await.unwrap();
        assert_eq!((o.model_calls, o.tool_results, o.read_attempts), (0, 0, 0));
        assert_eq!(o.stop, "budget.model_calls");
    }

    #[tokio::test]
    async fn a_batch_cannot_partly_consume_the_tool_budget() {
        let o = run("two-tools", &limits(None, Some(1))).await.unwrap();
        // 两个调用都拿到 not_run 结果，一次读取都没有发生
        assert_eq!(
            (o.tool_results, o.read_attempts, o.stop.as_str()),
            (2, 0, "budget.tool_calls")
        );
    }

    #[tokio::test]
    async fn a_reused_call_id_is_executed_again() {
        // 框架不检查调用 ID 是否重复：第二轮沿用 read-1，工具照样执行
        let o = run("duplicate-id", &limits(None, None)).await.unwrap();
        assert_eq!((o.read_attempts, o.stop.as_str()), (2, "final_answer"));
    }

    #[tokio::test]
    async fn the_answer_comes_from_the_file_actually_read() {
        let o = run("changed-readme", &limits(None, None)).await.unwrap();
        assert!(o.goal_met && o.lines.iter().any(|l| l.contains("cargo run --release")));
    }

    #[tokio::test]
    async fn a_final_answer_is_not_the_goal() {
        let o = run("missing-file", &limits(None, None)).await.unwrap();
        assert_eq!((o.stop.as_str(), o.goal_met), ("final_answer", false));
    }

    #[tokio::test]
    async fn the_loop_limit_stops_before_the_next_model_call() {
        let mut l = limits(None, None);
        l.max_iterations = Some(3);
        let o = run("repeat", &l).await.unwrap();
        // 三轮各调用一次模型、各读一次，准备第四次调用时超限；这种停止不写停止事件
        assert_eq!(
            (o.model_calls, o.read_attempts, o.stop.as_str()),
            (3, 3, "agent.legacy")
        );
    }

    #[tokio::test]
    async fn a_model_failure_stops_the_run_without_running_tools() {
        let o = run("model-error", &limits(None, None)).await.unwrap();
        assert_eq!((o.model_calls, o.tool_results, o.read_attempts), (1, 0, 0));
        assert_ne!(o.stop, "final_answer");
    }
}
