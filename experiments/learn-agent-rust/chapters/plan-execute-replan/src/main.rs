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
    let mut builder = GraphBuilder::new("D04-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &["plan", "validate", "execute", "observe", "finish"];
const SCENARIOS: &[&str] = &["normal", "discover", "cycle", "unknown", "repeat", "budget"];
// region replan
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Plan {
    revision: u32,
    steps: std::collections::BTreeMap<String, Vec<String>>,
}
fn validate_plan(p: &Plan) -> Result<(), &'static str> {
    fn visit(id: &str, p: &Plan, path: &mut Vec<String>) -> Result<(), &'static str> {
        if path.iter().any(|x| x == id) {
            return Err("dependency_cycle");
        }
        let deps = p.steps.get(id).ok_or("unknown_dependency")?;
        path.push(id.into());
        for d in deps {
            visit(d, p, path)?;
        }
        path.pop();
        Ok(())
    }
    if p.steps.len() > 4 {
        return Err("plan_too_large");
    }
    for id in p.steps.keys() {
        visit(id, p, &mut vec![])?;
    }
    Ok(())
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "plan" => {
            let mut steps = std::collections::BTreeMap::from([("root".into(), vec![])]);
            if s.scenario == "cycle" {
                steps.insert("root".into(), vec!["root".into()]);
            }
            if s.scenario == "unknown" {
                steps.insert("root".into(), vec!["ghost".into()]);
            }
            s.data = json!({"plan":Plan{revision:1,steps},"done":[],"replans":0});
        }
        "validate" => {
            let p: Plan = serde_json::from_value(s.data["plan"].clone()).unwrap();
            if let Err(e) = validate_plan(&p) {
                s.reject(e);
            }
        }
        "execute" => {
            let p: Plan = serde_json::from_value(s.data["plan"].clone()).unwrap();
            let done = s.data["done"].as_array().unwrap();
            let ready = p
                .steps
                .iter()
                .find(|(id, deps)| {
                    !done.contains(&json!(id)) && deps.iter().all(|d| done.contains(&json!(d)))
                })
                .map(|(id, _)| id.clone());
            if let Some(id) = ready {
                s.data["done"].as_array_mut().unwrap().push(json!(id));
            } else {
                return Some("finish");
            }
        }
        "observe" => {
            if ["discover", "repeat"].contains(&s.scenario.as_str()) && s.data["replans"] == 0 {
                let mut p: Plan = serde_json::from_value(s.data["plan"].clone()).unwrap();
                if s.scenario == "repeat" {
                    s.reject("repeated_plan");
                    return None;
                }
                p.revision += 1;
                p.steps.insert("member".into(), vec!["root".into()]);
                s.data["plan"] = json!(p);
                s.data["replans"] = json!(1);
                return Some("validate");
            }
            let p: Plan = serde_json::from_value(s.data["plan"].clone()).unwrap();
            if s.data["done"].as_array().unwrap().len() < p.steps.len() {
                return Some("execute");
            }
        }
        "finish" => s.reject("completed"),
        _ => unreachable!(),
    }
    None
}
// endregion replan
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
    async fn new_member_preserves_root() {
        let s = run("discover").await.unwrap();
        assert_eq!(s.data["done"], json!(["root", "member"]));
        assert_eq!(s.data["plan"]["revision"], 2);
        assert!(s.used > 4);
    }
    #[tokio::test]
    async fn cycle_stops_before_effect() {
        let s = run("cycle").await.unwrap();
        assert_eq!(s.stop, "dependency_cycle");
        assert_eq!(s.data["done"], json!([]));
    }
    #[tokio::test]
    async fn unknown_dependency_is_not_ready() {
        assert_eq!(run("unknown").await.unwrap().stop, "unknown_dependency");
    }
    #[tokio::test]
    async fn no_change_is_not_new_budget() {
        let s = run("repeat").await.unwrap();
        assert_eq!(s.stop, "repeated_plan");
        assert_eq!(s.used, 4);
    }
}
