//! R02（ADK-Rust 3.0）：工具注册、调用 ID 配对，以及把同一个 Agent 放进图里调度。
//!
//! 默认运行全部场景，每个场景分别用 Runner 直接运行 LlmAgent、再把同一个 Agent
//! 放进 adk-graph 的图里运行，比较两条路径的事件轨迹、模型请求和停止原因。
//! 模型是 ScriptedLlm（固定脚本，不读凭据、不联网）；文件工具读取程序自建的临时目录。
mod trace;

use std::{collections::HashMap, fs, io::Read, path::PathBuf, sync::Arc};

use adk_agent::{LlmAgent, LlmAgentBuilder};
use adk_core::{
    AdkError, Agent, Content, ErrorCategory, ErrorComponent, Event, FinishReason, LlmResponse,
    Part, RunBudget, ToolContext, ToolEffect,
};
use adk_graph::{
    agent::GraphAgent,
    edge::{END, START},
    node::{AgentNode, NodeOutput},
};
use adk_model::{ScriptedLlm, ScriptedResponse};
use adk_runner::Runner;
use adk_session::{CreateRequest, InMemorySessionService, SessionService};
use adk_tool::FunctionTool;
use futures::StreamExt;
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

const REQUEST: &str = "先列出练习目录，再读取 README.md，告诉我如何启动项目。";
const README: &str = "# Demo\n启动命令：cargo run\n";
const ANSWER: &str = "README 里的启动命令是：cargo run";
const SCENARIOS: [&str; 14] = [
    "normal",
    "batch",
    "unknown-tool",
    "invalid-args",
    "extra-field",
    "invalid-json",
    "not-an-object",
    "outside-path",
    "missing-file",
    "unreadable-file",
    "unreadable-file-exposed",
    "duplicate-id",
    "zero-budget",
    "turn-limit",
];

// region schema
/// 两个工具共用的参数类型：schema 由它生成，FunctionTool 在调用处理函数之前按 schema 校验
/// （对象 schema 默认封闭，多余字段也会被拒绝），处理函数再把参数解析成这个类型。
#[derive(Serialize, Deserialize, JsonSchema)]
struct PathArgs {
    /// list_files 只接受 "."，read_file 只接受 "README.md"
    path: String,
}

fn tool_error(category: ErrorCategory, code: &'static str, message: &str) -> AdkError {
    AdkError::new(ErrorComponent::Tool, category, code, message)
}

/// 解析参数，并检查 schema 管不到的取值规则：路径必须是这个工具允许的那一个。
fn allowed_path(args: Value, allowed: &str) -> adk_core::Result<()> {
    let PathArgs { path } = serde_json::from_value(args)
        .map_err(|e| tool_error(ErrorCategory::InvalidInput, "args.decode", &e.to_string()))?;
    if path == allowed {
        Ok(())
    } else {
        Err(tool_error(
            ErrorCategory::Forbidden,
            "path.not_allowed",
            &format!("path {path:?} is outside this tool's scope"),
        ))
    }
}

// endregion schema

// region tools
fn list_files_tool(root: Arc<PathBuf>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let root = root.clone();
        async move {
            allowed_path(args, ".")?;
            let unavailable =
                |_| tool_error(ErrorCategory::Unavailable, "dir.unavailable", "cannot list");
            let mut names = Vec::new();
            for entry in fs::read_dir(root.as_path()).map_err(unavailable)?.take(33) {
                let name = entry.map_err(unavailable)?.file_name();
                names.push(name.to_string_lossy().into_owned());
            }
            if names.len() > 32 {
                return Err(tool_error(
                    ErrorCategory::ResourceExhausted,
                    "dir.too_large",
                    "over 32 entries",
                ));
            }
            names.sort();
            Ok(json!({ "entries": names }))
        }
    };
    FunctionTool::new(
        "list_files",
        "列出练习目录的直接子项，最多 32 项，按名称排序。",
        handler,
    )
    .with_parameters_schema::<PathArgs>()
    .with_effect(ToolEffect::ReadOnly)
}

