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
    let mut builder = GraphBuilder::new("D05-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &["decompose", "workers", "handoff", "return"];
const SCENARIOS: &[&str] = &[
    "normal",
    "three",
    "failed_worker",
    "invalid_role",
    "stale",
    "depth",
    "budget",
];
// region handoff
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Handoff {
    id: u32,
    revision: u32,
    from: String,
    to: String,
    allowed: Vec<String>,
}
fn transfer(active: &str, h: &Handoff) -> Result<String, &'static str> {
    if h.revision != 2 {
        return Err("stale_handoff");
    }
    if active != h.from {
        return Err("wrong_controller");
    }
    if h.to != "license" || h.allowed != ["read"] {
        return Err("invalid_role_or_permission");
    }
    Ok(h.to.clone())
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "decompose" => {
            s.data = json!({"controller":"technical","input_revision":2,"tasks":[],"results":[]});
            if s.scenario == "depth" {
                s.reject("delegation_depth");
                return None;
            }
            let members = if s.scenario == "three" {
                vec!["api", "cli", "core"]
            } else {
                vec!["api", "cli"]
            };
            s.data["tasks"] = json!(members);
        }
        "workers" => {
            if !s.charge(s.data["tasks"].as_array().unwrap().len() as u32) {
                return None;
            }
            let mut tasks = tokio::task::JoinSet::new();
            for id in s.data["tasks"].as_array().unwrap() {
                let id = id.as_str().unwrap().to_owned();
                let fail = s.scenario == "failed_worker" && id == "cli";
                tasks.spawn(async move{let private_history=[format!("read:{id}")];json!({"id":id,"ok":!fail,"private_messages":private_history.len(),"revision":2})});
            }
            let mut results = vec![];
            while let Some(result) = tasks.join_next().await {
                results.push(result.unwrap());
            }
            results.sort_by_key(|x| x["id"].as_str().unwrap().to_owned());
            let ok = results.iter().all(|x| x["ok"] == true);
            s.data["results"] = json!(results);
            s.data["joined"] = json!(true);
            if !ok {
                s.reject("worker_failed");
            }
        }
        "handoff" => {
            let h = Handoff {
                id: 1,
                revision: if s.scenario == "stale" { 1 } else { 2 },
                from: "technical".into(),
                to: if s.scenario == "invalid_role" {
                    "admin"
                } else {
                    "license"
                }
                .into(),
                allowed: vec!["read".into()],
            };
            match transfer(s.data["controller"].as_str().unwrap(), &h) {
                Ok(role) => {
                    s.data["controller"] = json!(role);
                    s.data["handoff"] = json!(h);
                }
                Err(e) => s.reject(e),
            }
        }
        "return" => {
            s.data["returned_from"] = s.data["controller"].clone();
            s.data["controller"] = json!("technical");
            s.reject("completed");
        }
        _ => unreachable!(),
    }
    None
}
// endregion handoff
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
    async fn input_changes_number_of_workers() {
        assert_eq!(
            run("three").await.unwrap().data["results"]
                .as_array()
                .unwrap()
                .len(),
            3
        );
    }
    #[tokio::test]
    async fn child_failure_keeps_parent() {
        let s = run("failed_worker").await.unwrap();
        assert_eq!(s.data["controller"], "technical");
        assert_eq!(s.stop, "worker_failed");
    }
    #[tokio::test]
    async fn handoff_returns_explicitly() {
        let s = run("normal").await.unwrap();
        assert_eq!(s.data["returned_from"], "license");
        assert_eq!(s.data["controller"], "technical");
    }
    #[test]
    fn no_permission_escalation() {
        let h = Handoff {
            id: 1,
            revision: 2,
            from: "technical".into(),
            to: "license".into(),
            allowed: vec!["write".into()],
        };
        assert!(transfer("technical", &h).is_err());
    }
}
