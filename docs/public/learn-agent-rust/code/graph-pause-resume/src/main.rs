//! G02（ADK-Rust 3.0 / adk-graph）：图暂停、检查点存储与跨进程恢复。
//!
//! 升级审查：draft 写提案 → approve 暂停等人决定 → render 生成报告，或 reject，或 revise 回到 draft。
//! 每条命令都是一个独立进程，状态只在 SQLite 检查点文件里。
//!
//!   graph-resume-lab DB init                         开始审查，停在 approve
//!   graph-resume-lab DB show                         重新进入等待中的 approve，看它在等什么
//!   graph-resume-lab DB answer ID approve|reject|revise   按暂停 ID 回答（严格恢复）
//!   graph-resume-lab DB answer-loose approve         按节点名回答（非严格，用于对照）
//!   graph-resume-lab DB conflict ID                  两个写入者同时恢复同一个暂停
//!   graph-resume-lab DB tamper corrupt|rename|rename-unchecked
//!                                                    改坏检查点，或换一张图再恢复（宿主检查 / 不检查图版本）
mod trace;

use std::{
    fs::OpenOptions,
    io::Write,
    path::{Path, PathBuf},
    sync::{Arc, OnceLock},
};

use adk_graph::{
    checkpoint::SqliteCheckpointer,
    edge::{END, START},
    error::{GraphError, Result},
    graph::{CompiledGraph, StateGraph},
    node::{ExecutionConfig, NodeContext, NodeOutput},
    state::{State, StateSchema},
};
use serde_json::{Value, json};
use tokio::sync::Barrier;

const THREAD: &str = "review-42";
/// 图的版本号。框架不检查“保存检查点的图”和“恢复它的图”是不是同一版，这一项由宿主检查。
const GRAPH_VERSION: &str = "release-review-v1";

/// 每个节点每真正执行一次就在 runs.log 里记一行：用来观察恢复时哪些节点会再跑。
fn record_run(dir: &Path, node: &str) {
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("runs.log"))
        .expect("runs.log");
    writeln!(file, "{node}").expect("write runs.log");
}

/// 冲突实验用：先进入 render 的写入者在这里最多等 1 秒，不让它在另一个写入者读检查点之前跑完。
/// 另一个写入者保存 approve 这一步时遇到版本冲突，到不了 render，所以靠超时放行。
fn conflict_barrier() -> &'static OnceLock<Arc<Barrier>> {
    static BARRIER: OnceLock<Arc<Barrier>> = OnceLock::new();
    &BARRIER
}

// region graph
fn schema() -> StateSchema {
    StateSchema::builder()
        .channel("proposal")
        .channel("revision")
        .channel("decision")
        .channel("report")
        .channel("outcome")
        .channel("graph_version")
        .list_channel("trace")
        .build()
}

fn graph(dir: PathBuf, approve_name: &'static str) -> StateGraph {
    let d1 = dir.clone();
    let d2 = dir.clone();
    let d3 = dir.clone();
    let d4 = dir;
    StateGraph::new(schema())
        .add_node_fn("draft", move |ctx: NodeContext| {
            let dir = d1.clone();
            async move {
                record_run(&dir, "draft");
                let revision = ctx.get("revision").and_then(Value::as_u64).unwrap_or(0) + 1;
                Ok(NodeOutput::new()
                    .with_update("revision", json!(revision))
                    .with_update("proposal", json!(format!("升级到 3.0，第 {revision} 版提案")))
                    .with_update("trace", json!("draft")))
            }
        })
        .add_node_fn(approve_name, move |ctx: NodeContext| {
            let dir = d2.clone();
            async move {
                record_run(&dir, "approve");
                let answer = ctx.resume_value().and_then(|v| v.get("decision")).and_then(Value::as_str);
                let next = match answer {
                    Some("approve") => "render",
                    Some("reject") => "reject",
                    Some("revise") => "draft",
                    // 没有回答：暂停。暂停的数据和答案格式一起决定暂停 ID
                    _ => {
                        return Ok(NodeOutput::interrupt_with_data(
                            "approve this proposal?",
                            json!({ "proposal": ctx.get("proposal"), "revision": ctx.get("revision") }),
                        )
                        .with_response_schema(json!({
                            "type": "object",
                            "properties": { "decision": { "enum": ["approve", "reject", "revise"] } },
                            "required": ["decision"]
                        })));
                    }
                };
                Ok(NodeOutput::new()
                    .with_update("decision", json!(answer))
                    .with_update("trace", json!("approve"))
                    .with_goto([next]))
            }
        })
        .add_node_fn("render", move |ctx: NodeContext| {
            let dir = d3.clone();
            async move {
                record_run(&dir, "render");
                if let Some(barrier) = conflict_barrier().get() {
                    // 另一个写入者会因版本冲突提前失败、到不了这里，所以最多等一秒
                    let _ = tokio::time::timeout(std::time::Duration::from_secs(1), barrier.wait()).await;
                }
                let revision = ctx.get("revision").and_then(Value::as_u64).unwrap_or(0);
                Ok(NodeOutput::new()
                    .with_update("report", json!(format!("upgrade report: revision {revision} approved")))
                    .with_update("outcome", json!("approved"))
                    .with_update("trace", json!("render")))
            }
        })
        .add_node_fn("reject", move |_ctx: NodeContext| {
            let dir = d4.clone();
            async move {
                record_run(&dir, "reject");
                Ok(NodeOutput::new().with_update("outcome", json!("rejected")).with_update("trace", json!("reject")))
            }
        })
        .add_edge(START, "draft")
        .add_edge("draft", approve_name)
        .add_edge("render", END)
        .add_edge("reject", END)
}

