//! R20 integrated harness: real graph/LLM interfaces, stdio MCP, SQLite, worktree and reviewer task.
mod agent;
mod connection;
mod runtime;
mod server;
mod store;
#[cfg(test)]
mod tests;
use serde_json::{Value, json};
use std::{fs, path::Path, sync::Arc};
use tokio::sync::Mutex;
type AnyError = Box<dyn std::error::Error + Send + Sync>;
pub const SCENARIOS: &[&str] = &[
    "normal",
    "read-retry",
    "approval-denied",
    "pre-hook",
    "post-hook",
    "write-unknown",
    "model-budget",
    "tool-budget",
    "context-budget",
    "source-stale",
    "knowledge-injection",
    "false-finish",
    "duplicate-call",
    "model-error",
    "review-failed",
    "cancel-review",
    "stale-owner",
    "terminal-save-failed",
];

pub async fn experiment(mode: &str, root: &Path) -> Result<Value, AnyError> {
    let runtime = Arc::new(Mutex::new(runtime::Runtime::create(mode, root).await?));
    // Always clean hosted resources even if the graph driver returns an infrastructure error.
    let execution = agent::run(runtime.clone()).await;
    let mut rt = runtime.lock().await;
    let (state, nodes) = match execution {
        Ok(value) => value,
        Err(error) => {
            rt.cleanup().await?;
            return Err(error);
        }
    };
    let verified = agent::verify_goal(&state, &rt);
    let report_exists = rt.workspace.join("report.txt").exists();
    let report_text = fs::read_to_string(rt.workspace.join("report.txt")).ok();
    let cleanup = rt.cleanup().await?;
    let book = rt.book.lock().unwrap();
    let usage = book.usage.clone();
    let events = book.events.clone();
    drop(book);
    for event in &events {
        rt.store.event(
            event.call_id.as_deref(),
            &event.kind,
            &format!("{}:{}", event.actor, event.detail),
        );
    }
    let terminal_error = rt
        .store
        .terminal(verified, mode == "terminal-save-failed")
        .err()
        .map(|e| e.to_string());
    let database = rt.store.snapshot();
    // Independently reopen storage after the terminal transaction, rather than trust in-memory state.
    let reopened = store::Store::open(&root.join("tasks.sqlite"))?.snapshot();
    if reopened != database {
        return Err("reopened_state_mismatch".into());
    }
    let persisted = database["status"] == "completed";
    let result = json!({"scenario":mode,"scope":"scripted parent and reviewer LLM; real pinned graph-flow/langchain-rust, local MCP subprocess, SQLite and Git; no real provider",
        "goal_verified":verified,"completed":verified&&persisted,"terminal_error":terminal_error,
        "trigger_duplicate_inserted":rt.duplicate_inserted,"database":database,"usage":usage,"events":events,
        "graph_nodes":nodes,"state":state,"review_history":rt.review_history,
        "wire":rt.wire.lock().unwrap().clone(),"cleanup":cleanup,
        "report_exists":report_exists,"report_text":report_text,"reopened_equal":true});
    fs::write(root.join("run.json"), serde_json::to_vec_pretty(&result)?)?;
    Ok(result)
}
#[tokio::main]
async fn main() -> Result<(), AnyError> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() == 3 && args[0] == "server" {
        return server::run(args[1].clone().into(), args[2].clone()).await;
    }
    let (json_output, mode, dest) = match args.as_slice() {
        [flag, mode, dest] if flag == "--json" => (true, mode, dest),
        [mode, dest] => (false, mode, dest),
        _ => return Err("usage: learn-agent-r20 [--json] SCENARIO NEW_DIRECTORY".into()),
    };
    if !SCENARIOS.contains(&mode.as_str()) {
        return Err("unknown scenario".into());
    }
    let report = experiment(mode, Path::new(dest)).await?;
    if json_output {
        println!("{}", serde_json::to_string_pretty(&report)?);
    } else {
        println!(
            "scenario={} stop={} goal_verified={} completed={}",
            mode,
            report["state"]["stop"].as_str().unwrap(),
            report["goal_verified"],
            report["completed"]
        );
        println!(
            "task={} model_calls={} tool_attempts={} retries={} spawned={} joined={}",
            report["database"]["status"].as_str().unwrap(),
            report["usage"]["models"],
            report["usage"]["tools"],
            report["usage"]["retries"],
            report["usage"]["spawned"],
            report["usage"]["joined"]
        );
        println!(
            "duplicate_trigger_inserted={} context_compacted={} report_exists={} workspace={}",
            report["trigger_duplicate_inserted"],
            report["state"]["compacted"],
            report["report_exists"],
            report["cleanup"]["workspace"].as_str().unwrap()
        );
        println!(
            "mcp_reaped={} active_jobs={} primary_unchanged={} reopened_equal={}",
            report["cleanup"]["mcp_reaped"],
            report["cleanup"]["active_jobs"],
            report["cleanup"]["source_unchanged"],
            report["reopened_equal"]
        );
        if let Some(error) = report["terminal_error"].as_str() {
            println!("terminal_error={error}");
        }
    }
    Ok(())
}
