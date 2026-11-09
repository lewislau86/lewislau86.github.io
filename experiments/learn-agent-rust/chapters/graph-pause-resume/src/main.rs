use async_trait::async_trait;
use graph_flow::{
    Context, ExecutionStatus, FlowRunner, Graph, GraphBuilder, GraphError, NextAction, Session,
    SessionStorage, Task, TaskResult,
};
use rusqlite::{Connection, OptionalExtension, params};
use std::{path::PathBuf, sync::Arc};

const GRAPH: &str = "release-review-v1";
const SID: &str = "review";
fn error(e: impl std::fmt::Display) -> GraphError {
    GraphError::StorageError(e.to_string())
}

// region storage
struct SqliteSessions(PathBuf);
impl SqliteSessions {
    fn open(&self) -> graph_flow::Result<Connection> {
        let db = Connection::open(&self.0).map_err(error)?;
        db.busy_timeout(std::time::Duration::from_secs(2))
            .map_err(error)?;
        db.execute_batch("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, version INTEGER NOT NULL, body TEXT NOT NULL)").map_err(error)?;
        Ok(db)
    }
}

#[async_trait]
impl SessionStorage for SqliteSessions {
    async fn save(&self, mut session: Session) -> graph_flow::Result<()> {
        let mut db = self.open()?;
        let tx = db
            .transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)
            .map_err(error)?;
        let version: Option<u64> = tx
            .query_row(
                "SELECT version FROM sessions WHERE id=?1",
                [&session.id],
                |r| r.get(0),
            )
            .optional()
            .map_err(error)?;
        if version.is_some_and(|v| v != session.version)
            || (version.is_none() && session.version != 0)
        {
            return Err(GraphError::SessionConflict(session.id));
        }
        session.version += 1;
        let body = serde_json::to_string(&session).map_err(error)?;
        tx.execute("INSERT INTO sessions(id,version,body) VALUES (?1,?2,?3) ON CONFLICT(id) DO UPDATE SET version=excluded.version,body=excluded.body", params![session.id,session.version,body]).map_err(error)?;
        tx.commit().map_err(error)?;
        Ok(())
    }
    async fn get(&self, id: &str) -> graph_flow::Result<Option<Session>> {
        let db = self.open()?;
        let row: Option<(u64, String)> = db
            .query_row("SELECT version,body FROM sessions WHERE id=?1", [id], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .optional()
            .map_err(error)?;
        row.map(|(version, body)| {
            let s: Session = serde_json::from_str(&body).map_err(error)?;
            if s.id != id || s.version != version {
                return Err(error("row/body identity mismatch"));
            }
            Ok(s)
        })
        .transpose()
    }
    async fn delete(&self, id: &str) -> graph_flow::Result<()> {
        self.open()?
            .execute("DELETE FROM sessions WHERE id=?1", [id])
            .map_err(error)?;
        Ok(())
    }
}
// endregion storage