async fn compiled(db: &Path, approve_name: &'static str) -> Result<CompiledGraph> {
    let dir = db.parent().map(Path::to_path_buf).unwrap_or_default();
    let url = format!("sqlite:{}?mode=rwc", db.display());
    let checkpointer = SqliteCheckpointer::new(&url).await?;
    graph(dir, approve_name)
        .compile()
        .map(|g| g.with_checkpointer(checkpointer))
}
// endregion graph

// region report
/// 把一次 invoke 的结果写成稳定的文字：暂停时给出暂停 ID 和等待的内容，结束时给出结果。
fn report(result: &Result<State>) -> String {
    match result {
        Ok(state) => {
            let trace: Vec<&str> = state["trace"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .collect();
            format!(
                "status=completed outcome={} revision={} report={}\ntrace={}",
                state
                    .get("outcome")
                    .and_then(Value::as_str)
                    .unwrap_or("none"),
                state.get("revision").and_then(Value::as_u64).unwrap_or(0),
                state
                    .get("report")
                    .and_then(Value::as_str)
                    .unwrap_or("none"),
                trace.join(">")
            )
        }
        Err(GraphError::Interrupted(paused)) => format!(
            "status=waiting step={} interrupt={} revision={}",
            paused.step,
            paused.interrupt.id().unwrap_or("none"),
            paused
                .state
                .get("revision")
                .and_then(Value::as_u64)
                .unwrap_or(0)
        ),
        Err(GraphError::ResumeRejected { .. }) => "status=refused reason=resume_rejected".into(),
        Err(GraphError::CheckpointConflict { .. }) => {
            "status=refused reason=checkpoint_conflict".into()
        }
        Err(error) => format!("status=error kind={}", kind(error)),
    }
}

fn kind(error: &GraphError) -> &'static str {
    match error {
        GraphError::CheckpointError(_)
        | GraphError::SerializationError(_)
        | GraphError::JsonError(_) => "checkpoint_unreadable",
        GraphError::NodeNotFound(_) | GraphError::UnknownRouteTarget(_) => "unknown_node",
        _ => "other",
    }
}
// endregion report

// region resume
/// 宿主恢复前先读检查点里的状态，确认它是由同一版图保存的；不一致就不运行任何节点。
async fn resume(
    db: &Path,
    approve_name: &'static str,
    version: &str,
    cfg: ExecutionConfig,
) -> Result<String> {
    let graph = compiled(db, approve_name).await?;
    let saved = graph.get_state(THREAD).await?;
    let saved_version = saved
        .as_ref()
        .and_then(|s| s.get("graph_version"))
        .and_then(Value::as_str);
    if saved_version != Some(version) {
        return Ok(format!(
            "status=refused reason=graph_version saved={} running={version}",
            saved_version.unwrap_or("none")
        ));
    }
    Ok(report(&graph.invoke(State::new(), cfg).await))
}
// endregion resume

fn runs(dir: &Path) -> String {
    let text = std::fs::read_to_string(dir.join("runs.log")).unwrap_or_default();
    let count = |node: &str| text.lines().filter(|l| *l == node).count();
    format!(
        "node_runs draft={} approve={} render={} reject={}",
        count("draft"),
        count("approve"),
        count("render"),
        count("reject")
    )
}

