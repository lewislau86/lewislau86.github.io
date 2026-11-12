use async_trait::async_trait;
use graph_flow::{
    Context, ExecutionStatus, GraphBuilder, GraphError, NextAction, Session, Task, TaskResult,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::sync::Arc;

// region state
#[derive(Clone, Debug, Serialize, Deserialize)]
struct State {
    scenario: String,
    used: u32,
    limit: u32,
    trace: Vec<String>,
    stop: String,
    data: Value,
}
impl State {
    fn new(scenario: &str) -> Self {
        Self {
            scenario: scenario.into(),
            used: 0,
            limit: if scenario == "budget" { 1 } else { 32 },
            trace: vec![],
            stop: String::new(),
            data: json!({}),
        }
    }
    fn charge(&mut self, units: u32) -> bool {
        if units > self.limit.saturating_sub(self.used) {
            self.reject("budget_exhausted");
            false
        } else {
            self.used += units;
            true
        }
    }
    fn reject(&mut self, why: &str) {
        self.stop = why.into();
    }
}
// endregion state

struct Node(&'static str);
// region runner
#[async_trait]
impl Task for Node {
    fn id(&self) -> &str {
        self.0
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        let mut s: State = ctx
            .get("state")
            .ok_or_else(|| GraphError::ContextError("typed state missing".into()))?;
        if !s.charge(1) {
            s.reject("budget_exhausted");
        }
        if !s.stop.is_empty() {
            ctx.set("state", s)?;
            return Ok(TaskResult::new(None, NextAction::End));
        }
        s.trace.push(self.0.into());
        let destination = step(self.0, &mut s).await;
        let next = if !s.stop.is_empty() {
            NextAction::End
        } else {
            destination.map_or(NextAction::Continue, |id| NextAction::GoTo(id.into()))
        };
        ctx.set("state", s)?;
        Ok(TaskResult::new(None, next))
    }
}
async fn run(scenario: &str) -> graph_flow::Result<State> {
    if !SCENARIOS.contains(&scenario) {
        return Err(GraphError::ContextError("unknown scenario".into()));
    }
    let mut builder = GraphBuilder::new("D06-v1").with_max_execution_steps(32);
    for node in NODES {
        builder = builder.add_task(Arc::new(Node(node)));
    }
    for pair in NODES.windows(2) {
        builder = builder.add_edge(pair[0], pair[1]);
    }
    let graph = builder.set_start_task(NODES[0]).build()?;
    let mut session = Session::new_from_task("lab".into(), NODES[0]);
    session.context.set("state", State::new(scenario))?;
    for _ in 0..64 {
        let result = graph.execute_session(&mut session).await?;
        if matches!(result.status, ExecutionStatus::Completed) {
            return session
                .context
                .get("state")
                .ok_or_else(|| GraphError::ContextError("final state missing".into()));
        }
    }
    Err(GraphError::TaskExecutionFailed("host step bound".into()))
}
// endregion runner

const NODES: &[&str] = &["generate", "evaluate", "repair", "accept"];
const SCENARIOS: &[&str] = &[
    "normal",
    "already_good",
    "stale",
    "malformed",
    "no_progress",
    "new_error",
    "budget",
];
// region evaluation
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Candidate {
    revision: u32,
    text: String,
    sources: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Feedback {
    candidate_revision: u32,
    criterion: String,
}
fn evaluate(c: &Candidate) -> Result<(), &'static str> {
    if c.text.trim().is_empty() {
        return Err("empty_report");
    }
    if c.sources != ["README.md"] {
        return Err("missing_evidence");
    }
    Ok(())
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "generate" => {
            let c = Candidate {
                revision: 1,
                text: "upgrade reviewed".into(),
                sources: if s.scenario == "already_good" {
                    vec!["README.md".into()]
                } else {
                    vec![]
                },
            };
            s.data = json!({"candidate":c,"baseline":c,"repairs":0});
        }
        "evaluate" => {
            let c: Candidate = serde_json::from_value(s.data["candidate"].clone()).unwrap();
            if evaluate(&c).is_ok() {
                return Some("accept");
            }
            if s.data["repairs"].as_u64().unwrap() >= 2 {
                s.reject("repair_limit");
                return None;
            }
            if s.scenario == "malformed" {
                let raw = r#"{"candidate_revision":"wrong","criterion":5}"#;
                if serde_json::from_str::<Feedback>(raw).is_err() {
                    s.reject("invalid_feedback");
                    return None;
                }
            }
            s.data["feedback"] = json!(Feedback {
                candidate_revision: if s.scenario == "stale" { 0 } else { c.revision },
                criterion: evaluate(&c).unwrap_err().into()
            });
        }
        "repair" => {
            let mut c: Candidate = serde_json::from_value(s.data["candidate"].clone()).unwrap();
            let f: Feedback = serde_json::from_value(s.data["feedback"].clone()).unwrap();
            if f.candidate_revision != c.revision {
                s.reject("stale_feedback");
                return None;
            }
            let before = c.clone();
            if s.scenario != "no_progress" {
                c.sources = vec!["README.md".into()];
                if s.scenario == "new_error" {
                    c.text.clear();
                }
            }
            if c.text == before.text && c.sources == before.sources {
                s.reject("no_progress");
                return None;
            }
            c.revision += 1;
            s.data["candidate"] = json!(c);
            s.data["repairs"] = json!(s.data["repairs"].as_u64().unwrap() + 1);
            return Some("evaluate");
        }
        "accept" => s.reject("completed"),
        _ => unreachable!(),
    }
    None
}
// endregion evaluation
#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let scenario = args.first().map(String::as_str).unwrap_or("suite");
    if scenario == "suite" {
        for name in SCENARIOS {
            println!(
                "{}",
                serde_json::to_string(&run(name).await.expect("graph execution")).unwrap()
            );
        }
    } else {
        match run(scenario).await {
            Ok(s) => println!("{}", serde_json::to_string(&s).unwrap()),
            Err(e) => {
                eprintln!("{e}");
                std::process::exit(2);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn feedback_repairs_and_preserves_baseline() {
        let s = run("normal").await.unwrap();
        assert_eq!(s.stop, "completed");
        assert_eq!(s.data["baseline"]["sources"], json!([]));
        assert_eq!(s.data["repairs"], 1);
    }
    #[tokio::test]
    async fn stale_feedback_cannot_modify_candidate() {
        let s = run("stale").await.unwrap();
        assert_eq!(s.stop, "stale_feedback");
        assert_eq!(s.data["candidate"], s.data["baseline"]);
    }
    #[tokio::test]
    async fn rules_are_rechecked() {
        let s = run("new_error").await.unwrap();
        assert_ne!(s.stop, "completed");
        assert!(s.data["candidate"]["text"].as_str().unwrap().is_empty());
    }
    #[tokio::test]
    async fn unchanged_candidate_stops() {
        assert_eq!(run("no_progress").await.unwrap().stop, "no_progress");
    }
}