fn read_file_tool(root: Arc<PathBuf>) -> FunctionTool {
    let handler = move |_ctx: Arc<dyn ToolContext>, args: Value| {
        let root = root.clone();
        async move {
            allowed_path(args, "README.md")?;
            // 错误类别决定模型能看到什么：NotFound 属于“拒绝”类，消息交给模型；
            // Unavailable 属于“下游故障”类，默认只交出错误码，消息留在本地。
            let io_error = |error: std::io::Error| match error.kind() {
                std::io::ErrorKind::NotFound => tool_error(
                    ErrorCategory::NotFound,
                    "file.missing",
                    "README.md does not exist",
                ),
                _ => tool_error(
                    ErrorCategory::Unavailable,
                    "file.unreadable",
                    &format!("read README.md: {error}"),
                ),
            };
            let path = root.join("README.md").canonicalize().map_err(io_error)?;
            if !path.starts_with(root.as_path()) {
                return Err(tool_error(
                    ErrorCategory::Forbidden,
                    "path.outside",
                    "outside workspace",
                ));
            }
            let mut bytes = Vec::new();
            fs::File::open(&path)
                .map_err(io_error)?
                .take(4097)
                .read_to_end(&mut bytes)
                .map_err(io_error)?;
            if bytes.len() > 4096 {
                return Err(tool_error(
                    ErrorCategory::ResourceExhausted,
                    "file.too_large",
                    "over 4096 bytes",
                ));
            }
            let text = String::from_utf8(bytes).map_err(|_| {
                tool_error(ErrorCategory::InvalidInput, "file.not_utf8", "not UTF-8")
            })?;
            Ok(json!({ "text": text }))
        }
    };
    FunctionTool::new(
        "read_file",
        "读取练习目录的 README.md，最多 4096 字节。",
        handler,
    )
    .with_parameters_schema::<PathArgs>()
    .with_effect(ToolEffect::ReadOnly)
}
// endregion tools

// region agent
/// 每个场景的可变部分：模型脚本、循环上限、预算，以及工具错误是否交给模型。
struct Scenario {
    script: Vec<ScriptedResponse>,
    max_iterations: Option<u32>,
    max_model_calls: Option<u64>,
    expose_errors: bool,
    readme: Readme,
}

/// 练习目录里的 README：正常文件、不存在，或者同名目录（读取时报 I/O 错误）。
#[derive(Clone, Copy, PartialEq)]
enum Readme {
    File,
    Missing,
    Directory,
}

fn build_agent(
    model: Arc<ScriptedLlm>,
    root: Arc<PathBuf>,
    s: &Scenario,
) -> adk_core::Result<LlmAgent> {
    let mut builder = LlmAgentBuilder::new("assistant")
        .instruction("先列出练习目录，再读取 README.md，根据实际内容回答启动命令。")
        .model(model)
        // 声明顺序就是注册顺序（不按字母排），请求记录里的 tools=[...] 可以核对
        .tool(Arc::new(read_file_tool(root.clone())))
        .tool(Arc::new(list_files_tool(root)))
        .expose_tool_error_messages(s.expose_errors);
    if let Some(max) = s.max_iterations {
        builder = builder.max_iterations(max);
    }
    builder.build()
}
// endregion agent

// region scripts
fn call(name: &str, path: Value) -> (String, Value) {
    (name.to_string(), json!({ "path": path }))
}

/// 一条带指定调用 ID 的模型回复（ScriptedLlm 只在 ID 为空时才自动编号）。
fn calls_with_ids(calls: Vec<(&str, Value, &str)>) -> ScriptedResponse {
    let parts = calls
        .into_iter()
        .map(|(name, args, id)| Part::FunctionCall {
            name: name.into(),
            args,
            id: Some(id.into()),
            thought_signature: None,
        })
        .collect();
    let mut response = LlmResponse::new(Content {
        role: "model".into(),
        parts,
    });
    response.finish_reason = Some(FinishReason::Stop);
    response.turn_complete = true;
    ScriptedResponse::response(response)
}

