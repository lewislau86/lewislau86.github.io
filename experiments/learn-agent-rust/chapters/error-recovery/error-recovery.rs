//! R11: typed failures, bounded retries and in-memory continuation.
//! rustc --edition=2024 -D warnings error-recovery.rs -o recovery
//! ./recovery backoff [NEW_WORKSPACE_DIRECTORY]
//! Faults and time are injected; successful file operations are real.
use std::collections::VecDeque;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const README: &str = "cargo run\n";
const ENTRY: &str = "startup=cargo run\n";

// region errors
// region failure-types
#[derive(Clone, Debug, PartialEq, Eq)]
enum Failure {
    Transient { retry_after_ms: Option<u64> },
    InvalidInput,
    PermissionDenied,
    Permanent,
    OutcomeUnknown,
}

fn read_error(error: io::Error) -> Failure {
    match error.kind() {
        io::ErrorKind::Interrupted | io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut => {
            Failure::Transient {
                retry_after_ms: None,
            }
        }
        io::ErrorKind::PermissionDenied => Failure::PermissionDenied,
        io::ErrorKind::InvalidInput | io::ErrorKind::InvalidData => Failure::InvalidInput,
        _ => Failure::Permanent,
    }
}

// endregion failure-types
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stop {
    Completed,
    Failed,
    AttemptLimit,
    CallBudget,
    WaitBudget,
    Deadline,
    Cancelled,
    NeedsReconciliation,
}

impl Stop {
    fn label(self) -> &'static str {
        match self {
            Self::Completed => "completed",
            Self::Failed => "failed",
            Self::AttemptLimit => "attempt_limit",
            Self::CallBudget => "call_budget",
            Self::WaitBudget => "wait_budget",
            Self::Deadline => "deadline",
            Self::Cancelled => "cancelled",
            Self::NeedsReconciliation => "needs_reconciliation",
        }
    }
}
// endregion errors

// region budget
#[derive(Clone, Copy)]
struct Limits {
    calls: u32,
    wait_ms: u64,
    deadline_ms: u64,
}

struct Ledger {
    limits: Limits,
    calls: u32,
    waited_ms: u64,
    now_ms: u64,
}

impl Ledger {
    fn new(limits: Limits) -> Self {
        Self {
            limits,
            calls: 0,
            waited_ms: 0,
            now_ms: 0,
        }
    }

    // region ledger
    fn ready(&self) -> Result<(), Stop> {
        if self.now_ms >= self.limits.deadline_ms {
            return Err(Stop::Deadline);
        }
        if self.calls >= self.limits.calls {
            return Err(Stop::CallBudget);
        }
        Ok(())
    }

    fn admit(&mut self) -> Result<u64, Stop> {
        self.ready()?;
        let started = self.now_ms;
        self.calls += 1; // Charge before dispatch, including failed attempts.
        self.now_ms = self.now_ms.saturating_add(10); // Injected operation duration.
        Ok(started)
    }

    fn wait_until(&mut self, due_ms: u64) -> Result<(), Stop> {
        if self.now_ms >= self.limits.deadline_ms || due_ms >= self.limits.deadline_ms {
            return Err(Stop::Deadline);
        }
        let remaining = due_ms.saturating_sub(self.now_ms);
        if remaining > self.limits.wait_ms.saturating_sub(self.waited_ms) {
            return Err(Stop::WaitBudget);
        }
        self.waited_ms += remaining;
        self.now_ms = self.now_ms.max(due_ms);
        Ok(())
    }
    // endregion ledger
}

// region policy
#[derive(Clone, Copy)]
struct Policy {
    max_attempts: u32, // Includes the initial attempt.
    base_ms: u64,
    cap_ms: u64,
}

impl Policy {
    fn delay(self, failed_attempt: u32, retry_after_ms: Option<u64>) -> u64 {
        let factor = 1_u64
            .checked_shl(failed_attempt.saturating_sub(1))
            .unwrap_or(u64::MAX);
        let backoff = self.base_ms.saturating_mul(factor).min(self.cap_ms);
        backoff.max(retry_after_ms.unwrap_or(0))
    }
}
// endregion policy
// endregion budget

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Operation {
    Read,
    Append,
}

#[derive(Clone)]
struct Call {
    id: &'static str,
    operation: Operation,
    path: &'static str,
}

