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
    let mut builder = GraphBuilder::new("D07-v1").with_max_execution_steps(32);
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

const NODES: &[&str] = &["prepare", "intervene", "resume", "finish"];
const SCENARIOS: &[&str] = &[
    "approve",
    "clarify",
    "edit",
    "deny",
    "stale",
    "duplicate",
    "budget",
];
// region approval
#[derive(Clone, Debug, Serialize, Deserialize)]
struct Request {
    id: u32,
    revision: u32,
    content: String,
    approved: Option<u32>,
    denied: bool,
    completed: bool,
}
fn decision(r: &mut Request, id: u32, revision: u32, yes: bool) -> Result<(), &'static str> {
    if r.id != id {
        return Err("unknown_request");
    }
    if r.revision != revision {
        return Err("stale_approval");
    }
    if r.approved.is_some() || r.denied || r.completed {
        return Err("duplicate_decision");
    }
    if yes {
        r.approved = Some(revision);
    } else {
        r.denied = true;
    }
    Ok(())
}
fn edit(r: &mut Request, content: &str) {
    r.content = content.into();
    r.revision += 1;
    r.approved = None;
}
fn resume(r: &mut Request) -> Result<(), &'static str> {
    if r.completed {
        return Err("already_completed");
    }
    if r.denied {
        return Err("denied");
    }
    if r.approved != Some(r.revision) {
        return Err("needs_approval");
    }
    r.completed = true;
    Ok(())
}
async fn step(node: &str, s: &mut State) -> Option<&'static str> {
    match node {
        "prepare" => {
            s.data = json!({"request":Request{id:1,revision:1,content:"upgrade report".into(),approved:None,denied:false,completed:false},"effects":0})
        }
        "intervene" => {
            let mut r: Request = serde_json::from_value(s.data["request"].clone()).unwrap();
            let result = match s.scenario.as_str() {
                "clarify" => {
                    edit(&mut r, "target=v2; upgrade report");
                    Ok(())
                }
                "edit" => {
                    decision(&mut r, 1, 1, true).unwrap();
                    edit(&mut r, "edited report");
                    Ok(())
                }
                "stale" => decision(&mut r, 1, 0, true),
                "duplicate" => {
                    decision(&mut r, 1, 1, true).unwrap();
                    decision(&mut r, 1, 1, true)
                }
                "deny" => decision(&mut r, 1, 1, false),
                _ => decision(&mut r, 1, 1, true),
            };
            s.data["request"] = json!(r);
            if let Err(e) = result {
                s.reject(e);
            }
        }
        "resume" => {
            let mut r: Request = serde_json::from_value(s.data["request"].clone()).unwrap();
            match resume(&mut r) {
                Ok(()) => s.data["effects"] = json!(1),
                Err(e) => s.reject(e),
            }
            s.data["request"] = json!(r);
        }
        "finish" => s.reject("completed"),
        _ => unreachable!(),
    }
    None
}
// endregion approval
// region persistence
fn disk(args: &[String]) -> Result<(), Box<dyn std::error::Error>> {
    let path = std::path::Path::new(&args[1]);
    let action = args[2].as_str();
    let mut r = if action == "init" {
        if path.exists() {
            return Err("request already exists".into());
        }
        Request {
            id: 1,
            revision: 1,
            content: "upgrade report".into(),
            approved: None,
            denied: false,
            completed: false,
        }
    } else {
        serde_json::from_slice::<Request>(&std::fs::read(path)?)?
    };
    match action {
        "init" | "show" => {}
        "approve" | "deny" => decision(
            &mut r,
            args.get(3).ok_or("id required")?.parse()?,
            args.get(4).ok_or("revision required")?.parse()?,
            action == "approve",
        )?,
        "edit" => {
            if r.completed || r.denied {
                return Err("terminal request".into());
            }
            edit(&mut r, args.get(3).ok_or("content required")?);
        }
        "resume" => resume(&mut r)?,
        _ => return Err("unknown action".into()),
    }
    if action != "show" {
        let tmp = path.with_extension("tmp");
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&tmp)?;
        use std::io::Write;
        file.write_all(&serde_json::to_vec(&r)?)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(tmp, path)?;
    }
    println!("{}", serde_json::to_string(&r)?);
    Ok(())
}
// endregion persistence
#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|x| x == "disk") {
        if args.len() < 3 {
            eprintln!("disk PATH ACTION [ARGS]");
            std::process::exit(2);
        }
        if let Err(e) = disk(&args) {
            eprintln!("{e}");
            std::process::exit(2);
        }
        return;
    }
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
    async fn edit_invalidates_approval() {
        let s = run("edit").await.unwrap();
        assert_eq!(s.stop, "needs_approval");
        assert_eq!(s.data["effects"], 0);
    }
    #[tokio::test]
    async fn clarification_is_not_approval() {
        assert_eq!(run("clarify").await.unwrap().stop, "needs_approval");
    }
    #[test]
    fn unknown_identity_refused() {
        let mut r = Request {
            id: 1,
            revision: 1,
            content: "x".into(),
            approved: None,
            denied: false,
            completed: false,
        };
        assert_eq!(decision(&mut r, 2, 1, true), Err("unknown_request"));
    }
    #[test]
    fn terminal_cannot_replay() {
        let mut r = Request {
            id: 1,
            revision: 1,
            content: "x".into(),
            approved: Some(1),
            denied: false,
            completed: false,
        };
        assert!(resume(&mut r).is_ok());
        assert_eq!(resume(&mut r), Err("already_completed"));
    }
}