fn scenario(name: &str) -> Scenario {
    let one = |c: (String, Value)| ScriptedResponse::function_calls([c]);
    let list = || one(call("list_files", json!(".")));
    let read = || one(call("read_file", json!("README.md")));
    let fail = || ScriptedResponse::text("没能读到 README，任务未完成。");
    let mut s = Scenario {
        script: vec![list(), read(), ScriptedResponse::text(ANSWER)],
        max_iterations: None,
        max_model_calls: None,
        expose_errors: false,
        readme: Readme::File,
    };
    match name {
        "normal" => {}
        "batch" => {
            let both = ScriptedResponse::function_calls([
                call("list_files", json!(".")),
                call("read_file", json!("README.md")),
            ]);
            s.script = vec![both, ScriptedResponse::text(ANSWER)];
        }
        "unknown-tool" => s.script = vec![one(call("search_files", json!("."))), fail()],
        "invalid-args" => s.script = vec![one(call("read_file", json!(42))), fail()],
        "extra-field" => {
            let args = json!({ "path": "README.md", "mode": "raw" });
            s.script = vec![ScriptedResponse::function_call("read_file", args), fail()];
        }
        "invalid-json" => {
            // 真实服务返回的参数文本解析不了时，模型适配器不会让这一轮失败，
            // 而是用这个标记对象代替参数；Agent 见到它就不运行工具，直接回答 not_run。
            let args =
                adk_core::invalid_tool_arguments("arguments are not valid JSON", "{\"path\": ");
            s.script = vec![ScriptedResponse::function_call("read_file", args), fail()];
        }
        "not-an-object" => {
            let args = json!("{\"path\": ");
            s.script = vec![ScriptedResponse::function_call("read_file", args), fail()];
        }
        "outside-path" => s.script = vec![one(call("read_file", json!("../secret.txt"))), fail()],
        "missing-file" => {
            s.script = vec![list(), read(), fail()];
            s.readme = Readme::Missing;
        }
        "unreadable-file" | "unreadable-file-exposed" => {
            s.script = vec![list(), read(), fail()];
            s.readme = Readme::Directory;
            s.expose_errors = name == "unreadable-file-exposed";
        }
        "duplicate-id" => {
            let batch = calls_with_ids(vec![
                ("list_files", json!({ "path": "." }), "call-1"),
                ("read_file", json!({ "path": "README.md" }), "call-1"),
            ]);
            s.script = vec![batch, ScriptedResponse::text(ANSWER)];
        }
        "zero-budget" => s.max_model_calls = Some(0),
        "turn-limit" => s.max_iterations = Some(1),
        other => panic!("unknown scenario {other}"),
    }
    s
}
// endregion scripts

// region graph
/// 从 Agent 的事件里取出最后的回答文本和最后一次 read_file 的结果，写进图状态。
fn answer_and_readme(events: &[Event]) -> HashMap<String, Value> {
    let mut updates = HashMap::new();
    for event in events.iter().filter(|e| !e.llm_response.partial) {
        for result in event.tool_results() {
            if result.name == "read_file" {
                updates.insert("readme".into(), result.response["text"].clone());
            }
        }
        if event.is_final_response() {
            let text: String = event
                .content()
                .map(|c| c.parts.iter().filter_map(Part::text).collect())
                .unwrap_or_default();
            updates.insert("answer".into(), json!(text));
        }
    }
    updates
}

/// 图：START → assistant（整个 LlmAgent，含模型与工具的往返）→ check_answer（普通函数节点）→ END。
fn build_graph(agent: LlmAgent) -> adk_graph::Result<GraphAgent> {
    let assistant = AgentNode::new(Arc::new(agent)).with_output_mapper(answer_and_readme);
    GraphAgent::builder("r02_graph")
        .channels(&["input", "messages", "answer", "readme", "verified"])
        .node(assistant)
        .node_fn("check_answer", |ctx| async move {
            let answer = ctx
                .get("answer")
                .and_then(Value::as_str)
                .unwrap_or_default();
            let readme = ctx
                .get("readme")
                .and_then(Value::as_str)
                .unwrap_or_default();
            Ok(NodeOutput::new().with_update("verified", json!(verified(answer, readme))))
        })
        .edge(START, "assistant")
        .edge("assistant", "check_answer")
        .edge("check_answer", END)
        // 图结束时把检查结果作为一条图事件交回 Runner
        // 没有 verified 时写 none，区分“节点判定为 false”和“节点没有运行”
        .output_mapper(|state| {
            let verdict = state.get("verified").and_then(Value::as_bool);
            let text = verdict.map_or("verified=none".to_string(), |ok| format!("verified={ok}"));
            // Event::new 的参数是 invocation_id，GraphAgent 会改写成本次运行的值，作者也由它补上
            let mut event = Event::new(String::new());
            event.set_content(Content::new("model").with_text(text));
            vec![event]
        })
        .build()
}

/// 回答里的命令必须和真实读到的 README 一致。
fn verified(answer: &str, readme: &str) -> bool {
    readme
        .lines()
        .find_map(|line| line.strip_prefix("启动命令："))
        .is_some_and(|command| answer.ends_with(command))
}
// endregion graph

#[derive(Debug, Serialize, PartialEq)]
struct Run {
    trace: Vec<String>,
    requests: Vec<String>,
    model_calls: usize,
    tool_results: usize,
    error: Option<String>,
    answer: Option<String>,
    verified: bool,
}

