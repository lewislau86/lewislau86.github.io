use async_trait::async_trait;
use graph_flow::{
    Context, ExecutionStatus, FanOutTask, Graph, GraphBuilder, GraphError, NextAction, Session,
    Task, TaskResult,
};
use std::sync::Arc;
use tokio::sync::Barrier;
fn error(s: &str) -> GraphError {
    GraphError::TaskExecutionFailed(s.into())
}

// region worker
struct Check {
    id: &'static str,
    fail: bool,
    barrier: Arc<Barrier>,
    overwrite: Option<u32>,
}
#[async_trait]
impl Task for Check {
    fn id(&self) -> &str {
        self.id
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        // The barrier proves both tasks are active; it does not measure speed.
        let previous = ctx.get::<u32>("shared_counter").unwrap_or(0);
        self.barrier.wait().await;
        if let Some(value) = self.overwrite {
            ctx.set("shared_counter", previous + value)?;
        }
        ctx.set(format!("observed.{}", self.id), true)?;
        if self.fail {
            return Err(error("injected check failure"));
        }
        Ok(TaskResult::new(
            Some(format!("{}:pass", self.id)),
            NextAction::End,
        ))
    }
}

fn fan(fail: bool, collide: bool) -> Arc<FanOutTask> {
    let barrier = Arc::new(Barrier::new(2));
    let children: Vec<Arc<dyn Task>> = ["compatibility", "tests"]
        .iter()
        .enumerate()
        .map(|(i, id)| {
            Arc::new(Check {
                id,
                fail: fail && i == 1,
                barrier: barrier.clone(),
                overwrite: collide.then_some(1),
            }) as Arc<dyn Task>
        })
        .collect();
    FanOutTask::new("checks", children).with_prefix("checks")
}
// endregion worker

struct Merge;
// region merge
#[async_trait]
impl Task for Merge {
    fn id(&self) -> &str {
        "merge"
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        let mut outputs = Vec::new();
        // Membership and order are application contracts, independent of finish order.
        for id in ["compatibility", "tests"] {
            let value = ctx
                .get::<String>(&format!("checks.{id}.response"))
                .ok_or_else(|| error("incomplete check set"))?;
            outputs.push(value);
        }
        ctx.set("report", outputs.join(" | "))?;
        Ok(TaskResult::new(None, NextAction::End))
    }
}
fn graph(fail: bool, collide: bool) -> graph_flow::Result<Graph> {
    GraphBuilder::new("parallel-v1")
        .add_task(fan(fail, collide))
        .add_task(Arc::new(Merge))
        .add_edge("checks", "merge")
        .with_task_timeout(std::time::Duration::from_secs(2))
        .build()
}
// endregion merge

struct Upper;
#[async_trait]
impl Task for Upper {
    fn id(&self) -> &str {
        "upper"
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        let input = ctx
            .get::<String>("input")
            .ok_or_else(|| error("missing child input"))?;
        ctx.set("output", input.to_uppercase())?;
        ctx.set("child_private", "scratch")?;
        Ok(TaskResult::new(None, NextAction::End))
    }
}

// region subgraph
struct ChildGraph {
    graph: Arc<Graph>,
}
#[async_trait]
impl Task for ChildGraph {
    fn id(&self) -> &str {
        "review_subgraph"
    }
    async fn run(&self, parent: Context) -> graph_flow::Result<TaskResult> {
        // New Session => new Context. Only explicit inputs and outputs cross the boundary.
        let mut child = Session::new_from_task("child".into(), "upper");
        child.context.set(
            "input",
            parent
                .get::<String>("request")
                .ok_or_else(|| error("missing request"))?,
        )?;
        for _ in 0..4 {
            match self.graph.execute_session(&mut child).await?.status {
                ExecutionStatus::Completed => {
                    let result = child
                        .context
                        .get::<String>("output")
                        .ok_or_else(|| error("missing child output"))?;
                    parent.set("subgraph_result", result)?;
                    parent.set(
                        "child_private_exported",
                        parent.get::<String>("child_private").is_some(),
                    )?;
                    return Ok(TaskResult::new(None, NextAction::End));
                }
                ExecutionStatus::WaitingForInput => {
                    return Err(error("child wait requires a parent resume contract"));
                }
                ExecutionStatus::Paused { .. } => {}
            }
        }
        Err(error("child step budget"))
    }
}
// endregion subgraph