async fn command(db: &Path, args: &[String]) -> Result<String> {
    let dir = db.parent().map(Path::to_path_buf).unwrap_or_default();
    let cfg = ExecutionConfig::new(THREAD);
    let out = match args {
        // region commands
        [c] if c == "init" => {
            let mut input = State::new();
            input.insert("revision".into(), json!(0));
            input.insert("graph_version".into(), json!(GRAPH_VERSION));
            report(&compiled(db, "approve").await?.invoke(input, cfg).await)
        }
        [c] if c == "show" => resume(db, "approve", GRAPH_VERSION, cfg).await?,
        [c, id, decision] if c == "answer" => {
            let cfg = cfg
                .strict_resume()
                .with_resume_value(id.as_str(), json!({ "decision": decision }));
            resume(db, "approve", GRAPH_VERSION, cfg).await?
        }
        [c, decision] if c == "answer-loose" => {
            let cfg = cfg.with_resume_value("approve", json!({ "decision": decision }));
            resume(db, "approve", GRAPH_VERSION, cfg).await?
        }
        // endregion commands
        [c, id] if c == "conflict" => {
            // 两个写入者（两张图对象，共用同一个 SQLite 文件）同时用同一个答案恢复同一个暂停
            conflict_barrier().get_or_init(|| Arc::new(Barrier::new(2)));
            let (a, b) = (
                compiled(db, "approve").await?,
                compiled(db, "approve").await?,
            );
            let answer = |id: &str| {
                ExecutionConfig::new(THREAD).with_resume_value(id, json!({ "decision": "approve" }))
            };
            let (ra, rb) = tokio::join!(
                a.invoke(State::new(), answer(id)),
                b.invoke(State::new(), answer(id))
            );
            let mut lines = [report(&ra), report(&rb)];
            lines.sort();
            lines.join("\n")
        }
        [c, how] if c == "tamper" => {
            match how.as_str() {
                "corrupt" => {
                    let conn = rusqlite::Connection::open(db)
                        .map_err(|e| GraphError::CheckpointError(e.to_string()))?;
                    conn.execute(
                        "UPDATE graph_checkpoints SET state = '{broken' WHERE version = (SELECT MAX(version) FROM graph_checkpoints)",
                        [],
                    )
                    .map_err(|e| GraphError::CheckpointError(e.to_string()))?;
                    report(
                        &compiled(db, "approve")
                            .await?
                            .invoke(State::new(), cfg)
                            .await,
                    )
                }
                // 新版本的图把 approve 改名为 approve_v2：检查点里记着的待运行节点在新图里不存在。
                // 不检查版本时，框架照常运行这张新图；宿主检查版本时，恢复在运行任何节点之前被拒绝。
                "rename-unchecked" => report(
                    &compiled(db, "approve_v2")
                        .await?
                        .invoke(State::new(), cfg)
                        .await,
                ),
                "rename" => resume(db, "approve_v2", "release-review-v2", cfg).await?,
                _ => {
                    return Err(GraphError::InvalidGraph(
                        "tamper corrupt|rename|rename-unchecked".into(),
                    ));
                }
            }
        }
        _ => return Err(GraphError::InvalidGraph("bad command".into())),
    };
    Ok(format!("{out}\n{}", runs(&dir)))
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some((db, rest)) = args.split_first() else {
        eprintln!(
            "usage: graph-resume-lab DB init|show|answer ID DECISION|answer-loose DECISION|conflict ID|tamper corrupt|rename|rename-unchecked"
        );
        std::process::exit(2);
    };
    match command(Path::new(db), rest).await {
        Ok(text) => println!("{text}"),
        Err(error) => {
            eprintln!("usage error: {error}");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_db(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("g02-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("review.db")
    }

    fn interrupt_id(text: &str) -> String {
        text.split("interrupt=")
            .nth(1)
            .unwrap()
            .split(' ')
            .next()
            .unwrap()
            .to_string()
    }

    #[tokio::test]
    async fn a_pause_survives_a_fresh_graph_and_resumes_once() {
        let db = temp_db("resume");
        let first = command(&db, &["init".into()]).await.unwrap();
        let id = interrupt_id(&first);
        let done = command(&db, &["answer".into(), id, "approve".into()])
            .await
            .unwrap();
        assert!(done.contains("outcome=approved"), "{done}");
        assert!(done.contains("render=1"), "{done}");
    }

    #[tokio::test]
    async fn an_answer_for_an_old_pause_is_refused_under_strict_resume() {
        let db = temp_db("stale");
        let old = interrupt_id(&command(&db, &["init".into()]).await.unwrap());
        let revised = command(&db, &["answer".into(), old.clone(), "revise".into()])
            .await
            .unwrap();
        assert!(revised.contains("revision=2"), "{revised}");
        let stale = command(&db, &["answer".into(), old, "approve".into()])
            .await
            .unwrap();
        assert!(stale.contains("resume_rejected"), "{stale}");
    }

    #[tokio::test]
    async fn an_answer_outside_the_schema_is_refused() {
        let db = temp_db("schema");
        let id = interrupt_id(&command(&db, &["init".into()]).await.unwrap());
        let wrong = command(&db, &["answer".into(), id, "maybe".into()])
            .await
            .unwrap();
        assert!(wrong.contains("resume_rejected"), "{wrong}");
    }
}
