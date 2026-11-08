use crate::protocol::{Check, Decision, Member, Message, Plan, Registry, decode};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::{mpsc, watch};
use tokio::task::JoinHandle;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Normal,
    Reject,
    Silent,
    AckStall,
    Panic,
    IgnoreCancel,
}

// The trusted application creates endpoints. JSON can never set this identity.
#[derive(Clone, Copy)]
pub struct Endpoint {
    member: Member,
}

enum Command {
    Propose { id: String, plan: Plan },
    Deliver(Message),
    Execute { id: String, plan: Plan },
}

#[derive(Debug)]
pub enum Output {
    Wire {
        from: Member,
        to: Member,
        message: Message,
    },
    Seen {
        member: Member,
        id: String,
    },
    Executed {
        member: Member,
        id: String,
        result: Check<()>,
    },
}

struct Worker {
    tx: mpsc::Sender<Command>,
    cancel: watch::Sender<bool>,
    start: watch::Sender<bool>,
    join: JoinHandle<&'static str>,
}

// Owned by the spawned future, including before its first poll. Panic and
// cancellation drop it too, so the report observes tasks rather than a constant.
struct TaskGuard(Arc<AtomicUsize>);

impl Drop for TaskGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Joined {
    pub member: Member,
    pub outcome: String,
    pub aborted: bool,
}

pub struct Runtime {
    pub registry: Arc<Mutex<Registry>>,
    workers: BTreeMap<Member, Worker>,
    rx: mpsc::Receiver<Output>,
    pub received: Vec<String>,
    active: Arc<AtomicUsize>,
}

impl Runtime {
    pub fn new(root: PathBuf, core_mode: Mode, paused: bool) -> Self {
        let registry = Arc::new(Mutex::new(Registry::default()));
        let (out, rx) = mpsc::channel(64);
        let mut workers = BTreeMap::new();
        let active = Arc::new(AtomicUsize::new(0));
        for member in [Member::Core, Member::Config] {
            let (tx, inbox) = mpsc::channel(2);
            let (cancel, cancel_rx) = watch::channel(false);
            let (start, start_rx) = watch::channel(!paused);
            let mode = if member == Member::Core {
                core_mode
            } else {
                Mode::Normal
            };
            active.fetch_add(1, Ordering::SeqCst);
            let join = tokio::spawn(actor(
                member,
                mode,
                inbox,
                out.clone(),
                cancel_rx,
                start_rx,
                registry.clone(),
                root.clone(),
                TaskGuard(active.clone()),
            ));
            workers.insert(
                member,
                Worker {
                    tx,
                    cancel,
                    start,
                    join,
                },
            );
        }
        Self {
            registry,
            workers,
            rx,
            received: Vec::new(),
            active,
        }
    }

    pub fn active(&self) -> usize {
        self.active.load(Ordering::SeqCst)
    }

    pub fn endpoint(&self, member: Member) -> Endpoint {
        Endpoint { member }
    }

    pub fn snapshot(&self) -> Registry {
        self.registry.lock().unwrap().clone()
    }

    pub fn advance(&self, now: u64) -> Check<()> {
        self.registry.lock().unwrap().advance(now)
    }

    pub fn raw(&self, from: Endpoint, to: Member, raw: &str) -> Check<()> {
        self.route(from, to, decode(raw)?)
    }

    // region delivery-commit
    pub fn route(&self, from: Endpoint, to: Member, message: Message) -> Check<()> {
        let mut registry = self.registry.lock().unwrap();
        let mut candidate = registry.clone();
        candidate.dispatch(from.member, to, &message)?;
        if to != Member::Lead {
            self.workers
                .get(&to)
                .ok_or("unknown_member")?
                .tx
                .try_send(Command::Deliver(message))
                .map_err(mail_error)?;
        }
        // No await between validation, try_send and commit on current_thread.
        *registry = candidate;
        Ok(())
    }
    // endregion delivery-commit

    pub fn propose(&self, member: Member, id: &str, plan: Plan) -> Check<()> {
        self.workers
            .get(&member)
            .ok_or("unknown_member")?
            .tx
            .try_send(Command::Propose {
                id: id.into(),
                plan,
            })
            .map_err(mail_error)
    }

    pub fn execute(&self, member: Member, id: &str, plan: Plan) -> Check<()> {
        self.workers
            .get(&member)
            .ok_or("unknown_member")?
            .tx
            .try_send(Command::Execute {
                id: id.into(),
                plan,
            })
            .map_err(mail_error)
    }

    pub fn release(&self) {
        for worker in self.workers.values() {
            let _ = worker.start.send(true);
        }
    }

    pub fn cancel(&self, member: Member) {
        let _ = self.workers[&member].cancel.send(true);
    }

    pub fn finished(&self, member: Member) -> bool {
        self.workers[&member].join.is_finished()
    }

