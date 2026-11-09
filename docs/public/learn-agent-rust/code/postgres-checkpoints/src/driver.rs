use crate::state::{Error, Granularity, Message, Phase, Result, State};
use crate::store::{Fault, Store};
use serde_json::{Value, json};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::Path;

fn checkpoint(
    store: &mut Store,
    id: &str,
    revision: &mut i64,
    state: &State,
    fault: Fault,
) -> Result<()> {
    let save_id = format!("step-{}", *revision + 1);
    store.save(id, *revision, &save_id, state, fault)?;
    *revision += 1;
    Ok(())
}

fn read(root: &Path, filename: &str) -> Result<String> {
    let path = root.join(filename);
    let meta = fs::symlink_metadata(&path).map_err(|_| Error("tool_failed"))?;
    if !meta.is_file() {
        return Err(Error("tool_failed"));
    }
    let mut bytes = Vec::new();
    fs::File::open(path)
        .map_err(|_| Error("tool_failed"))?
        .take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| Error("tool_failed"))?;
    if bytes.len() > 4096 {
        return Err(Error("tool_failed"));
    }
    String::from_utf8(bytes).map_err(|_| Error("tool_failed"))
}

fn tool(root: &Path, state: &State) -> Result<String> {
    if state.cursor == 0 {
        return read(root, "README.md");
    }
    if state.profile == "read_only" {
        return read(root, "Cargo.toml");
    }
    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open(root.join("audit.log"))
        .map_err(|_| Error("tool_failed"))?;
    file.write_all(b"report delivered\n")
        .map_err(|_| Error("tool_failed"))?;
    file.sync_all().map_err(|_| Error("tool_failed"))?;
    Ok("report delivered".into())
}

// region recover
fn recover(store: &mut Store, id: &str, revision: &mut i64, state: &mut State) -> Result<()> {
    state.uncertain = Some(
        if state.phase == Phase::ModelInFlight {
            "model"
        } else {
            "tool"
        }
        .into(),
    );
    state.phase = Phase::Reconcile;
    checkpoint(store, id, revision, state, Fault::None)
}
// endregion recover

// region step
pub fn step(
    store: &mut Store,
    id: &str,
    root: &Path,
    expected: i64,
    fault: Fault,
) -> Result<Value> {
    let (mut revision, mut state) = store.load(id)?;
    if revision != expected {
        return Err(Error("revision_conflict"));
    }
    match state.phase {
        Phase::Done | Phase::Reconcile => {}
        Phase::ModelInFlight | Phase::ToolInFlight => {
            recover(store, id, &mut revision, &mut state)?
        }
        Phase::Model => {
            if state.model_turns >= state.max_model_turns {
                return Err(Error("model_budget"));
            }
            state.model_turns += 1;
            state.phase = Phase::ModelInFlight;
            checkpoint(store, id, &mut revision, &state, Fault::None)?;
            // Script model: its call and answer happen OUTSIDE the database transaction.
            if state.cursor == 0 {
                state.messages.push(Message::AssistantCalls {
                    ids: state.calls().iter().map(|id| (*id).into()).collect(),
                });
                state.phase = Phase::Tools;
            } else {
                let text = state
                    .messages
                    .iter()
                    .find_map(|m| {
                        if let Message::Tool { call_id, content } = m {
                            (call_id == "read-1").then_some(content)
                        } else {
                            None
                        }
                    })
                    .ok_or(Error("invalid_state"))?;
                if !text.contains("cargo run") {
                    return Err(Error("model_fixture_mismatch"));
                }
                state.messages.push(Message::Assistant {
                    text: "已核对启动命令 cargo run".into(),
                });
                state.phase = Phase::Done;
            }
            if fault == Fault::AfterModel {
                std::process::exit(76);
            }
            checkpoint(store, id, &mut revision, &state, fault)?;
        }
        Phase::Tools => {
            let count = if state.granularity == Granularity::Tool {
                1
            } else {
                2 - state.cursor
            };
            if state.tool_dispatches + count as u32 > state.max_tool_dispatches {
                return Err(Error("tool_budget"));
            }
            state.tool_dispatches += count as u32;
            state.phase = Phase::ToolInFlight;
            checkpoint(store, id, &mut revision, &state, Fault::None)?;
            for _ in 0..count {
                let content = tool(root, &state)?;
                let call_id = state.calls()[state.cursor].into();
                if fault == Fault::AfterAction {
                    std::process::exit(75);
                }
                state.messages.push(Message::Tool { call_id, content });
                state.cursor += 1;
            }
            state.phase = if state.cursor == 2 {
                Phase::Model
            } else {
                Phase::Tools
            };
            checkpoint(store, id, &mut revision, &state, fault)?;
        }
    }
    Ok(json!({"status":"stepped","revision":revision,"state":state}))
}
// endregion step
