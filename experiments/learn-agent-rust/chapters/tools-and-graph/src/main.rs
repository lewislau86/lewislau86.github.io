//! R02: deterministic model, real filesystem tools, explicit loop vs graph-flow.
use async_trait::async_trait;
use futures::Stream;
use graph_flow::{Context, ExecutionStatus, GraphBuilder, NextAction, Session, Task, TaskResult};
use langchain_rust::{
    language_models::{GenerateResult, LLMError, llm::LLM},
    schemas::{Message, MessageType, StreamData, ToolCall},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::Read,
    path::Path,
    pin::Pin,
    sync::Arc,
};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
const REQUEST: &str = "先列出练习目录，再读取 README.md，告诉我如何启动项目。";
const README: &str = "# Demo\n启动命令：cargo run\n";

// region registry
struct Tool {
    description: &'static str,
    parameters: Value,
    handler: fn(&Path, Value) -> std::result::Result<Value, &'static str>,
}

struct Registry(BTreeMap<&'static str, Tool>);

impl Registry {
    fn definitions(&self) -> Vec<Value> {
        self.0
            .iter()
            .map(|(name, tool)| {
                json!({
                    "type": "function",
                    "function": {"name": name, "description": tool.description,
                                 "parameters": tool.parameters}
                })
            })
            .collect()
    }

    fn dispatch(&self, root: &Path, call: &ToolCall) -> Value {
        let result = self
            .0
            .get(call.name.as_str())
            .ok_or("unknown_tool")
            .and_then(|tool| {
                let args = serde_json::from_str(&call.arguments).map_err(|_| "invalid_json")?;
                (tool.handler)(root, args)
            });
        match result {
            Ok(data) => json!({"ok": true, "data": data}),
            Err(code) => json!({"ok": false, "error": code}),
        }
    }
}
// endregion registry

// region tools
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PathArgs {
    path: String,
}

fn read_file(root: &Path, args: Value) -> std::result::Result<Value, &'static str> {
    let args: PathArgs = serde_json::from_value(args).map_err(|_| "invalid_arguments")?;
    if args.path != "README.md" {
        return Err("invalid_arguments");
    }
    let path = root
        .join(&args.path)
        .canonicalize()
        .map_err(|_| "file_unavailable")?;
    if !path.starts_with(root) {
        return Err("outside_workspace");
    }
    let file = fs::File::open(path).map_err(|_| "file_unavailable")?;
    let mut bytes = Vec::new();
    file.take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| "read_failed")?;
    if bytes.len() > 4096 {
        return Err("file_too_large");
    }
    let text = String::from_utf8(bytes).map_err(|_| "invalid_utf8")?;
    Ok(json!({"text": text}))
}

fn list_files(root: &Path, args: Value) -> std::result::Result<Value, &'static str> {
    let args: PathArgs = serde_json::from_value(args).map_err(|_| "invalid_arguments")?;
    if args.path != "." {
        return Err("invalid_arguments");
    }
    let entries = fs::read_dir(root).map_err(|_| "directory_unavailable")?;
    let mut names = Vec::new();
    for entry in entries.take(33) {
        let entry = entry.map_err(|_| "directory_unavailable")?;
        names.push(
            entry
                .file_name()
                .into_string()
                .map_err(|_| "invalid_utf8")?,
        );
    }
    if names.len() > 32 {
        return Err("too_many_entries");
    }
    names.sort();
    Ok(json!({"entries": names}))
}

fn registry() -> Registry {
    let schema = |path| {
        json!({
            "type": "object", "properties": {"path": {"type": "string", "enum": [path]}},
            "required": ["path"], "additionalProperties": false
        })
    };
    Registry(BTreeMap::from([
        (
            "read_file",
            Tool {
                description: "读取练习目录的 README.md，最多 4096 字节。",
                parameters: schema("README.md"),
                handler: read_file,
            },
        ),
        (
            "list_files",
            Tool {
                description: "列出练习目录的直接子项，最多 32 项，按名称排序。",
                parameters: schema("."),
                handler: list_files,
            },
        ),
    ]))
}
// endregion tools

// region state
#[derive(Clone, Debug, Serialize, Deserialize)]
struct State {
    messages: Vec<Message>,
    pending: Vec<ToolCall>,
    seen_ids: BTreeSet<String>,
    model_turns: usize,
    max_turns: usize,
    tool_dispatches: usize,
    stop: Option<String>,
}