struct Never;
#[async_trait]
impl Task for Never {
    fn id(&self) -> &str {
        "never"
    }
    async fn run(&self, _: Context) -> graph_flow::Result<TaskResult> {
        std::future::pending().await
    }
}

async fn run(scenario: &str) -> graph_flow::Result<()> {
    match scenario {
        "normal" | "failure" | "collision" => {
            let g = graph(scenario == "failure", scenario == "collision")?;
            let mut s = Session::new_from_task("s".into(), "checks");
            let result = g.execute_session(&mut s).await;
            if scenario == "failure" {
                assert!(result.is_err());
                assert!(
                    s.context
                        .get::<String>("checks.compatibility.response")
                        .is_some()
                );
                assert!(s.context.get::<String>("report").is_none());
                println!(
                    "scenario=failure parent_error=true sibling_result_retained=true merge_ran=false cursor={}",
                    s.current_task_id
                );
            } else {
                assert!(matches!(result?.status, ExecutionStatus::Paused { .. }));
                assert_eq!(s.current_task_id, "merge");
                assert!(matches!(
                    g.execute_session(&mut s).await?.status,
                    ExecutionStatus::Completed
                ));
                assert_eq!(
                    s.context
                        .get::<String>("checks.compatibility.next_action")
                        .as_deref(),
                    Some("End")
                );
                println!(
                    "scenario={scenario} child_end_ignored=true both_started=true report={}",
                    s.context.get::<String>("report").unwrap()
                );
                if scenario == "collision" {
                    assert_eq!(s.context.get::<u32>("shared_counter"), Some(1));
                    println!("shared_counter=1 expected_sum=2 lost_update=true");
                }
            }
        }
        "subgraph" => {
            let child = Arc::new(
                GraphBuilder::new("child")
                    .add_task(Arc::new(Upper))
                    .build()?,
            );
            let parent = GraphBuilder::new("parent")
                .add_task(Arc::new(ChildGraph { graph: child }))
                .build()?;
            let mut s = Session::new_from_task("parent".into(), "review_subgraph");
            s.context.set("request", "upgrade")?;
            s.context.set("parent_private", "secret")?;
            parent.execute_session(&mut s).await?;
            assert_eq!(
                s.context.get::<String>("subgraph_result").as_deref(),
                Some("UPGRADE")
            );
            assert_eq!(s.context.get::<bool>("child_private_exported"), Some(false));
            println!(
                "scenario=subgraph result=UPGRADE child_scratch_exported=false explicit_contract=true"
            );
        }
        "timeout" => {
            let g = GraphBuilder::new("timeout")
                .add_task(Arc::new(Never))
                .with_task_timeout(std::time::Duration::from_millis(10))
                .build()?;
            let mut s = Session::new_from_task("s".into(), "never");
            let e = g.execute_session(&mut s).await.unwrap_err();
            assert!(e.to_string().contains("timed out"));
            println!(
                "scenario=timeout graph_task_timeout=true cursor={}",
                s.current_task_id
            );
        }
        _ => return Err(error("unknown scenario")),
    }
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
    async fn parallel_success_and_child_actions() {
        run("normal").await.unwrap();
    }
    #[tokio::test]
    async fn failed_child_keeps_sibling_data() {
        run("failure").await.unwrap();
    }
    #[tokio::test]
    async fn shared_read_modify_write_loses_update() {
        run("collision").await.unwrap();
    }
    #[tokio::test]
    async fn private_child_context() {
        run("subgraph").await.unwrap();
    }
    #[tokio::test]
    async fn real_task_timeout() {
        run("timeout").await.unwrap();
    }
    #[tokio::test]
    async fn merge_rejects_incomplete_set() {
        assert!(Merge.run(Context::new()).await.is_err());
    }
}
