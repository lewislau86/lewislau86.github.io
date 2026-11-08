//! Single-process team runtime. Endpoints are issued by the trusted application.
use crate::worker::{self, Mode};
use langchain_rust::schemas::Message;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{
    sync::{mpsc, oneshot, watch},
    task::JoinHandle,
};
pub type LabResult<T> = Result<T, &'static str>;
pub type Shared<T> = Arc<Mutex<T>>;
pub fn shared<T>(value: T) -> Shared<T> {
    Arc::new(Mutex::new(value))
}

// region contracts
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Payload {
    Work { path: String, brief: String },
    Note { text: String },
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Receipt {
    pub message_id: String,
    pub member: String,
    pub status: String,
    pub summary: Option<String>,
}
pub struct Envelope {
    pub id: String,
    pub from: String,
    pub payload: Payload,
    pub reply: oneshot::Sender<Receipt>,
}
pub struct Ticket {
    pub id: String,
    pub receiver: oneshot::Receiver<Receipt>,
}
impl Ticket {
    pub async fn wait(self) -> LabResult<Receipt> {
        tokio::time::timeout(Duration::from_secs(3), self.receiver)
            .await
            .map_err(|_| "receipt_timeout")?
            .map_err(|_| "worker_unavailable")
    }
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Limits {
    pub members: usize,
    pub mailbox: usize,
    pub messages: usize,
    pub models: usize,
    pub tools: usize,
    pub context_bytes: usize,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            members: 2,
            mailbox: 2,
            messages: 16,
            models: 16,
            tools: 8,
            context_bytes: 16000,
        }
    }
}
#[derive(Default, Clone, Debug, Serialize, Deserialize)]
pub struct Usage {
    pub accepted: usize,
    pub models: usize,
    pub tools: usize,
    pub reads: usize,
    pub spawned: usize,
    pub active: usize,
    pub joined: usize,
    pub aborted: usize,
}
#[derive(Default, Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub member: String,
    pub lifecycle: String,
    pub events: Vec<String>,
    pub messages: Vec<Message>,
    pub graph_nodes: Vec<String>,
    pub model_input_bytes: Vec<usize>,
    pub receipts: Vec<Receipt>,
    pub reads: usize,
    pub notes: usize,
    pub pairs_valid: bool,
}
// endregion contracts

pub struct Book {
    pub limits: Limits,
    pub usage: Usage,
    pub ids: BTreeSet<String>,
    pub routes: BTreeMap<String, mpsc::Sender<Envelope>>,
    pub accepting: bool,
}
impl Book {
    pub fn charge_model(&mut self) -> LabResult<()> {
        if self.usage.models >= self.limits.models {
            return Err("team_model_budget");
        }
        self.usage.models += 1;
        Ok(())
    }
    pub fn charge_tool(&mut self) -> LabResult<()> {
        if self.usage.tools >= self.limits.tools {
            return Err("team_tool_budget");
        }
        self.usage.tools += 1;
        Ok(())
    }
}

#[derive(Clone)]
pub struct Endpoint {
    identity: String,
    book: Shared<Book>,
}
fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 48
        && id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_".contains(&c))
}
impl Endpoint {
    // region delivery
    pub fn send(&self, to: &str, id: &str, payload: Payload) -> LabResult<Ticket> {
        if !valid_id(id) {
            return Err("invalid_message_id");
        }
        if serde_json::to_vec(&payload)
            .map_err(|_| "invalid_payload")?
            .len()
            > 512
        {
            return Err("message_size");
        }
        let mut book = self.book.lock().unwrap();
        if !book.accepting {
            return Err("team_closed");
        }
        let sender = book.routes.get(to).ok_or("unknown_member")?.clone();
        if book.ids.contains(id) {
            return Err("duplicate_message");
        }
        if book.usage.accepted >= book.limits.messages {
            return Err("team_message_budget");
        }
        let (reply, receiver) = oneshot::channel();
        let envelope = Envelope {
            id: id.into(),
            from: self.identity.clone(),
            payload,
            reply,
        };
        sender.try_send(envelope).map_err(|e| match e {
            mpsc::error::TrySendError::Full(_) => "mailbox_full",
            mpsc::error::TrySendError::Closed(_) => "mailbox_closed",
        })?;
        book.ids.insert(id.into());
        book.usage.accepted += 1;
        Ok(Ticket {
            id: id.into(),
            receiver,
        })
    }
    // endregion delivery
}