struct Node(&'static str);
// region approval
#[async_trait]
impl Task for Node {
    fn id(&self) -> &str {
        self.0
    }
    async fn run(&self, ctx: Context) -> graph_flow::Result<TaskResult> {
        let visits = ctx.get::<u32>(&format!("visits.{}", self.0)).unwrap_or(0) + 1;
        ctx.set(format!("visits.{}", self.0), visits)?;
        let next = match self.0 {
            "draft" => {
                ctx.set("revision", 1_u32)?;
                ctx.set("proposal", "produce upgrade report")?;
                NextAction::Continue
            }
            "approve" => {
                let revision = ctx
                    .get::<u32>("revision")
                    .ok_or_else(|| error("revision missing"))?;
                if let Some(decision) = ctx.get::<bool>("decision") {
                    if ctx.get::<u32>("approved_revision") != Some(revision) {
                        return Err(error("stale approval"));
                    }
                    NextAction::GoTo(if decision { "render" } else { "reject" }.into())
                } else {
                    NextAction::WaitForInput
                }
            }
            "render" => {
                ctx.set("report", "upgrade report: review complete")?;
                ctx.set("terminal", true)?;
                NextAction::End
            }
            "reject" => {
                ctx.set("terminal", true)?;
                NextAction::End
            }
            _ => return Err(GraphError::TaskNotFound(self.0.into())),
        };
        Ok(TaskResult::new(None, next))
    }
}

fn graph() -> graph_flow::Result<Graph> {
    let mut g = GraphBuilder::new(GRAPH);
    for id in ["draft", "approve", "render", "reject"] {
        g = g.add_task(Arc::new(Node(id)));
    }
    g.add_edge("draft", "approve")
        .set_start_task("draft")
        .build()
}

async fn checked(storage: &SqliteSessions) -> graph_flow::Result<Session> {
    let s = storage
        .get(SID)
        .await?
        .ok_or_else(|| GraphError::SessionNotFound(SID.into()))?;
    if s.graph_id != GRAPH || s.context.get::<u32>("schema") != Some(1) {
        return Err(error("incompatible graph/schema"));
    }
    if !["draft", "approve", "render", "reject"].contains(&s.current_task_id.as_str()) {
        return Err(error("unknown saved cursor"));
    }
    Ok(s)
}

async fn submit(storage: &SqliteSessions, revision: u32, decision: bool) -> graph_flow::Result<()> {
    let s = checked(storage).await?;
    if s.current_task_id != "approve" || s.context.get::<bool>("terminal") == Some(true) {
        return Err(error("not waiting for approval"));
    }
    if s.context.get::<u32>("revision") != Some(revision) {
        return Err(error("stale approval"));
    }
    if s.context.get::<bool>("decision").is_some() {
        return Err(error("decision already submitted"));
    }
    s.context.set("decision", decision)?;
    s.context.set("approved_revision", revision)?;
    storage.save(s).await
}
// endregion approval

// region runner
async fn step(storage: Arc<SqliteSessions>) -> graph_flow::Result<()> {
    let s = checked(&storage).await?;
    if s.context.get::<bool>("terminal") == Some(true) {
        println!(
            "status=already_completed cursor={} version={}",
            s.current_task_id, s.version
        );
        return Ok(());
    }
    let runner = FlowRunner::new(Arc::new(graph()?), storage.clone());
    let result = runner.run(SID).await?;
    let s = checked(&storage).await?;
    let status = match result.status {
        ExecutionStatus::Paused { .. } => "paused",
        ExecutionStatus::WaitingForInput => "waiting",
        ExecutionStatus::Completed => "completed",
    };
    println!(
        "status={status} cursor={} version={} approval_visits={} report={}",
        s.current_task_id,
        s.version,
        s.context.get::<u32>("visits.approve").unwrap_or(0),
        s.context.get::<String>("report").is_some()
    );
    Ok(())
}
// endregion runner

async fn run(args: &[String]) -> graph_flow::Result<()> {
    if args.len() < 3 {
        return Err(error(
            "usage: graph-resume-lab DB init|step|show|approve REV yes|no|conflict",
        ));
    }
    let storage = Arc::new(SqliteSessions(PathBuf::from(&args[1])));
    match args[2].as_str() {
        "init" => {
            if storage.get(SID).await?.is_some() {
                return Err(error("session exists"));
            }
            let s = Session::new_from_task(SID.into(), "draft").with_graph_id(GRAPH);
            s.context.set("schema", 1_u32)?;
            storage.save(s).await?;
            println!("status=initialized version=1");
        }
        "step" => step(storage.clone()).await?,
        "approve" if args.len() == 5 => {
            let revision = args[3].parse().map_err(error)?;
            let decision = match args[4].as_str() {
                "yes" => true,
                "no" => false,
                _ => return Err(error("expected yes|no")),
            };
            submit(&storage, revision, decision).await?;
            println!("status=decision_saved revision={revision} accepted={decision}");
        }
        "show" => {
            let s = checked(&storage).await?;
            println!(
                "cursor={} version={} draft_visits={} approval_visits={} render_visits={} report={}",
                s.current_task_id,
                s.version,
                s.context.get::<u32>("visits.draft").unwrap_or(0),
                s.context.get::<u32>("visits.approve").unwrap_or(0),
                s.context.get::<u32>("visits.render").unwrap_or(0),
                s.context
                    .get::<String>("report")
                    .unwrap_or_else(|| "none".into())
            );
        }
        "conflict" => {
            let first = checked(&storage).await?;
            let stale = checked(&storage).await?;
            storage.save(first).await?;
            assert!(matches!(
                storage.save(stale).await,
                Err(GraphError::SessionConflict(_))
            ));
            println!("conflict=stale_writer_rejected");
        }
        _ => return Err(error("unknown command")),
    }
    Ok(())
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    if let Err(e) = run(&std::env::args().collect::<Vec<_>>()).await {
        eprintln!("{e}");
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn waiting_reexecutes_same_node() {
        let mut s = Session::new_from_task("s".into(), "approve");
        s.context.set("revision", 1_u32).unwrap();
        let g = graph().unwrap();
        for _ in 0..2 {
            assert!(matches!(
                g.execute_session(&mut s).await.unwrap().status,
                ExecutionStatus::WaitingForInput
            ));
        }
        assert_eq!(s.context.get::<u32>("visits.approve"), Some(2));
        assert_eq!(s.current_task_id, "approve");
    }
    #[tokio::test]
    async fn stale_revision_cannot_route_to_render() {
        let mut s = Session::new_from_task("s".into(), "approve");
        s.context.set("revision", 2_u32).unwrap();
        s.context.set("decision", true).unwrap();
        s.context.set("approved_revision", 1_u32).unwrap();
        assert!(graph().unwrap().execute_session(&mut s).await.is_err());
        assert_eq!(s.current_task_id, "approve");
    }
    #[tokio::test]
    async fn graph_end_is_not_a_terminal_lock() {
        let mut s = Session::new_from_task("s".into(), "render");
        let g = graph().unwrap();
        g.execute_session(&mut s).await.unwrap();
        g.execute_session(&mut s).await.unwrap();
        assert_eq!(s.context.get::<u32>("visits.render"), Some(2));
    }
    #[tokio::test]
    async fn serialization_restores_detached_state() {
        let s = Session::new_from_task("s".into(), "approve");
        s.context.set("revision", 1_u32).unwrap();
        let restored: Session = serde_json::from_str(&serde_json::to_string(&s).unwrap()).unwrap();
        restored.context.set("revision", 2_u32).unwrap();
        assert_eq!(s.context.get::<u32>("revision"), Some(1));
    }
}
