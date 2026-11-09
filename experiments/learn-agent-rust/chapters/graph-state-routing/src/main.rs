use async_trait::async_trait;
use graph_flow::{
    Context, ExecutionStatus, Graph, GraphBuilder, GraphError, NextAction, Session, Task,
    TaskResult,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

// region state
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
struct Review {
    schema: u32,
    draft: u32,
    required: u32,
    repairs: u32,
    max_repairs: u32,
    outcome: Option<String>,
    trace: Vec<String>,
}

fn state(ctx: &Context) -> graph_flow::Result<Review> {
    let value: Review = ctx
        .get("review")
        .ok_or_else(|| GraphError::ContextError("review missing or wrong type".into()))?;
    if value.schema != 1 {
        return Err(GraphError::ContextError("unsupported review schema".into()));
    }
    Ok(value)
}

fn initial(required: u32) -> Review {
    Review {
        schema: 1,
        draft: 0,
        required,
        repairs: 0,
        max_repairs: 2,
        outcome: None,
        trace: vec![],
    }
}
// endregion state

struct Step(&'static str, bool);
// region nodes
#[async_trait]
impl Task for Step {
    fn id(&self) -> &str {
        self.0
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        let mut s = state(&ctx)?;
        s.trace.push(self.0.into());
        let mut next = if self.1 {
            NextAction::ContinueAndExecute
        } else {
            NextAction::Continue
        };
        match self.0 {
            "prepare" => s.draft = 1,
            "check" => {}
            "repair" => {
                if s.repairs >= s.max_repairs {
                    next = NextAction::GoTo("handoff".into());
                } else {
                    s.repairs += 1;
                    s.draft += 1;
                    next = NextAction::GoTo("check".into());
                }
            }
            "accept" => {
                s.outcome = Some("accepted".into());
                next = NextAction::End;
            }
            "handoff" => {
                s.outcome = Some("needs_human".into());
                next = NextAction::End;
            }
            _ => return Err(GraphError::TaskNotFound(self.0.into())),
        }
        ctx.set("review", s)?;
        Ok(TaskResult::new(None, next))
    }
}
// endregion nodes

// region graph
fn graph(automatic: bool) -> graph_flow::Result<Graph> {
    let mut builder = GraphBuilder::new("review-v1").with_max_execution_steps(8);
    for name in ["prepare", "check", "repair", "accept", "handoff"] {
        builder = builder.add_task(Arc::new(Step(name, automatic)));
    }
    builder
        .add_edge("prepare", "check")
        .add_conditional_edge(
            "check",
            |ctx| {
                // Invalid state fails closed at the next typed node; it never grants acceptance.
                state(ctx).is_ok_and(|s| s.draft >= s.required)
            },
            "accept",
            "repair",
        )
        .set_start_task("prepare")
        .build()
}

async fn drive(graph: &Graph, session: &mut Session) -> graph_flow::Result<usize> {
    // A host limit covers GoTo/Continue across calls as well as graph-internal chains.
    for call in 1..=16 {
        let before = session.current_task_id.clone();
        let result = graph.execute_session(session).await?;
        let status = match result.status {
            ExecutionStatus::Completed => "completed",
            ExecutionStatus::Paused { .. } => "paused",
            ExecutionStatus::WaitingForInput => {
                return Err(GraphError::ContextError("unexpected input wait".into()));
            }
        };
        println!(
            "call={call} before={before} after={} status={status}",
            session.current_task_id
        );
        if status == "completed" {
            return Ok(call);
        }
    }
    Err(GraphError::TaskExecutionFailed("host step budget".into()))
}
// endregion graph

struct Action(&'static str, NextAction);
#[async_trait]
impl Task for Action {
    fn id(&self) -> &str {
        self.0
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        ctx.set("touched", true)?;
        Ok(TaskResult::new(None, self.1.clone()))
    }
}

// region probes
async fn probes() -> graph_flow::Result<()> {
    let invalid = GraphBuilder::new("bad")
        .add_task(Arc::new(Action("a", NextAction::End)))
        .add_edge("a", "missing")
        .build();
    assert!(matches!(invalid, Err(GraphError::InvalidEdge(_))));
    println!("probe=dangling_edge rejected=true");
    let missing_start = GraphBuilder::new("bad")
        .add_task(Arc::new(Action("a", NextAction::End)))
        .set_start_task("unknown")
        .build();
    assert!(matches!(missing_start, Err(GraphError::TaskNotFound(_))));
    println!("probe=missing_start rejected=true");
    let orphan = GraphBuilder::new("orphan")
        .add_task(Arc::new(Action("a", NextAction::Continue)))
        .build()?;
    let mut s = Session::new_from_task("s".into(), "a");
    assert!(matches!(
        orphan.execute_session(&mut s).await?.status,
        ExecutionStatus::Paused { .. }
    ));
    assert_eq!(s.current_task_id, "a");
    println!("probe=no_edge status=paused cursor=a");
    let jump = GraphBuilder::new("jump")
        .add_task(Arc::new(Action("a", NextAction::GoTo("missing".into()))))
        .build()?;
    assert!(matches!(
        jump.execute_session(&mut s).await,
        Err(GraphError::TaskNotFound(_))
    ));
    println!(
        "probe=bad_goto rejected=true mutation_retained={}",
        s.context.get::<bool>("touched") == Some(true)
    );
    let cycle = GraphBuilder::new("cycle")
        .add_task(Arc::new(Action("a", NextAction::ContinueAndExecute)))
        .add_edge("a", "a")
        .with_max_execution_steps(2)
        .build()?;
    assert!(cycle.execute_session(&mut s).await.is_err());
    println!("probe=cycle chained_limit_rejected=true");
    let priority = GraphBuilder::new("priority")
        .add_task(Arc::new(Action("a", NextAction::Continue)))
        .add_task(Arc::new(Action("b", NextAction::End)))
        .add_task(Arc::new(Action("c", NextAction::End)))
        .add_conditional_edge("a", |_| true, "b", "c")
        .add_conditional_edge("a", |_| true, "c", "b")
        .build()?;
    assert_eq!(
        priority.find_next_task("a", &Context::new()).as_deref(),
        Some("b")
    );
    println!("probe=overlapping_conditions first_matching=b");
    let ctx = Context::new();
    ctx.set("count", 1_u32)?;
    let clone = ctx.clone();
    clone.set("count", 2_u32)?;
    assert_eq!(ctx.get::<u32>("count"), Some(2));
    let snapshot: Context = serde_json::from_value(serde_json::to_value(&ctx).unwrap()).unwrap();
    snapshot.set("count", 3_u32)?;
    assert_eq!(ctx.get::<u32>("count"), Some(2));
    println!("probe=context clone_shares=true serialized_snapshot_isolated=true");
    let g = graph(false)?;
    let mut malformed = Session::new_from_task("bad".into(), "prepare");
    malformed.context.set("review", "wrong type")?;
    assert!(g.execute_session(&mut malformed).await.is_err());
    println!("probe=typed_state malformed_rejected=true");
    Ok(())
}
// endregion probes

async fn run(scenario: &str) -> graph_flow::Result<()> {
    if scenario == "probes" {
        return probes().await;
    }
    let (required, automatic) = match scenario {
        "normal" => (2, false),
        "direct" => (2, true),
        "exhausted" => (9, false),
        _ => return Err(GraphError::ContextError("unknown scenario".into())),
    };
    let g = graph(automatic)?;
    let mut session = Session::new_from_task("review".into(), g.start_task_id().unwrap())
        .with_graph_id("review-v1");
    session.context.set("review", initial(required))?;
    let calls = drive(&g, &mut session).await?;
    let s = state(&session.context)?;
    println!(
        "scenario={scenario} outcome={} repairs={} calls={calls}",
        s.outcome.as_deref().unwrap(),
        s.repairs
    );
    println!("trace={}", s.trace.join(">"));
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let scenario = std::env::args().nth(1).unwrap_or_else(|| "normal".into());
    if let Err(e) = run(&scenario).await {
        eprintln!("{e}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn normal_and_direct_have_identical_business_state() {
        let mut a = Session::new_from_task("a".into(), "prepare");
        let mut b = Session::new_from_task("b".into(), "prepare");
        a.context.set("review", initial(2)).unwrap();
        b.context.set("review", initial(2)).unwrap();
        drive(&graph(false).unwrap(), &mut a).await.unwrap();
        drive(&graph(true).unwrap(), &mut b).await.unwrap();
        assert_eq!(state(&a.context).unwrap(), state(&b.context).unwrap());
    }
    #[tokio::test]
    async fn repair_budget_hands_off() {
        let mut s = Session::new_from_task("a".into(), "prepare");
        s.context.set("review", initial(99)).unwrap();
        drive(&graph(false).unwrap(), &mut s).await.unwrap();
        let result = state(&s.context).unwrap();
        assert_eq!(result.repairs, 2);
        assert_eq!(result.outcome.as_deref(), Some("needs_human"));
    }
    #[tokio::test]
    async fn framework_edge_cases_are_explicit() {
        probes().await.unwrap();
    }
    #[test]
    fn missing_and_wrong_schema_fail_closed() {
        let c = Context::new();
        assert!(state(&c).is_err());
        let mut s = initial(2);
        s.schema = 9;
        c.set("review", s).unwrap();
        assert!(state(&c).is_err());
    }
}
