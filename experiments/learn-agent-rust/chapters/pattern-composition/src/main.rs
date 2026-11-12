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
    let mut builder = GraphBuilder::new("D08-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &[
    "route", "plan", "parallel", "merge", "generate", "evaluate", "repair", "approve", "publish",
];
const SCENARIOS: &[&str] = &[
    "normal",
    "discover",
    "branch_failed",
    "stale_branch",
    "missing_branch",
    "stale_approval",
    "denied",
    "no_progress",
    "budget",
];
// region composition
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Evidence {
    member: String,
    revision: u32,
    source: String,
    ok: bool,
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "route" => {
            s.data = json!({"revision":2,"members":["root"],"repairs":0,"effects":0,"report_revision":0,"sources":[]})
        }
        "plan" => {
            if s.scenario == "discover" {
                s.data["members"] = json!(["root", "member"]);
            }
            s.data["plan_revision"] = json!(if s.scenario == "discover" { 2 } else { 1 });
        }
        "parallel" => {
            if !s.charge(s.data["members"].as_array().unwrap().len() as u32) {
                return None;
            }
            let mut tasks = tokio::task::JoinSet::new();
            for id in s.data["members"].as_array().unwrap() {
                let member = id.as_str().unwrap().to_owned();
                let ok = s.scenario != "branch_failed" || member != "root";
                tasks.spawn(async move {
                    Evidence {
                        source: format!("{member}/README.md"),
                        member,
                        revision: 2,
                        ok,
                    }
                });
            }
            let mut results = vec![];
            while let Some(v) = tasks.join_next().await {
                results.push(v.unwrap());
            }
            results.sort_by(|a, b| a.member.cmp(&b.member));
            if s.scenario == "stale_branch" {
                results[0].revision = 1;
            }
            if s.scenario == "missing_branch" {
                results.pop();
            }
            s.data["results"] = json!(results);
            s.data["joined"] = json!(true);
        }
        "merge" => {
            let results: Vec<Evidence> = serde_json::from_value(s.data["results"].clone()).unwrap();
            let mut expected = s.data["members"].as_array().unwrap().clone();
            expected.sort_by_key(|x| x.as_str().unwrap().to_owned());
            if results.iter().map(|r| json!(r.member)).collect::<Vec<_>>() != expected {
                s.reject("member_mismatch");
            } else if results.iter().any(|r| r.revision != 2) {
                s.reject("stale_result");
            } else if results.iter().any(|r| !r.ok) {
                s.reject("branch_failed");
            } else {
                s.data["evidence"] =
                    json!(results.iter().map(|r| r.source.clone()).collect::<Vec<_>>());
            }
        }
        "generate" => {
            s.data["report"] = json!("upgrade report");
            s.data["report_revision"] = json!(1);
        }
        "evaluate" => {
            if s.data["sources"] == s.data["evidence"] {
                return Some("approve");
            }
            if s.data["repairs"].as_u64().unwrap() >= 1 {
                s.reject("no_progress");
                return None;
            }
            s.data["feedback_revision"] = s.data["report_revision"].clone();
        }
        "repair" => {
            if s.data["feedback_revision"] != s.data["report_revision"] {
                s.reject("stale_feedback");
                return None;
            }
            if s.scenario != "no_progress" {
                s.data["sources"] = s.data["evidence"].clone();
            }
            s.data["report_revision"] = json!(2);
            s.data["repairs"] = json!(1);
            return Some("evaluate");
        }
        "approve" => {
            if s.scenario == "denied" {
                s.reject("denied");
                return None;
            }
            s.data["approved_revision"] = json!(if s.scenario == "stale_approval" { 1 } else { 2 });
        }
        "publish" => {
            if s.data["approved_revision"] != s.data["report_revision"] {
                s.reject("stale_approval");
                return None;
            }
            s.data["effects"] = json!(1);
            s.reject("completed");
        }
        _ => unreachable!(),
    }
    None
}
// endregion composition
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
            Ok(s) => {
                if let Some(path) = args.get(1)
                    && s.stop == "completed"
                {
                    use std::io::Write;
                    let mut file = std::fs::OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .open(path)
                        .expect("new artifact path required");
                    file.write_all(serde_json::to_string(&s.data).unwrap().as_bytes())
                        .unwrap();
                    file.sync_all().unwrap();
                }
                println!("{}", serde_json::to_string(&s).unwrap());
            }
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
    async fn full_composition() {
        let s = run("discover").await.unwrap();
        assert_eq!(s.stop, "completed");
        assert_eq!(s.data["effects"], 1);
        assert_eq!(s.data["sources"].as_array().unwrap().len(), 2);
        assert!(s.used > 10);
    }
    #[tokio::test]
    async fn old_branch_cannot_publish() {
        let s = run("stale_branch").await.unwrap();
        assert_eq!(s.stop, "stale_result");
        assert_eq!(s.data["effects"], 0);
    }
    #[tokio::test]
    async fn repair_invalidates_old_approval() {
        let s = run("stale_approval").await.unwrap();
        assert_eq!(s.stop, "stale_approval");
        assert_eq!(s.data["effects"], 0);
    }
    #[tokio::test]
    async fn nested_work_uses_global_limit() {
        let s = run("budget").await.unwrap();
        assert_eq!(s.used, 1);
        assert_eq!(s.stop, "budget_exhausted");
        assert_eq!(s.data["effects"], 0);
    }
}