impl Call {
    fn validate(&self) -> Result<(), Failure> {
        let expected = match self.operation {
            Operation::Read => "README.md",
            Operation::Append => "events.log",
        };
        if self.path == expected {
            Ok(())
        } else {
            Err(Failure::InvalidInput)
        }
    }
}

// region state
struct Recovery {
    call: Call,
    attempts: u32,
    pending_due_ms: Option<u64>,
    last_failure: Option<Failure>,
    terminal: Option<Stop>,
    result_count: u32,
    value: Option<String>,
}

impl Recovery {
    fn new(call: Call) -> Self {
        Self {
            call,
            attempts: 0,
            pending_due_ms: None,
            last_failure: None,
            terminal: None,
            result_count: 0,
            value: None,
        }
    }

    fn finish(&mut self, stop: Stop, trace: &mut Vec<String>) {
        if self.terminal.is_none() {
            self.terminal = Some(stop);
            self.pending_due_ms = None;
            self.result_count += 1;
            trace.push(format!(
                "result call_id={} status={}",
                self.call.id,
                stop.label()
            ));
        }
    }
}
// endregion state

#[derive(Clone, Copy)]
enum Fault {
    Transient,
    RetryAfter(u64),
    Permanent,
    LoseReply,
}

struct Workspace {
    root: PathBuf,
    keep: bool,
    read_successes: u32,
    append_successes: u32,
}

impl Workspace {
    fn new(directory: Option<&Path>) -> io::Result<Self> {
        let root = match directory {
            Some(path) => path.to_path_buf(),
            None => std::env::temp_dir().join(format!(
                "agent-r11-{}-{}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .expect("clock before epoch")
                    .as_nanos()
            )),
        };
        fs::create_dir(&root)?; // Existing directories are never overwritten.
        let workspace = Self {
            root,
            keep: directory.is_some(),
            read_successes: 0,
            append_successes: 0,
        };
        fs::write(workspace.root.join("README.md"), README)?;
        Ok(workspace)
    }

    // region tool
    fn execute(&mut self, call: &Call, fault: Option<Fault>) -> Result<String, Failure> {
        match fault {
            Some(Fault::Transient) => {
                return Err(Failure::Transient {
                    retry_after_ms: None,
                });
            }
            Some(Fault::RetryAfter(ms)) => {
                return Err(Failure::Transient {
                    retry_after_ms: Some(ms),
                });
            }
            Some(Fault::Permanent) => return Err(Failure::Permanent),
            _ => {}
        }
        match call.operation {
            Operation::Read => {
                let value = fs::read_to_string(self.root.join(call.path)).map_err(read_error)?;
                self.read_successes += 1;
                Ok(value)
            }
            Operation::Append => {
                let mut file = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(self.root.join(call.path))
                    .map_err(|_| Failure::OutcomeUnknown)?;
                file.write_all(ENTRY.as_bytes())
                    .map_err(|_| Failure::OutcomeUnknown)?;
                self.append_successes += 1;
                if matches!(fault, Some(Fault::LoseReply)) {
                    return Err(Failure::OutcomeUnknown);
                }
                Ok("appended".into())
            }
        }
    }
    // endregion tool
}

impl Drop for Workspace {
    fn drop(&mut self) {
        if !self.keep {
            let _ = fs::remove_dir_all(&self.root);
        }
    }
}

struct Driver<'a> {
    ledger: &'a mut Ledger,
    workspace: &'a mut Workspace,
    faults: &'a mut VecDeque<Fault>,
    trace: &'a mut Vec<String>,
    policy: Policy,
    authorized: bool,
    cancelled: bool,
}

