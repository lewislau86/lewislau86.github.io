use crate::provider::{HttpModel, POLICY};
use async_trait::async_trait;
use graph_flow::{Context, ExecutionStatus, GraphBuilder, NextAction, Session, Task, TaskResult};
use langchain_rust::{
    language_models::llm::LLM,
    schemas::{Message, ToolCall},
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{collections::BTreeSet, fs, path::PathBuf, sync::Arc};

#[derive(Clone, Serialize, Deserialize)]
pub struct State {
    pub messages: Vec<Message>,
    pub pending: Vec<ToolCall>,
    pub seen: BTreeSet<String>,
    pub answer: Option<String>,
    pub stop: Option<String>,
    pub attempts: usize,
    pub reads: usize,
    pub read_result: Option<Value>,
}
impl Default for State {
    fn default() -> Self {
        Self {
            messages: vec![
                Message::new_system_message(POLICY),
                Message::new_human_message(
                    "Inspect this project's README.md and report its startup command.",
                ),
            ],
            pending: vec![],
            seen: BTreeSet::new(),
            answer: None,
            stop: None,
            attempts: 0,
            reads: 0,
            read_result: None,
        }
    }
}
fn load(c: &Context) -> graph_flow::Result<State> {
    c.get("state")
        .ok_or_else(|| graph_flow::GraphError::TaskExecutionFailed("missing state".into()))
}
fn finish(c: Context, s: State) -> graph_flow::Result<TaskResult> {
    let action = if s.stop.is_some() {
        NextAction::End
    } else {
        NextAction::Continue
    };
    c.set("state", s)?;
    Ok(TaskResult::new(None, action))
}
struct ModelTurn {
    model: HttpModel,
}
#[async_trait]
impl Task for ModelTurn {
    fn id(&self) -> &str {
        "ModelTurn"
    }
    // region turn
    async fn run(&self, c: Context) -> graph_flow::Result<TaskResult> {
        let mut s = load(&c)?;
        if s.attempts >= 3 {
            s.stop = Some("model_budget".into());
            return finish(c, s);
        }
        s.attempts += 1;
        match self.model.generate(&s.messages).await {
            Err(_) => {
                s.stop = Some(
                    self.model
                        .telemetry
                        .lock()
                        .unwrap()
                        .error
                        .clone()
                        .unwrap_or("model_error".into()),
                )
            }
            Ok(reply) if reply.tool_calls.is_empty() => {
                s.answer = Some(reply.generation.clone());
                s.messages.push(Message::new_ai_message(reply.generation));
                s.stop = Some("answered".into());
            }
            Ok(reply) => {
                if reply
                    .tool_calls
                    .iter()
                    .any(|c| !s.seen.insert(c.id.clone()))
                {
                    s.stop = Some("duplicate_call".into());
                } else {
                    s.messages.push(Message::new_ai_message_with_tool_calls(
                        "",
                        &reply.tool_calls,
                    ));
                    s.pending = reply.tool_calls;
                }
            }
        }
        finish(c, s)
    }
    // endregion turn
}
struct Execute {
    root: PathBuf,
}
#[async_trait]
impl Task for Execute {
    fn id(&self) -> &str {
        "ExecuteTools"
    }
    // region tool
    async fn run(&self, c: Context) -> graph_flow::Result<TaskResult> {
        let mut s = load(&c)?;
        for call in std::mem::take(&mut s.pending) {
            let args: Value = serde_json::from_str(&call.arguments).unwrap_or(Value::Null);
            let code = if call.name != "read_file" {
                Some("unknown_tool")
            } else if args != json!({"path":"README.md"}) {
                Some("permission_denied")
            } else if s.reads >= 1 {
                Some("tool_budget")
            } else {
                None
            };
            let result = if let Some(code) = code {
                s.stop = Some(code.into());
                json!({"ok":false,"error":code})
            } else {
                s.reads += 1;
                match fs::read_to_string(self.root.join("README.md")) {
                    Ok(text) if text.len() <= 4096 => json!({"ok":true,"text":text}),
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                        json!({"ok":false,"error":"not_found"})
                    }
                    _ => {
                        s.stop = Some("read_error".into());
                        json!({"ok":false,"error":"read_error"})
                    }
                }
            };
            s.read_result = Some(result.clone());
            s.messages.push(Message::new_tool_message(result, call.id));
        }
        finish(c, s)
    }
    // endregion tool
}
// region graph
pub async fn run(
    model: HttpModel,
    root: PathBuf,
) -> Result<(State, Vec<String>), Box<dyn std::error::Error + Send + Sync>> {
    let graph = GraphBuilder::new("p03-http")
        .add_task(Arc::new(ModelTurn { model }))
        .add_task(Arc::new(Execute { root }))
        .add_edge("ModelTurn", "ExecuteTools")
        .add_edge("ExecuteTools", "ModelTurn")
        .set_start_task("ModelTurn")
        .build()?;
    let mut session =
        Session::new_from_task("eval-run".into(), "ModelTurn").with_graph_id("p03-http");
    session.context.set("state", State::default())?;
    let mut nodes = vec![];
    for _ in 0..7 {
        nodes.push(session.current_task_id.clone());
        if matches!(
            graph.execute_session(&mut session).await?.status,
            ExecutionStatus::Completed
        ) {
            return Ok((load(&session.context)?, nodes));
        }
    }
    Err("graph_bound".into())
}
// endregion graph

// region grade
pub fn grade(s: &State, expected: &Value) -> Value {
    let parsed = s
        .answer
        .as_ref()
        .and_then(|text| serde_json::from_str::<Value>(text).ok());
    let schema = parsed.as_ref().is_some_and(|a| {
        a.as_object().is_some_and(|o| {
            o.len() == 2
                && o.contains_key("command")
                && a["source"] == "README.md"
                && (a["command"].is_null() || a["command"].is_string())
        })
    });
    let correct = schema && parsed.as_ref().unwrap()["command"] == *expected;
    let grounded = s.reads == 1 && s.read_result.is_some();
    json!({"schema_valid":schema,"answer_correct":correct,"read_observed":grounded,
        "task_pass":s.stop.as_deref()==Some("answered")&&schema&&correct&&grounded})
}
// endregion grade
