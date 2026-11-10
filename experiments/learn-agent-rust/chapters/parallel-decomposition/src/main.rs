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
    let mut builder = GraphBuilder::new("D03-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &["dispatch", "merge"];
const SCENARIOS: &[&str] = &[
    "normal",
    "reverse",
    "failure",
    "duplicate",
    "stale",
    "missing",
    "cancel",
    "budget",
];
// region parallel
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Finding {
    id: String,
    revision: u32,
    ok: bool,
}
fn merge(mut values: Vec<Finding>) -> Result<Vec<Finding>, &'static str> {
    values.sort_by(|a, b| a.id.cmp(&b.id));
    if values.iter().map(|v| v.id.as_str()).collect::<Vec<_>>() != ["config", "deps", "docs"] {
        return Err("member_mismatch");
    }
    if values.iter().any(|v| v.revision != 2) {
        return Err("stale_result");
    }
    if values.iter().any(|v| !v.ok) {
        return Err("branch_failed");
    }
    Ok(values)
}
async fn checks(scenario: &str) -> (Vec<Finding>, usize) {
    let semaphore = Arc::new(tokio::sync::Semaphore::new(2));
    let active = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let peak = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let mut tasks = tokio::task::JoinSet::new();
    for (i, id) in ["config", "deps", "docs"].into_iter().enumerate() {
        let (sem, a, p) = (semaphore.clone(), active.clone(), peak.clone());
        let reverse = scenario == "reverse";
        let fail = scenario == "failure" && id == "deps";
        tasks.spawn(async move {
            let _permit = sem.acquire_owned().await.unwrap();
            let now = a.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
            p.fetch_max(now, std::sync::atomic::Ordering::SeqCst);
            tokio::time::sleep(std::time::Duration::from_millis(if reverse {
                (3 - i) * 2
            } else {
                (i + 1) * 2
            } as u64))
            .await;
            a.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
            Finding {
                id: id.into(),
                revision: 2,
                ok: !fail,
            }
        });
    }
    if scenario == "cancel" {
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
        return (vec![], 0);
    }
    let mut values = vec![];
    while let Some(v) = tasks.join_next().await {
        values.push(v.unwrap());
    }
    {
        values.sort_by(|a, b| a.id.cmp(&b.id));
        (values, peak.load(std::sync::atomic::Ordering::SeqCst))
    }
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "dispatch" => {
            if !s.charge(3) {
                return None;
            }
            let (mut results, peak) = checks(&s.scenario).await;
            match s.scenario.as_str() {
                "duplicate" => results.push(results[0].clone()),
                "stale" => results[0].revision = 1,
                "missing" => {
                    results.pop();
                }
                _ => {}
            }
            s.data = json!({"results":results,"peak":peak,"joined":true});
            if s.scenario == "cancel" {
                s.reject("cancelled");
            }
        }
        "merge" => {
            let results: Vec<Finding> = serde_json::from_value(s.data["results"].clone()).unwrap();
            match merge(results) {
                Ok(v) => {
                    s.data["report"] = json!(v);
                    s.reject("completed");
                }
                Err(e) => s.reject(e),
            }
        }
        _ => unreachable!(),
    }
    None
}
// endregion parallel
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
    async fn finish_order_does_not_change_report() {
        assert_eq!(
            run("normal").await.unwrap().data["report"],
            run("reverse").await.unwrap().data["report"]
        );
    }
    #[tokio::test]
    async fn actually_overlaps_and_is_bounded() {
        assert_eq!(run("normal").await.unwrap().data["peak"], 2);
    }
    #[tokio::test]
    async fn failure_does_not_pass() {
        let s = run("failure").await.unwrap();
        assert_eq!(s.stop, "branch_failed");
        assert!(s.data.get("report").is_none());
    }
    #[tokio::test]
    async fn cancellation_joins_children() {
        let s = run("cancel").await.unwrap();
        assert_eq!(s.stop, "cancelled");
        assert_eq!(s.data["joined"], true);
    }
}