impl Driver<'_> {
    // region drive
    fn drive(&mut self, state: &mut Recovery, pause_after_schedule: bool) {
        if state.terminal.is_some() {
            return;
        }
        loop {
            // region admission
            if self.cancelled {
                state.finish(Stop::Cancelled, self.trace);
                return;
            }
            if let Err(error) = state.call.validate() {
                state.last_failure = Some(error);
                state.finish(Stop::Failed, self.trace);
                return;
            }
            if !self.authorized {
                state.last_failure = Some(Failure::PermissionDenied);
                state.finish(Stop::Failed, self.trace);
                return;
            }
            if state.attempts >= self.policy.max_attempts {
                state.finish(Stop::AttemptLimit, self.trace);
                return;
            }
            if let Err(stop) = self.ledger.ready() {
                state.finish(stop, self.trace);
                return;
            }
            if let Some(due) = state.pending_due_ms {
                if let Err(stop) = self.ledger.wait_until(due) {
                    state.finish(stop, self.trace);
                    return;
                }
                self.trace.push(format!(
                    "wake call_id={} now_ms={}",
                    state.call.id, self.ledger.now_ms
                ));
                state.pending_due_ms = None;
            }
            let started = match self.ledger.admit() {
                Ok(started) => started,
                Err(stop) => {
                    state.finish(stop, self.trace);
                    return;
                }
            };
            state.attempts += 1;
            self.trace.push(format!(
                "attempt call_id={} attempt={} started_ms={}",
                state.call.id, state.attempts, started
            ));
            // endregion admission
            match self.workspace.execute(&state.call, self.faults.pop_front()) {
                Ok(value) => {
                    state.value = Some(value);
                    state.finish(Stop::Completed, self.trace);
                    return;
                }
                Err(error) => {
                    self.trace
                        .push(format!("failure call_id={} kind={error:?}", state.call.id));
                    state.last_failure = Some(error.clone());
                    // region retry
                    match error {
                        Failure::Transient { retry_after_ms }
                            if state.call.operation == Operation::Read =>
                        {
                            if state.attempts >= self.policy.max_attempts {
                                state.finish(Stop::AttemptLimit, self.trace);
                                return;
                            }
                            if self.ledger.calls >= self.ledger.limits.calls {
                                state.finish(Stop::CallBudget, self.trace);
                                return;
                            }
                            let delay = self.policy.delay(state.attempts, retry_after_ms);
                            let due = self.ledger.now_ms.saturating_add(delay);
                            state.pending_due_ms = Some(due);
                            self.trace.push(format!(
                                "schedule call_id={} delay_ms={delay} due_ms={due}",
                                state.call.id
                            ));
                            if pause_after_schedule {
                                return;
                            }
                        }
                        Failure::OutcomeUnknown | Failure::Transient { .. } => {
                            state.finish(Stop::NeedsReconciliation, self.trace);
                            return;
                        }
                        _ => {
                            state.finish(Stop::Failed, self.trace);
                            return;
                        }
                    }
                    // endregion retry
                }
            }
        }
    }
    // endregion drive
}

fn policy() -> Policy {
    Policy {
        max_attempts: 3,
        base_ms: 100,
        cap_ms: 400,
    }
}
fn limits() -> Limits {
    Limits {
        calls: 6,
        wait_ms: 600,
        deadline_ms: 2000,
    }
}
fn read_call(id: &'static str) -> Call {
    Call {
        id,
        operation: Operation::Read,
        path: "README.md",
    }
}

const SCENARIOS: &[&str] = &[
    "normal",
    "transient",
    "backoff",
    "attempt-limit",
    "call-budget",
    "wait-budget",
    "deadline",
    "retry-after",
    "retry-after-too-long",
    "permission-denied",
    "invalid-input",
    "missing-file",
    "permanent",
    "append-ok",
    "append-unknown",
    "resume-budget",
    "resume-cooldown",
    "resume-expired",
    "cancelled-backoff",
    "revoked-backoff",
    "shared-budget",
];

