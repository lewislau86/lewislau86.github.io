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
    let mut builder = GraphBuilder::new("D01-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &["choose", "read", "observe", "generate", "accept"];
const SCENARIOS: &[&str] = &[
    "single",
    "workflow",
    "adaptive",
    "missing",
    "forbidden",
    "budget",
];
// region selection
#[derive(Debug, PartialEq)]
enum Strategy {
    Single,
    Workflow,
    Adaptive,
}
fn choose(ready: bool, dynamic: bool) -> Strategy {
    if ready {
        Strategy::Single
    } else if dynamic {
        Strategy::Adaptive
    } else {
        Strategy::Workflow
    }
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "choose" => {
            let mode = choose(s.scenario == "single", s.scenario == "adaptive");
            s.data = json!({"strategy": format!("{mode:?}"), "evidence": [], "reads": 0});
            if mode == Strategy::Single {
                s.data["evidence"] = json!(["root"]);
                return Some("generate");
            }
        }
        "read" => {
            if s.scenario == "forbidden" {
                s.reject("permission_denied");
                return None;
            }
            if s.scenario == "missing" {
                s.reject("missing_evidence");
                return None;
            }
            let reads = s.data["reads"].as_u64().unwrap();
            s.data["evidence"]
                .as_array_mut()
                .unwrap()
                .push(json!(if reads == 0 { "root" } else { "member" }));
            s.data["reads"] = json!(reads + 1);
        }
        "observe" => {
            if s.scenario == "adaptive" && s.data["reads"] == 1 {
                return Some("read");
            }
        }
        "generate" => {
            s.data["report"] = json!(s.data["evidence"].as_array().unwrap().len());
        }
        "accept" => {
            s.reject(if s.data["report"].as_u64().unwrap_or(0) > 0 {
                "completed"
            } else {
                "missing_evidence"
            });
        }
        _ => unreachable!(),
    }
    None
}
// endregion selection
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
    #[test]
    fn minimal_structure() {
        assert_eq!(choose(true, true), Strategy::Single);
        assert_eq!(choose(false, false), Strategy::Workflow);
    }
    #[tokio::test]
    async fn new_observation_adds_one_read() {
        let s = run("adaptive").await.unwrap();
        assert_eq!(s.data["reads"], 2);
        assert_eq!(s.stop, "completed");
    }
    #[tokio::test]
    async fn denied_has_no_effect() {
        let s = run("forbidden").await.unwrap();
        assert_eq!(s.data["reads"], 0);
        assert!(s.data.get("report").is_none());
    }
    #[tokio::test]
    async fn total_budget() {
        let s = run("budget").await.unwrap();
        assert_eq!(s.used, 1);
        assert_eq!(s.stop, "budget_exhausted");
    }
}