impl State {
    fn new(max_turns: usize) -> Self {
        Self {
            messages: vec![Message::new_human_message(REQUEST)],
            pending: vec![],
            seen_ids: BTreeSet::new(),
            model_turns: 0,
            max_turns,
            tool_dispatches: 0,
            stop: None,
        }
    }
}
// endregion state

// A fixture implementing the actual langchain-rust trait. No HTTP client is created.
#[derive(Clone)]
struct ScriptedModel {
    scenario: String,
    definitions: Vec<Value>,
}

#[async_trait]
impl LLM for ScriptedModel {
    async fn generate(
        &self,
        messages: &[Message],
    ) -> std::result::Result<GenerateResult, LLMError> {
        assert_eq!(self.definitions.len(), 2);
        let previous: Vec<_> = messages
            .iter()
            .filter(|m| m.message_type == MessageType::ToolMessage)
            .collect();
        let calls = if previous.is_empty() {
            match self.scenario.as_str() {
                "unknown-tool" => vec![ToolCall::new("bad-1", "delete_file", "{}")],
                "invalid-json" => vec![ToolCall::new("bad-1", "read_file", "{")],
                "invalid-args" => vec![ToolCall::new("bad-1", "read_file", r#"{"path":42}"#)],
                "duplicate-id" => vec![
                    ToolCall::new("same", "list_files", r#"{"path":"."}"#),
                    ToolCall::new("same", "read_file", r#"{"path":"README.md"}"#),
                ],
                "batch" => vec![
                    ToolCall::new("list-1", "list_files", r#"{"path":"."}"#),
                    ToolCall::new("read-1", "read_file", r#"{"path":"README.md"}"#),
                ],
                _ => vec![ToolCall::new("list-1", "list_files", r#"{"path":"."}"#)],
            }
        } else {
            let outputs: Vec<Value> = previous
                .iter()
                .map(|m| serde_json::from_str(&m.content).unwrap())
                .collect();
            if outputs.iter().any(|v| v["ok"] == false) {
                return Ok(GenerateResult {
                    generation: "工具返回错误，任务未完成。".into(),
                    ..Default::default()
                });
            }
            if previous.iter().any(|m| m.id.as_deref() == Some("read-1")) {
                let read = previous
                    .iter()
                    .find(|m| m.id.as_deref() == Some("read-1"))
                    .unwrap();
                let output: Value = serde_json::from_str(&read.content)?;
                let text = output["data"]["text"].as_str().unwrap();
                if !text.lines().any(|line| line == "启动命令：cargo run") {
                    return Err(LLMError::OtherError("Unexpected fixture contents".into()));
                }
                return Ok(GenerateResult {
                    generation: "README 里的启动命令是：cargo run".into(),
                    ..Default::default()
                });
            }
            vec![ToolCall::new(
                "read-1",
                "read_file",
                r#"{"path":"README.md"}"#,
            )]
        };
        Ok(GenerateResult::default().with_tool_calls(calls))
    }

    async fn stream(
        &self,
        _: &[Message],
    ) -> std::result::Result<
        Pin<Box<dyn Stream<Item = std::result::Result<StreamData, LLMError>> + Send>>,
        LLMError,
    > {
        Err(LLMError::OtherError("R02 uses generate only".into()))
    }
}

// region model-turn
async fn model_turn(state: &mut State, model: &dyn LLM) -> Result<()> {
    if state.model_turns >= state.max_turns {
        state.stop = Some("turn_limit".into());
        return Ok(());
    }
    state.model_turns += 1;
    let result = model.generate(&state.messages).await?;
    // Validate the complete batch before recording or executing any of its calls.
    let mut ids = state.seen_ids.clone();
    if result
        .tool_calls
        .iter()
        .any(|c| c.id.is_empty() || !ids.insert(c.id.clone()))
    {
        state.stop = Some("invalid_call_id".into());
        return Ok(());
    }
    state.seen_ids = ids;
    if result.tool_calls.is_empty() {
        state
            .messages
            .push(Message::new_ai_message(result.generation));
        let failed = state
            .messages
            .iter()
            .filter(|m| m.message_type == MessageType::ToolMessage)
            .any(|m| serde_json::from_str::<Value>(&m.content).unwrap()["ok"] == false);
        state.stop = Some(if failed { "tool_error" } else { "completed" }.into());
    } else {
        state.messages.push(Message::new_ai_message_with_tool_calls(
            "",
            &result.tool_calls,
        ));
        state.pending = result.tool_calls;
    }
    Ok(())
}
// endregion model-turn

// region execute-tools
fn execute_tools(state: &mut State, registry: &Registry, root: &Path) {
    for call in std::mem::take(&mut state.pending) {
        let output = registry.dispatch(root, &call);
        state.tool_dispatches += 1;
        state
            .messages
            .push(Message::new_tool_message(output, call.id));
    }
}
// endregion execute-tools

// region explicit-loop
async fn run_explicit(
    mut state: State,
    model: &dyn LLM,
    registry: &Registry,
    root: &Path,
) -> Result<State> {
    loop {
        model_turn(&mut state, model).await?;
        if state.stop.is_some() {
            return Ok(state);
        }
        execute_tools(&mut state, registry, root);
    }
}
// endregion explicit-loop

struct ModelTurn {
    model: Arc<dyn LLM>,
}
struct ExecuteTools {
    registry: Arc<Registry>,
    root: std::path::PathBuf,
}

fn load_state(context: &Context) -> graph_flow::Result<State> {
    context
        .get("agent")
        .ok_or_else(|| graph_flow::GraphError::TaskExecutionFailed("Missing agent state".into()))
}

// region graph-nodes
#[async_trait]
impl Task for ModelTurn {
    fn id(&self) -> &str {
        "ModelTurn"
    }
    async fn run(&self, context: Context) -> graph_flow::Result<TaskResult> {
        let mut state = load_state(&context)?;
        model_turn(&mut state, self.model.as_ref())
            .await
            .map_err(|e| graph_flow::GraphError::TaskExecutionFailed(e.to_string()))?;
        let action = if state.stop.is_some() {
            NextAction::End
        } else {
            NextAction::Continue
        };
        context.set("agent", state)?;
        Ok(TaskResult::new(None, action))
    }
}

#[async_trait]
impl Task for ExecuteTools {
    fn id(&self) -> &str {
        "ExecuteTools"
    }
    async fn run(&self, context: Context) -> graph_flow::Result<TaskResult> {
        let mut state = load_state(&context)?;
        execute_tools(&mut state, &self.registry, &self.root);
        context.set("agent", state)?;
        Ok(TaskResult::new(None, NextAction::Continue))
    }
}
// endregion graph-nodes

// region graph-runner
async fn run_graph(
    state: State,
    model: Arc<dyn LLM>,
    registry: Arc<Registry>,
    root: &Path,
) -> Result<(State, Vec<String>)> {
    let graph = GraphBuilder::new("r02")
        .add_task(Arc::new(ModelTurn { model }))
        .add_task(Arc::new(ExecuteTools {
            registry,
            root: root.into(),
        }))
        .add_edge("ModelTurn", "ExecuteTools")
        .add_edge("ExecuteTools", "ModelTurn")
        .set_start_task("ModelTurn")
        .build()?;
    let mut session = Session::new_from_task("r02-demo".into(), "ModelTurn").with_graph_id("r02");
    session.context.set("agent", state)?;
    let mut nodes = Vec::new();
    loop {
        nodes.push(session.current_task_id.clone());
        let result = graph.execute_session(&mut session).await?;
        match result.status {
            ExecutionStatus::Completed => break,
            ExecutionStatus::Paused { .. } => {}
            other => return Err(format!("Unexpected graph status: {other:?}").into()),
        }
    }
    Ok((load_state(&session.context)?, nodes))
}
// endregion graph-runner

fn check_pairs(state: &State) {
    let mut pending = BTreeSet::new();
    for message in &state.messages {
        match message.message_type {
            MessageType::AIMessage => {
                assert!(
                    pending.is_empty(),
                    "Tool results must precede the next assistant message"
                );
                for call in message.parse_tool_calls() {
                    assert!(pending.insert(call.id));
                }
            }
            MessageType::ToolMessage => {
                assert!(pending.remove(message.id.as_ref().unwrap()));
            }
            _ => {}
        }
    }
    assert!(pending.is_empty());
    assert!(state.pending.is_empty());
}

const SCENARIOS: &[(&str, usize, usize, usize, &str)] = &[
    ("normal", 3, 2, 6, "completed"),
    ("batch", 2, 2, 5, "completed"),
    ("unknown-tool", 2, 1, 4, "tool_error"),
    ("invalid-json", 2, 1, 4, "tool_error"),
    ("invalid-args", 2, 1, 4, "tool_error"),
    ("missing-file", 3, 2, 6, "tool_error"),
    ("duplicate-id", 1, 0, 1, "invalid_call_id"),
    ("zero-budget", 0, 0, 1, "turn_limit"),
    ("turn-limit", 1, 1, 3, "turn_limit"),
];

async fn compare(name: &str) -> Result<Value> {
    let (_, turns, executions, messages, stop) = SCENARIOS
        .iter()
        .find(|s| s.0 == name)
        .ok_or("Unknown scenario")?;
    let workspace = tempfile::tempdir()?;
    let root = workspace.path().canonicalize()?;
    fs::write(root.join("Cargo.toml"), "[package]\nname = \"demo\"\n")?;
    if name != "missing-file" {
        fs::write(root.join("README.md"), README)?;
    }
    let registry = Arc::new(registry());
    let model: Arc<dyn LLM> = Arc::new(ScriptedModel {
        scenario: name.into(),
        definitions: registry.definitions(),
    });
    let budget = match name {
        "zero-budget" => 0,
        "turn-limit" => 1,
        _ => 4,
    };
    let explicit = run_explicit(State::new(budget), model.as_ref(), &registry, &root).await?;
    let (graph, nodes) = run_graph(State::new(budget), model, registry, &root).await?;
    // Compare the complete serializable state, including every message and call ID.
    assert_eq!(
        serde_json::to_value(&explicit)?,
        serde_json::to_value(&graph)?
    );
    assert_eq!(
        (
            graph.model_turns,
            graph.tool_dispatches,
            graph.messages.len()
        ),
        (*turns, *executions, *messages)
    );
    assert_eq!(graph.stop.as_deref(), Some(*stop));
    check_pairs(&graph);
    if *stop == "completed" {
        assert_eq!(
            graph.messages.last().unwrap().content,
            "README 里的启动命令是：cargo run"
        );
    }
    Ok(json!({"scenario": name, "equal": true, "graph_nodes": nodes, "state": graph}))
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(String::as_str) == Some("--json") {
        println!(
            "{}",
            serde_json::to_string_pretty(
                &compare(args.get(1).map(String::as_str).unwrap_or("normal")).await?
            )?
        );
        return Ok(());
    }
    println!("R02 | scripted model + real filesystem | explicit vs graph-flow");
    for (name, ..) in SCENARIOS {
        let report = compare(name).await?;
        let state = &report["state"];
        println!(
            "{name}: equal=true turns={} dispatches={} messages={} stop={}",
            state["model_turns"],
            state["tool_dispatches"],
            state["messages"].as_array().unwrap().len(),
            state["stop"].as_str().unwrap()
        );
        if *name == "normal" {
            let nodes: Vec<_> = report["graph_nodes"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap())
                .collect();
            println!("nodes: {}", nodes.join(" -> "));
            println!(
                "answer: {}",
                state["messages"].as_array().unwrap().last().unwrap()["content"]
                    .as_str()
                    .unwrap()
            );
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn explicit_and_graph_obey_the_same_scenario_contracts() -> Result<()> {
        for (name, ..) in SCENARIOS {
            compare(name).await?;
        }
        Ok(())
    }

    #[test]
    fn registry_validates_arguments_and_reads_actual_fixture() {
        let temp = tempfile::tempdir().unwrap();
        let root = temp.path().canonicalize().unwrap();
        let registry = registry();
        fs::write(root.join("README.md"), "changed fixture").unwrap();
        let call = |args| ToolCall::new("read", "read_file", args);
        assert_eq!(
            registry.dispatch(&root, &call(r#"{"path":"README.md"}"#))["data"]["text"],
            "changed fixture"
        );
        for args in [
            r#"{"path":"../README.md"}"#,
            r#"{"path":"/etc/passwd"}"#,
            r#"{"path":"README.md","extra":true}"#,
            "null",
            r#"{"path":42}"#,
        ] {
            assert_eq!(
                registry.dispatch(&root, &call(args))["error"],
                "invalid_arguments"
            );
        }
        fs::write(root.join("README.md"), vec![b'x'; 4097]).unwrap();
        assert_eq!(
            registry.dispatch(&root, &call(r#"{"path":"README.md"}"#))["error"],
            "file_too_large"
        );
    }
}