    // Only this consumer dispatches wire responses to the authoritative registry.
    pub async fn next(&mut self) -> Output {
        let output = tokio::time::timeout(Duration::from_secs(2), self.rx.recv())
            .await
            .expect("event deadline")
            .expect("event channel open");
        if let Output::Wire { from, to, message } = &output {
            let result = self.route(self.endpoint(*from), *to, message.clone());
            self.received.push(format!(
                "{}:{from:?}->{to:?}:{}",
                message.id(),
                result.err().unwrap_or("accepted")
            ));
        }
        output
    }

    pub async fn seen(&mut self, id: &str) {
        match self.next().await {
            Output::Seen { id: got, .. } => assert_eq!(id, got),
            other => panic!("expected Seen: {other:?}"),
        }
    }

    pub async fn work(&mut self, id: &str) -> Check<()> {
        match self.next().await {
            Output::Executed {
                member,
                id: got,
                result,
            } => {
                assert_eq!(member, Member::Core);
                assert_eq!(id, got);
                result
            }
            other => panic!("expected Executed: {other:?}"),
        }
    }

    pub async fn no_event_timeout(&mut self) -> bool {
        tokio::time::timeout(Duration::from_millis(20), self.rx.recv())
            .await
            .is_err()
    }

    // region join-cleanup
    pub async fn finish(&mut self) -> Vec<Joined> {
        let mut joined = Vec::new();
        // Independent cancellation never needs a business mailbox slot.
        for worker in self.workers.values() {
            let _ = worker.cancel.send(true);
        }
        for (member, mut worker) in std::mem::take(&mut self.workers) {
            let result = tokio::time::timeout(Duration::from_millis(100), &mut worker.join).await;
            let (outcome, aborted) = match result {
                Ok(Ok(outcome)) => (outcome, false),
                Ok(Err(error)) if error.is_panic() => ("panic", false),
                Ok(Err(_)) => ("join_error", false),
                Err(_) => {
                    worker.join.abort();
                    let _ = worker.join.await;
                    ("aborted", true)
                }
            };
            self.registry
                .lock()
                .unwrap()
                .stopped(member, outcome == "panic");
            joined.push(Joined {
                member,
                outcome: outcome.into(),
                aborted,
            });
        }
        joined
    }
    // endregion join-cleanup
}

fn mail_error<T>(error: mpsc::error::TrySendError<T>) -> &'static str {
    match error {
        mpsc::error::TrySendError::Full(_) => "mailbox_full",
        mpsc::error::TrySendError::Closed(_) => "mailbox_closed",
    }
}

// region actor-dispatch
#[allow(clippy::too_many_arguments)]
async fn actor(
    member: Member,
    mode: Mode,
    mut inbox: mpsc::Receiver<Command>,
    out: mpsc::Sender<Output>,
    mut cancel: watch::Receiver<bool>,
    mut start: watch::Receiver<bool>,
    registry: Arc<Mutex<Registry>>,
    root: PathBuf,
    _lifetime: TaskGuard,
) -> &'static str {
    if !*start.borrow() {
        tokio::select! { biased;
            _ = cancel.changed() => return "cancelled",
            _ = start.changed() => {}
        }
    }
    loop {
        let command = tokio::select! { biased;
            _ = cancel.changed() => return "cancelled",
            command = inbox.recv() => match command { Some(c) => c, None => return "closed" }
        };
        let event = match command {
            Command::Propose { id, plan } => Output::Wire {
                from: member,
                to: Member::Lead,
                message: Message::PlanRequest {
                    request_id: id,
                    plan,
                    ttl: 10,
                },
            },
            Command::Execute { id, plan } => {
                let result = registry.lock().unwrap().execute(member, &id, &plan, &root);
                Output::Executed { member, id, result }
            }
            Command::Deliver(message) => {
                if out
                    .try_send(Output::Seen {
                        member,
                        id: message.id().into(),
                    })
                    .is_err()
                {
                    return "outbound_full";
                }
                if let Message::ShutdownRequest { request_id, .. } = message {
                    if mode == Mode::Panic {
                        panic!("injected teammate panic");
                    }
                    if mode == Mode::Silent {
                        continue;
                    }
                    let decision = if mode == Mode::Reject {
                        Decision::Reject
                    } else {
                        Decision::Approve
                    };
                    let response = Output::Wire {
                        from: member,
                        to: Member::Lead,
                        message: Message::ShutdownResponse {
                            request_id,
                            decision,
                            feedback: if decision == Decision::Reject {
                                "unfinished review"
                            } else {
                                "local work released"
                            }
                            .into(),
                        },
                    };
                    if out.try_send(response).is_err() {
                        return "outbound_full";
                    }
                    if mode == Mode::Normal {
                        return "graceful";
                    }
                    if mode == Mode::IgnoreCancel {
                        std::future::pending::<()>().await;
                    }
                }
                continue;
            }
        };
        if out.try_send(event).is_err() {
            return "outbound_full";
        }
    }
}
// endregion actor-dispatch