/// 用 Runner 运行一个 Agent（直接的 LlmAgent，或包着它的 GraphAgent），收集可比较的结果；
/// 图版另外返回 check_answer 节点写下的检查结果。
async fn run(name: &str, use_graph: bool) -> Result<(Run, Option<bool>)> {
    let mut s = scenario(name);
    let workspace = tempfile::tempdir()?;
    fs::write(
        workspace.path().join("Cargo.toml"),
        "[package]\nname = \"demo\"\n",
    )?;
    match s.readme {
        Readme::File => fs::write(workspace.path().join("README.md"), README)?,
        Readme::Directory => fs::create_dir(workspace.path().join("README.md"))?,
        Readme::Missing => {}
    }
    let root = Arc::new(workspace.path().canonicalize()?);
    let model = Arc::new(ScriptedLlm::new("scripted", std::mem::take(&mut s.script)));
    let agent = build_agent(model.clone(), root.clone(), &s)?;
    let root_agent: Arc<dyn Agent> = if use_graph {
        Arc::new(build_graph(agent)?)
    } else {
        Arc::new(agent)
    };

    // region runner
    let sessions = Arc::new(InMemorySessionService::new());
    sessions
        .create(CreateRequest {
            app_name: "r02".into(),
            user_id: "reader".into(),
            session_id: Some("s1".into()),
            state: Default::default(),
        })
        .await?;
    let mut builder = Runner::builder()
        .app_name("r02")
        .agent(root_agent)
        .session_service(sessions)
        .without_intra_compaction();
    if let Some(max) = s.max_model_calls {
        builder = builder.budget(RunBudget::new().max_model_calls(max));
    }
    let runner = builder.build()?;
    // endregion runner

    let mut out = Run {
        trace: vec![],
        requests: vec![],
        model_calls: 0,
        tool_results: 0,
        error: None,
        answer: None,
        verified: false,
    };
    let mut readme = String::new();
    let mut graph_check = None;
    // region events
    let mut stream = runner
        .run_str("reader", "s1", Content::new("user").with_text(REQUEST))
        .await?;
    while let Some(item) = stream.next().await {
        match item {
            // 图自己的事件（作者不是 assistant）不进入比较；比较的是 Agent 的行为
            Ok(event) if event.author == "assistant" => {
                for result in event.tool_results() {
                    out.tool_results += 1;
                    if result.name == "read_file" {
                        readme = result.response["text"].as_str().unwrap_or_default().into();
                    }
                }
                if event.is_final_response() && !event.llm_response.partial {
                    let text: String = event
                        .content()
                        .map(|c| c.parts.iter().filter_map(Part::text).collect())
                        .unwrap_or_default();
                    if !text.is_empty() {
                        out.answer = Some(text);
                    }
                }
                // 预算停止事件：直接运行时作者是 assistant，放进图里时作者是图本身，统一记作 [run]
                out.trace
                    .extend(trace::event_lines(&event).into_iter().map(|line| {
                        match line.split_once("] stop    ") {
                            Some((_, code)) => format!("[run] stop    {code}"),
                            None => line,
                        }
                    }));
            }
            Ok(event) => {
                if let Some(code) = &event.llm_response.error_code {
                    out.trace.push(format!("[run] stop    code={code}"));
                }
                let text = event
                    .content()
                    .and_then(|c| c.parts.first()?.text().map(str::to_owned));
                if let Some(flag) = text.as_deref().and_then(|t| t.strip_prefix("verified=")) {
                    graph_check = Some(flag == "true");
                }
            }
            Err(error) => {
                out.error = Some(error.code.to_string());
                break;
            }
        }
    }
    // endregion events
    runner.close().await;
    out.requests = trace::request_lines(&model.requests());
    out.model_calls = model.requests().len();
    out.verified = out.answer.as_deref().is_some_and(|a| verified(a, &readme));
    Ok((out, graph_check))
}

#[derive(Serialize)]
struct Report {
    scenario: String,
    equal: bool,
    direct: Run,
    graph: Run,
    /// 图里 check_answer 节点的结论；Agent 中途失败时图停在 assistant，没有结论
    graph_check: Option<bool>,
}

async fn report(name: &str) -> Result<Report> {
    let (direct, _) = run(name, false).await?;
    let (graph, graph_check) = run(name, true).await?;
    Ok(Report {
        scenario: name.into(),
        equal: direct == graph,
        direct,
        graph,
        graph_check,
    })
}