fn experiment(name: &str, directory: Option<&Path>) -> io::Result<()> {
    let mut workspace = Workspace::new(directory)?;
    let mut call = read_call("read-1");
    let mut configured_limits = limits();
    let mut faults = VecDeque::new();
    let mut allowed = true;
    match name {
        "transient" | "resume-cooldown" | "resume-expired" | "cancelled-backoff"
        | "revoked-backoff" => faults.push_back(Fault::Transient),
        "backoff" | "wait-budget" | "shared-budget" => {
            faults.extend([Fault::Transient, Fault::Transient])
        }
        "attempt-limit" => faults.extend([Fault::Transient; 3]),
        "call-budget" | "resume-budget" => {
            configured_limits.calls = 2;
            faults.extend([Fault::Transient; 2]);
        }
        "deadline" => {
            configured_limits.deadline_ms = 100;
            faults.push_back(Fault::Transient);
        }
        "retry-after" => faults.push_back(Fault::RetryAfter(250)),
        "retry-after-too-long" => faults.push_back(Fault::RetryAfter(2000)),
        "permission-denied" => allowed = false,
        "invalid-input" => call.path = "../README.md",
        "missing-file" => fs::remove_file(workspace.root.join("README.md"))?,
        "permanent" => faults.push_back(Fault::Permanent),
        "append-ok" | "append-unknown" => {
            call = Call {
                id: "append-1",
                operation: Operation::Append,
                path: "events.log",
            };
            if name == "append-unknown" {
                faults.push_back(Fault::LoseReply);
            }
        }
        _ => {}
    }
    if name == "wait-budget" {
        configured_limits.wait_ms = 150;
    }
    if name == "resume-expired" {
        configured_limits.deadline_ms = 150;
    }
    if name == "shared-budget" {
        configured_limits.calls = 3;
    }
    let paused = matches!(
        name,
        "resume-budget"
            | "resume-cooldown"
            | "resume-expired"
            | "cancelled-backoff"
            | "revoked-backoff"
    );
    let mut ledger = Ledger::new(configured_limits);
    let mut state = Recovery::new(call);
    let mut trace = Vec::new();
    let mut driver = Driver {
        ledger: &mut ledger,
        workspace: &mut workspace,
        faults: &mut faults,
        trace: &mut trace,
        policy: policy(),
        authorized: allowed,
        cancelled: false,
    };
    driver.drive(&mut state, paused);
    if paused {
        assert!(state.terminal.is_none());
        driver.trace.push(format!(
            "pause attempts={} calls={} waited_ms={} due_ms={}",
            state.attempts,
            driver.ledger.calls,
            driver.ledger.waited_ms,
            state.pending_due_ms.unwrap()
        ));
        if name == "resume-expired" {
            driver.ledger.now_ms = 200;
        }
        if name == "cancelled-backoff" {
            driver.cancelled = true;
        }
        if name == "revoked-backoff" {
            driver.authorized = false;
        }
        // region resume
        let mut resumed = state; // Ownership transfer; retain attempts and pending due time.
        driver.drive(&mut resumed, false); // Same task-wide ledger, no reset.
        state = resumed;
        // endregion resume
    }
    let mut result_count = state.result_count;
    let mut logical_calls = 1;
    if name == "shared-budget" {
        assert_eq!(state.terminal, Some(Stop::Completed));
        let mut next = Recovery::new(read_call("read-2"));
        driver.drive(&mut next, false); // New call, same exhausted task budget.
        result_count += next.result_count;
        logical_calls += 1;
        state = next;
    }
    driver.drive(&mut state, false); // Terminal reentry must do no work and emit no result.
    let appended = match fs::read_to_string(workspace.root.join("events.log")) {
        Ok(value) => value.lines().count(),
        Err(error) if error.kind() == io::ErrorKind::NotFound => 0,
        Err(error) => return Err(error),
    };
    println!("scenario={name}");
    println!("clock=virtual attempt_duration_ms=10 jitter=disabled");
    println!(
        "limits calls={} wait_ms={} deadline_ms={} max_attempts={}",
        configured_limits.calls,
        configured_limits.wait_ms,
        configured_limits.deadline_ms,
        policy().max_attempts
    );
    for (index, line) in trace.iter().enumerate() {
        println!("trace[{index}] {line}");
    }
    println!("last_failure={:?}", state.last_failure);
    println!(
        "read_value_matches={}",
        state.value.as_deref() == Some(README)
    );
    println!(
        "stats stop={} calls={} last_attempts={} waited_ms={} now_ms={} results={} logical_calls={} reads={} appends={} lines={} paused={}",
        state.terminal.unwrap().label(),
        ledger.calls,
        state.attempts,
        ledger.waited_ms,
        ledger.now_ms,
        result_count,
        logical_calls,
        workspace.read_successes,
        workspace.append_successes,
        appended,
        paused
    );
    Ok(())
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let name = args.first().map(String::as_str).unwrap_or("normal");
    if args.len() > 2 || !SCENARIOS.contains(&name) {
        eprintln!(
            "usage: recovery [{}] [NEW_WORKSPACE_DIRECTORY]",
            SCENARIOS.join("|")
        );
        std::process::exit(2);
    }
    if let Err(error) = experiment(name, args.get(1).map(Path::new)) {
        eprintln!("workspace error: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(faults: VecDeque<Fault>, configured: Limits) -> (Recovery, Ledger, Vec<String>) {
        let mut faults = faults;
        let mut workspace = Workspace::new(None).unwrap();
        let mut state = Recovery::new(read_call("read-1"));
        let mut ledger = Ledger::new(configured);
        let mut trace = Vec::new();
        Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        }
        .drive(&mut state, false);
        (state, ledger, trace)
    }

    #[test]
    fn backoff_caps_and_handles_large_attempts() {
        assert_eq!(
            [1, 2, 3, 4, 1000].map(|n| policy().delay(n, None)),
            [100, 200, 400, 400, 400]
        );
        assert_eq!(policy().delay(1, Some(2000)), 2000);
        assert_eq!(policy().delay(2, Some(1)), 200);
    }

    #[test]
    fn io_classification_is_conservative() {
        assert_eq!(
            read_error(io::ErrorKind::NotFound.into()),
            Failure::Permanent
        );
        assert_eq!(
            read_error(io::ErrorKind::PermissionDenied.into()),
            Failure::PermissionDenied
        );
        assert_eq!(
            read_error(io::ErrorKind::InvalidData.into()),
            Failure::InvalidInput
        );
        assert!(matches!(
            read_error(io::ErrorKind::TimedOut.into()),
            Failure::Transient { .. }
        ));
    }

    #[test]
    fn max_attempts_includes_first_dispatch() {
        let (state, ledger, _) = run(VecDeque::from([Fault::Transient; 4]), limits());
        assert_eq!(state.terminal, Some(Stop::AttemptLimit));
        assert_eq!(ledger.calls, 3);
        assert_eq!(ledger.waited_ms, 300);
        assert_eq!(state.result_count, 1);
    }

    #[test]
    fn failed_attempts_consume_total_call_budget() {
        let (state, ledger, _) = run(
            VecDeque::from([Fault::Transient; 3]),
            Limits {
                calls: 2,
                ..limits()
            },
        );
        assert_eq!(state.terminal, Some(Stop::CallBudget));
        assert_eq!((ledger.calls, ledger.waited_ms), (2, 100));
    }

    #[test]
    fn rejected_wait_is_not_partially_charged() {
        let (state, ledger, _) = run(
            VecDeque::from([Fault::Transient; 2]),
            Limits {
                wait_ms: 150,
                ..limits()
            },
        );
        assert_eq!(state.terminal, Some(Stop::WaitBudget));
        assert_eq!(
            (ledger.calls, ledger.waited_ms, ledger.now_ms),
            (2, 100, 120)
        );
    }

    #[test]
    fn deadline_equality_rejects_next_attempt() {
        let (state, ledger, _) = run(
            VecDeque::from([Fault::Transient]),
            Limits {
                deadline_ms: 110,
                ..limits()
            },
        );
        assert_eq!(state.terminal, Some(Stop::Deadline));
        assert_eq!((ledger.calls, ledger.waited_ms), (1, 0));
    }

    #[test]
    fn permanent_error_does_not_wait() {
        let (state, ledger, _) = run(VecDeque::from([Fault::Permanent]), limits());
        assert_eq!(state.terminal, Some(Stop::Failed));
        assert_eq!((ledger.calls, ledger.waited_ms), (1, 0));
    }

    #[test]
    fn continuation_preserves_attempts_due_time_and_ledger() {
        let mut workspace = Workspace::new(None).unwrap();
        let mut ledger = Ledger::new(limits());
        let mut faults = VecDeque::from([Fault::Transient; 3]);
        let mut trace = Vec::new();
        let mut state = Recovery::new(read_call("read-1"));
        let mut driver = Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        };
        driver.drive(&mut state, true);
        assert_eq!(state.pending_due_ms, Some(110));
        driver.ledger.now_ms = 60; // Scheduler already used part of the cooldown.
        driver.drive(&mut state, false);
        assert_eq!(state.terminal, Some(Stop::AttemptLimit));
        assert_eq!((driver.ledger.calls, driver.ledger.waited_ms), (3, 250));
    }

    #[test]
    fn cancellation_and_revocation_prevent_wait_and_dispatch() {
        for revoked in [false, true] {
            let mut workspace = Workspace::new(None).unwrap();
            let mut ledger = Ledger::new(limits());
            let mut faults = VecDeque::from([Fault::Transient]);
            let mut trace = Vec::new();
            let mut state = Recovery::new(read_call("read-1"));
            let mut driver = Driver {
                ledger: &mut ledger,
                workspace: &mut workspace,
                faults: &mut faults,
                trace: &mut trace,
                policy: policy(),
                authorized: true,
                cancelled: false,
            };
            driver.drive(&mut state, true);
            driver.cancelled = !revoked;
            driver.authorized = !revoked;
            driver.drive(&mut state, false);
            assert_eq!(
                state.terminal,
                Some(if revoked {
                    Stop::Failed
                } else {
                    Stop::Cancelled
                })
            );
            assert_eq!((driver.ledger.calls, driver.ledger.waited_ms), (1, 0));
        }
    }

    #[test]
    fn ambiguous_append_is_never_replayed() {
        let mut workspace = Workspace::new(None).unwrap();
        let mut ledger = Ledger::new(limits());
        let mut faults = VecDeque::from([Fault::LoseReply]);
        let mut trace = Vec::new();
        let mut state = Recovery::new(Call {
            id: "append-1",
            operation: Operation::Append,
            path: "events.log",
        });
        let mut driver = Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        };
        driver.drive(&mut state, false);
        driver.drive(&mut state, false);
        assert_eq!(state.terminal, Some(Stop::NeedsReconciliation));
        assert_eq!(state.result_count, 1);
        assert_eq!(driver.ledger.calls, 1);
        assert_eq!(
            fs::read_to_string(driver.workspace.root.join("events.log")).unwrap(),
            ENTRY
        );
    }

    #[test]
    fn new_call_inherits_exhausted_task_budget() {
        let mut workspace = Workspace::new(None).unwrap();
        let mut ledger = Ledger::new(Limits {
            calls: 1,
            ..limits()
        });
        let mut faults = VecDeque::new();
        let mut trace = Vec::new();
        let mut driver = Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        };
        let mut first = Recovery::new(read_call("read-1"));
        let mut second = Recovery::new(read_call("read-2"));
        driver.drive(&mut first, false);
        driver.drive(&mut second, false);
        assert_eq!(first.terminal, Some(Stop::Completed));
        assert_eq!(second.terminal, Some(Stop::CallBudget));
        assert_eq!(second.attempts, 0);
        assert_eq!(driver.workspace.read_successes, 1);
    }

    #[test]
    fn exhausted_shared_budget_skips_pending_wait() {
        let mut workspace = Workspace::new(None).unwrap();
        let mut ledger = Ledger::new(Limits {
            calls: 2,
            ..limits()
        });
        let mut faults = VecDeque::from([Fault::Transient]);
        let mut trace = Vec::new();
        let mut state = Recovery::new(read_call("read-1"));
        let mut driver = Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        };
        driver.drive(&mut state, true);
        assert_eq!(state.pending_due_ms, Some(110));
        let mut other = Recovery::new(read_call("read-2"));
        driver.drive(&mut other, false);
        assert_eq!(other.terminal, Some(Stop::Completed));
        driver.drive(&mut state, false);
        assert_eq!(state.terminal, Some(Stop::CallBudget));
        assert_eq!(
            (
                driver.ledger.calls,
                driver.ledger.waited_ms,
                driver.ledger.now_ms
            ),
            (2, 0, 20)
        );
        assert_eq!(driver.workspace.read_successes, 1);
    }

    #[test]
    fn transient_label_alone_does_not_authorize_write_retry() {
        let mut workspace = Workspace::new(None).unwrap();
        let mut ledger = Ledger::new(limits());
        let mut faults = VecDeque::from([Fault::Transient]);
        let mut trace = Vec::new();
        let mut state = Recovery::new(Call {
            id: "append-1",
            operation: Operation::Append,
            path: "events.log",
        });
        Driver {
            ledger: &mut ledger,
            workspace: &mut workspace,
            faults: &mut faults,
            trace: &mut trace,
            policy: policy(),
            authorized: true,
            cancelled: false,
        }
        .drive(&mut state, false);
        assert_eq!(state.terminal, Some(Stop::NeedsReconciliation));
        assert_eq!((ledger.calls, ledger.waited_ms), (1, 0));
        assert!(!workspace.root.join("events.log").exists());
    }
}
