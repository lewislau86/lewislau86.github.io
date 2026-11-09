use crate::{
    AnyError,
    adapter::{Approval, Dispatcher, Invocation, Registry},
    connection::{Connection, Wire},
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fs,
    path::Path,
    sync::{Arc, Mutex},
};

pub const SCENARIOS: &[&str] = &[
    "normal",
    "dual-server",
    "denied-write",
    "approved-write",
    "approval-mismatch",
    "invalid-arguments",
    "unknown-tool",
    "duplicate-call",
    "tool-error",
    "protocol-error",
    "timeout",
    "write-timeout",
    "server-crash",
    "discovery-duplicate",
    "discovery-schema",
    "discovery-name",
    "cursor-loop",
    "missing-capability",
    "startup-exit",
    "startup-timeout",
    "dirty-stdout",
    "list-timeout",
    "result-limit",
    "closed-registry",
    "call-budget",
];
fn invocation(id: &str, name: &str, arguments: Value) -> Invocation {
    Invocation {
        call_id: id.into(),
        name: name.into(),
        arguments,
    }
}

pub async fn run(scenario: &str, root: &Path) -> Result<Value, AnyError> {
    if !SCENARIOS.contains(&scenario) {
        return Err("unknown scenario".into());
    }
    fs::create_dir(root)?; // Never overwrite an existing fixture directory.
    let root = root.canonicalize()?;
    let mode = match scenario {
        "write-timeout" => "effect-hang",
        "discovery-duplicate" => "duplicate",
        "discovery-schema" => "bad-schema",
        "discovery-name" => "bad-name",
        "cursor-loop" => "cursor-loop",
        "missing-capability" => "no-tools",
        "startup-exit" => "exit-start",
        "startup-timeout" => "silent-start",
        "dirty-stdout" => "dirty-stdout",
        "list-timeout" => "slow-list",
        _ => "normal",
    };
    let wire: Wire = Arc::new(Mutex::new(vec![]));
    let mut connections = BTreeMap::new();
    let mut registry = Registry::local();
    let mut startup = BTreeMap::new();
    let mut discovery = BTreeMap::new();
    for namespace in if scenario == "dual-server" {
        vec!["notes", "other"]
    } else {
        vec!["notes"]
    } {
        let folder = root.join(namespace);
        fs::create_dir(&folder)?;
        fs::write(
            folder.join("README.md"),
            format!("# {namespace}\n启动：cargo run\n"),
        )?;
        let mut connection = Connection::spawn(&folder, mode, namespace, wire.clone()).await?;
        startup.insert(namespace.to_owned(), connection.startup);
        let result = registry.discover(namespace, &mut connection).await;
        discovery.insert(namespace.to_owned(), result.err().unwrap_or("ok"));
        connections.insert(namespace.to_owned(), connection);
    }
    let definitions = registry.definitions();
    let mut dispatcher = Dispatcher::default();
    let mut results = vec![];
    if discovery.values().all(|v| *v == "ok") {
        let path = json!({"path":"README.md"});
        let request = match scenario {
            "denied-write" | "approved-write" | "approval-mismatch" | "write-timeout" => {
                invocation(
                    "call-1",
                    "mcp_notes__append_note",
                    json!({"text":"one line"}),
                )
            }
            "invalid-arguments" => invocation("call-1", "mcp_notes__read_note", json!({"path":7})),
            "unknown-tool" => invocation("call-1", "mcp_notes__missing", path.clone()),
            "tool-error" => invocation("call-1", "mcp_notes__fail_note", path.clone()),
            "protocol-error" => invocation("call-1", "mcp_notes__rpc_error", path.clone()),
            "timeout" => invocation("call-1", "mcp_notes__slow_note", path.clone()),
            "server-crash" => invocation("call-1", "mcp_notes__crash_note", path.clone()),
            "result-limit" => invocation("call-1", "mcp_notes__big_note", path.clone()),
            _ => invocation("call-1", "mcp_notes__read_note", path.clone()),
        };
        let approval = match scenario {
            "approved-write" | "write-timeout" => Some(Approval(request.clone())),
            "approval-mismatch" => Some(Approval(invocation(
                "call-1",
                &request.name,
                json!({"text":"different"}),
            ))),
            _ => None,
        };
        if scenario == "normal" {
            results.push(
                dispatcher
                    .invoke(
                        &registry,
                        &mut connections,
                        invocation("local-1", "local_status", path.clone()),
                        None,
                    )
                    .await,
            );
        }
        if scenario == "closed-registry" {
            connections.get_mut("notes").unwrap().usable = false;
            registry.invalidate("notes");
        }
        results.push(
            dispatcher
                .invoke(&registry, &mut connections, request.clone(), approval)
                .await,
        );
        if ["duplicate-call", "timeout", "write-timeout", "server-crash"].contains(&scenario) {
            let next = if scenario == "duplicate-call" {
                request
            } else {
                invocation("call-2", "mcp_notes__read_note", path.clone())
            };
            results.push(
                dispatcher
                    .invoke(&registry, &mut connections, next, None)
                    .await,
            );
        }
        if scenario == "dual-server" {
            results.push(
                dispatcher
                    .invoke(
                        &registry,
                        &mut connections,
                        invocation("call-2", "mcp_other__read_note", path.clone()),
                        None,
                    )
                    .await,
            );
        }
        if scenario == "call-budget" {
            for n in 2..=9 {
                results.push(
                    dispatcher
                        .invoke(
                            &registry,
                            &mut connections,
                            invocation(&format!("call-{n}"), "mcp_notes__read_note", path.clone()),
                            None,
                        )
                        .await,
                );
            }
        }
    }
    let mut cleanup = BTreeMap::new();
    for (namespace, connection) in &mut connections {
        registry.invalidate(namespace);
        cleanup.insert(namespace.clone(), connection.close().await?);
    }
    let trace = wire.lock().unwrap().clone();
    Ok(
        json!({"scenario":scenario,"startup":startup,"discovery":discovery,"definitions":definitions,
        "results":results,"dispatched":dispatcher.dispatched,"cleanup":cleanup,"wire":trace,
        "remaining_tools":registry.0.keys().collect::<Vec<_>>()}),
    )
}