fn summary_line(r: &Report) -> String {
    let d = &r.direct;
    format!(
        "{}: equal={} model_calls={} tool_results={} stop={} verified={} graph_check={}",
        r.scenario,
        r.equal,
        d.model_calls,
        d.tool_results,
        d.error.as_deref().unwrap_or("final_answer"),
        d.verified,
        r.graph_check.map_or("none".to_string(), |v| v.to_string())
    )
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.as_slice() {
        [] => {
            println!("R02 | ScriptedLlm + real temp dir | Runner(LlmAgent) vs Runner(GraphAgent)");
            for name in SCENARIOS {
                let r = report(name).await?;
                println!("{}", summary_line(&r));
                if name == "normal" {
                    for line in &r.direct.trace {
                        println!("  {line}");
                    }
                }
            }
        }
        [flag, name] if flag == "--json" => {
            println!("{}", serde_json::to_string_pretty(&report(name).await?)?);
        }
        [flag, name] if flag == "--trace" => {
            let (r, _) = run(name, false).await?;
            for line in r.trace.iter().chain(&r.requests) {
                println!("{line}");
            }
            if let Some(error) = r.error {
                println!("stop: {error}");
            }
        }
        _ => return Err("usage: learn-agent-r02 [--json NAME | --trace NAME]".into()),
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn normal_reads_real_readme_in_three_model_calls() {
        let r = run("normal", false).await.unwrap().0;
        assert_eq!((r.model_calls, r.tool_results, r.error), (3, 2, None));
        assert!(r.verified, "answer must match the README actually read");
    }

    #[tokio::test]
    async fn batch_saves_one_model_call() {
        let r = run("batch", false).await.unwrap().0;
        assert_eq!((r.model_calls, r.tool_results), (2, 2));
    }

    #[tokio::test]
    async fn schema_rejects_before_the_handler_runs() {
        for name in ["invalid-args", "extra-field", "not-an-object"] {
            let r = run(name, false).await.unwrap().0;
            assert!(
                r.trace.iter().any(|l| l.contains("status=failed")),
                "{name}"
            );
            assert!(
                r.trace
                    .iter()
                    .any(|l| l.contains("invalid arguments for 'read_file'")),
                "{name}"
            );
        }
    }

    #[tokio::test]
    async fn undecodable_arguments_never_reach_the_tool() {
        let r = run("invalid-json", false).await.unwrap().0;
        assert!(r.trace.iter().any(|l| l.contains("status=not_run")));
    }

    #[tokio::test]
    async fn value_rules_stay_in_the_application() {
        let r = run("outside-path", false).await.unwrap().0;
        // 通过了 schema（是字符串），被处理函数里的取值检查拒绝
        assert!(r.trace.iter().any(|l| l.contains("(path.not_allowed)")));
    }

    #[tokio::test]
    async fn error_category_decides_what_the_model_sees() {
        let rejected = run("missing-file", false).await.unwrap().0;
        let hidden = run("unreadable-file", false).await.unwrap().0;
        let shown = run("unreadable-file-exposed", false).await.unwrap().0;
        assert!(
            rejected
                .trace
                .iter()
                .any(|l| l.contains("README.md does not exist"))
        );
        assert!(hidden.trace.iter().any(|l| l.contains("(file.unreadable)")));
        assert!(!hidden.trace.iter().any(|l| l.contains("read README.md:")));
        assert!(shown.trace.iter().any(|l| l.contains("read README.md:")));
    }

    #[tokio::test]
    async fn limits_stop_the_run_with_framework_codes() {
        assert_eq!(
            run("zero-budget", false).await.unwrap().0.error.as_deref(),
            Some("budget.model_calls")
        );
        let r = run("turn-limit", false).await.unwrap().0;
        assert_eq!((r.model_calls, r.tool_results, r.answer), (1, 1, None));
        assert!(r.error.is_some());
    }

    #[tokio::test]
    async fn graph_runs_the_same_agent_behaviour_for_every_scenario() {
        for name in SCENARIOS {
            let r = report(name).await.unwrap();
            assert!(r.equal, "{name}: direct and graph runs differ");
            // Agent 给出回答的场景，图里的 check_answer 节点必须运行，并得出同样结论
            if r.direct.answer.is_some() {
                assert_eq!(r.graph_check, Some(r.direct.verified), "{name}");
            }
        }
    }

    #[tokio::test]
    async fn every_call_in_normal_gets_exactly_one_result_with_its_id() {
        let r = run("normal", false).await.unwrap().0;
        let ids = |kind: &str| -> Vec<String> {
            r.trace
                .iter()
                .filter(|l| l.contains(kind))
                .filter_map(|l| l.split("id=").nth(1)?.split(' ').next().map(str::to_owned))
                .collect()
        };
        assert_eq!(ids("] call "), ids("] result "));
    }
}