struct Member {
    cancel: watch::Sender<bool>,
    release: watch::Sender<bool>,
    snapshot: Shared<Snapshot>,
    changed: watch::Receiver<String>,
    handle: Option<JoinHandle<()>>,
}
pub struct Team {
    pub book: Shared<Book>,
    members: BTreeMap<String, Member>,
    pub root: PathBuf,
}
impl Team {
    pub fn new(root: PathBuf, limits: Limits) -> Self {
        Self {
            root,
            members: BTreeMap::new(),
            book: shared(Book {
                limits,
                usage: Usage::default(),
                ids: BTreeSet::new(),
                routes: BTreeMap::new(),
                accepting: true,
            }),
        }
    }
    pub fn endpoint(&self, member: &str) -> LabResult<Endpoint> {
        if member != "lead" && !self.members.contains_key(member) {
            return Err("unknown_member");
        }
        Ok(Endpoint {
            identity: member.into(),
            book: self.book.clone(),
        })
    }
    // region spawn
    pub fn spawn(&mut self, name: &str, mode: Mode, paused: bool) -> LabResult<()> {
        if !matches!(name, "core" | "config") {
            return Err("invalid_member");
        }
        if self.members.contains_key(name) {
            return Err("duplicate_member");
        }
        let mut book = self.book.lock().unwrap();
        if !book.accepting {
            return Err("team_closed");
        }
        if self.members.len() >= book.limits.members {
            return Err("member_limit");
        }
        if book.limits.mailbox == 0 || book.limits.mailbox > 8 {
            return Err("invalid_limits");
        }
        let (sender, receiver) = mpsc::channel(book.limits.mailbox);
        book.routes.insert(name.into(), sender);
        book.usage.spawned += 1;
        book.usage.active += 1;
        drop(book);
        let (cancel, cancellation) = watch::channel(false);
        let (release, gate) = watch::channel(!paused);
        let (phase, changed) = watch::channel("starting".to_owned());
        let snapshot = shared(Snapshot {
            member: name.into(),
            lifecycle: "starting".into(),
            pairs_valid: true,
            ..Default::default()
        });
        let endpoint = Endpoint {
            identity: name.into(),
            book: self.book.clone(),
        };
        let actor = worker::Actor {
            name: name.into(),
            root: self.root.clone(),
            mode,
            endpoint,
            book: self.book.clone(),
            snapshot: snapshot.clone(),
            phase,
            gate,
            cancellation,
            receiver,
        };
        let handle = tokio::spawn(worker::actor_loop(actor));
        self.members.insert(
            name.into(),
            Member {
                cancel,
                release,
                snapshot,
                changed,
                handle: Some(handle),
            },
        );
        Ok(())
    }
    // endregion spawn
    pub async fn phase(&mut self, name: &str, expected: &str) -> LabResult<()> {
        let member = self.members.get_mut(name).ok_or("unknown_member")?;
        tokio::time::timeout(Duration::from_secs(2), async {
            while member.changed.borrow().as_str() != expected {
                member
                    .changed
                    .changed()
                    .await
                    .map_err(|_| "worker_unavailable")?;
            }
            Ok(())
        })
        .await
        .map_err(|_| "phase_timeout")?
    }
    pub fn release(&self, name: &str) {
        self.members[name].release.send_replace(true);
    }
    pub fn cancel(&self, name: &str) {
        self.members[name].cancel.send_replace(true);
    }
    pub fn snapshots(&self) -> BTreeMap<String, Snapshot> {
        self.members
            .iter()
            .map(|(id, m)| (id.clone(), m.snapshot.lock().unwrap().clone()))
            .collect()
    }
    // region shutdown
    pub async fn shutdown(&mut self) {
        self.book.lock().unwrap().accepting = false;
        for member in self.members.values() {
            member.cancel.send_replace(true);
        }
        for member in self.members.values_mut() {
            if let Some(mut handle) = member.handle.take() {
                if tokio::time::timeout(Duration::from_secs(2), &mut handle)
                    .await
                    .is_err()
                {
                    handle.abort();
                    let _ = handle.await;
                    self.book.lock().unwrap().usage.aborted += 1;
                }
                self.book.lock().unwrap().usage.joined += 1;
            }
        }
    }
    // endregion shutdown
}
impl Drop for Team {
    fn drop(&mut self) {
        // Best effort only: callers use shutdown().await to confirm cleanup.
        for member in self.members.values_mut() {
            member.cancel.send_replace(true);
            if let Some(handle) = member.handle.take() {
                handle.abort();
            }
        }
    }
}

pub fn pairs(messages: &[Message]) -> bool {
    let mut seen = BTreeSet::new();
    let mut pending = BTreeSet::new();
    for message in messages {
        if message.message_type == langchain_rust::schemas::MessageType::ToolMessage {
            let Some(id) = &message.id else {
                return false;
            };
            if !pending.remove(id) {
                return false;
            }
        } else {
            if !pending.is_empty() {
                return false;
            }
            let calls: Vec<langchain_rust::schemas::ToolCall> = match &message.tool_calls {
                Some(raw) => match serde_json::from_value(raw.clone()) {
                    Ok(calls) => calls,
                    Err(_) => return false,
                },
                None => vec![],
            };
            for call in calls {
                if call.id.is_empty() || !seen.insert(call.id.clone()) {
                    return false;
                }
                pending.insert(call.id);
            }
        }
    }
    pending.is_empty()
}
