//! R03: an in-memory permission gate, using only the Rust standard library.
//! rustc --edition=2024 permissions.rs -o permissions
//! ./permissions approve  (the default scenario is approve)
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

const README: &str = "启动命令：cargo run\n";
static NEXT_WORKSPACE: AtomicU64 = AtomicU64::new(1);

// region calls
#[derive(Clone, Debug, PartialEq, Eq)]
enum Action {
    Read { path: String },
    Write { path: String, content: String },
    Unknown { name: String },
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ToolCall {
    call_id: String,
    action: Action,
}

#[derive(Debug, PartialEq, Eq)]
enum Permission {
    Allow,
    Deny(&'static str),
    AskApproval,
}

fn check_permission(call: &ToolCall) -> Permission {
    match &call.action {
        Action::Read { path } if path == "README.md" => Permission::Allow,
        Action::Write { path, content } if path == "notes/summary.txt" && content.len() <= 1024 => {
            Permission::AskApproval
        }
        _ => Permission::Deny("action_outside_policy"),
    }
}
// endregion calls

// region states
#[derive(Clone, Debug, PartialEq, Eq)]
struct ApprovalId {
    scope: PathBuf,
    sequence: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ApprovalRequest {
    id: ApprovalId,
    call: ToolCall,
}

enum HumanDecision {
    Approve,
    Decline,
}

#[derive(Debug)]
struct ToolResult {
    call_id: String,
    status: &'static str,
    content: String,
}

#[derive(Debug)]
enum Step {
    ToolResult(ToolResult),
    AwaitingApproval(ApprovalRequest),
    RejectedInput(&'static str),
}
// endregion states

struct Workspace(PathBuf);

impl Workspace {
    fn new() -> io::Result<Self> {
        let stamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap();
        let serial = NEXT_WORKSPACE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "agent-r03-{}-{}-{serial}",
            std::process::id(),
            stamp.as_nanos()
        ));
        // Exclusive creation: never adopt or clean up an existing directory.
        fs::create_dir(&root)?;
        let workspace = Self(root);
        fs::create_dir(workspace.0.join("notes"))?;
        fs::write(workspace.0.join("README.md"), README)?;
        Ok(workspace)
    }
}

impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Default)]
struct Counters {
    read_attempts: usize,
    write_attempts: usize,
    write_successes: usize,
    tool_results: usize,
}

struct Runtime {
    workspace: Workspace,
    seen: HashSet<String>,
    pending: Option<ApprovalRequest>,
    next_approval: u64,
    counters: Counters,
}

impl Runtime {
    fn new() -> io::Result<Self> {
        Ok(Self {
            workspace: Workspace::new()?,
            seen: HashSet::new(),
            pending: None,
            next_approval: 0,
            counters: Counters::default(),
        })
    }

    fn result(&mut self, call: &ToolCall, status: &'static str, content: String) -> Step {
        self.counters.tool_results += 1;
        Step::ToolResult(ToolResult {
            call_id: call.call_id.clone(),
            status,
            content,
        })
    }

    // region submit
    fn submit(&mut self, call: ToolCall) -> Step {
        if self.pending.is_some() {
            return Step::RejectedInput("approval_pending");
        }
        if !self.seen.insert(call.call_id.clone()) {
            return Step::RejectedInput("duplicate_call_id");
        }
        match check_permission(&call) {
            Permission::Deny(reason) => self.result(&call, "denied", reason.into()),
            Permission::Allow => self.execute(&call),
            Permission::AskApproval => {
                self.next_approval += 1;
                let request = ApprovalRequest {
                    id: ApprovalId {
                        scope: self.workspace.0.clone(),
                        sequence: self.next_approval,
                    },
                    call,
                };
                self.pending = Some(request.clone());
                Step::AwaitingApproval(request)
            }
        }
    }
    // endregion submit

    // region resume
    // Only the trusted UI/CLI adapter calls this method, never a model tool.
    fn resume(&mut self, reply: &ApprovalRequest, decision: HumanDecision) -> Step {
        let Some(pending) = self.pending.as_ref() else {
            return Step::RejectedInput("no_pending_approval");
        };
        // Equality covers scope, approval sequence, call_id and ALL arguments.
        if pending != reply {
            return Step::RejectedInput("approval_mismatch");
        }
        // Consume before I/O, even if execution fails. Execute the saved call.
        let saved = self.pending.take().unwrap();
        match decision {
            HumanDecision::Decline => self.result(&saved.call, "declined", "human_declined".into()),
            HumanDecision::Approve => self.execute(&saved.call),
        }
    }
    // endregion resume

    // region execute
    fn execute(&mut self, call: &ToolCall) -> Step {
        let operation = match &call.action {
            Action::Read { path } => {
                self.counters.read_attempts += 1;
                fs::read_to_string(self.workspace.0.join(path))
            }
            Action::Write { path, content } => {
                self.counters.write_attempts += 1;
                fs::write(self.workspace.0.join(path), content).map(|()| {
                    self.counters.write_successes += 1;
                    "summary_written".into()
                })
            }
            Action::Unknown { .. } => unreachable!("policy denies unknown tools"),
        };
        match operation {
            Ok(content) => self.result(call, "ok", content),
            // Stable teaching output; avoid platform-specific OS error strings.
            Err(_) => self.result(call, "tool_error", "filesystem_operation_failed".into()),
        }
    }
    // endregion execute
}

fn read_call() -> ToolCall {
    ToolCall {
        call_id: "read-1".into(),
        action: Action::Read {
            path: "README.md".into(),
        },
    }
}

fn write_call() -> ToolCall {
    ToolCall {
        call_id: "write-1".into(),
        action: Action::Write {
            path: "notes/summary.txt".into(),
            content: README.into(),
        },
    }
}

fn report(step: &Step) {
    match step {
        Step::ToolResult(result) => println!(
            "tool_result call_id={} status={} content={:?}",
            result.call_id, result.status, result.content
        ),
        Step::AwaitingApproval(request) => println!(
            "awaiting_approval approval={} scope=this_session call_id={} action={:?}",
            request.id.sequence, request.call.call_id, request.call.action
        ),
        Step::RejectedInput(reason) => println!("rejected_input reason={reason}"),
    }
}

fn main() -> io::Result<()> {
    let scenario = std::env::args().nth(1).unwrap_or_else(|| "approve".into());
    if ![
        "read",
        "deny",
        "invalid-path",
        "unknown",
        "wait",
        "approve",
        "decline",
        "tamper",
        "replay",
        "write-error",
    ]
    .contains(&scenario.as_str())
    {
        eprintln!(
            "usage: permissions [read|deny|invalid-path|unknown|wait|approve|decline|tamper|replay|write-error]"
        );
        std::process::exit(2);
    }
    let mut runtime = Runtime::new()?;
    println!("scenario={scenario} source=scripted_tool_requests storage=in_memory");
    report(&runtime.submit(read_call()));
    if scenario != "read" {
        let mut call = write_call();
        match scenario.as_str() {
            "deny" => {
                call.action = Action::Write {
                    path: "README.md".into(),
                    content: "replace project instructions".into(),
                };
            }
            "invalid-path" => {
                call.action = Action::Write {
                    path: "../outside.txt".into(),
                    content: "outside".into(),
                };
            }
            "unknown" => {
                call.action = Action::Unknown {
                    name: "bash".into(),
                }
            }
            "write-error" => {
                // A directory at the target forces a real write failure.
                fs::create_dir(runtime.workspace.0.join("notes/summary.txt"))?;
            }
            _ => {}
        }
        let step = runtime.submit(call);
        report(&step);
        if let Step::AwaitingApproval(request) = step {
            match scenario.as_str() {
                "wait" => {}
                "decline" => report(&runtime.resume(&request, HumanDecision::Decline)),
                "tamper" => {
                    let mut changed = request.clone();
                    if let Action::Write { content, .. } = &mut changed.call.action {
                        *content = "substituted content".into();
                    }
                    report(&runtime.resume(&changed, HumanDecision::Approve));
                }
                _ => {
                    report(&runtime.resume(&request, HumanDecision::Approve));
                    if scenario == "replay" || scenario == "write-error" {
                        report(&runtime.resume(&request, HumanDecision::Approve));
                    }
                }
            }
        }
    }
    let summary = fs::read_to_string(runtime.workspace.0.join("notes/summary.txt")).ok();
    let readme_unchanged = fs::read_to_string(runtime.workspace.0.join("README.md"))? == README;
    assert!(readme_unchanged);
    let expected_written = scenario == "approve" || scenario == "replay";
    assert_eq!(summary.as_deref(), expected_written.then_some(README));
    let counts = &runtime.counters;
    println!(
        "stats read_attempts={} write_attempts={} write_successes={} tool_results={} pending={} summary_matches={} readme_unchanged={}",
        counts.read_attempts,
        counts.write_attempts,
        counts.write_successes,
        counts.tool_results,
        runtime.pending.is_some(),
        summary.as_deref() == Some(README),
        readme_unchanged
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn waiting(runtime: &mut Runtime) -> ApprovalRequest {
        match runtime.submit(write_call()) {
            Step::AwaitingApproval(request) => request,
            other => panic!("expected approval, got {other:?}"),
        }
    }

    fn status(step: Step, expected: &str) {
        match step {
            Step::ToolResult(result) => {
                assert_eq!(result.call_id, "write-1");
                assert_eq!(result.status, expected);
            }
            other => panic!("expected result, got {other:?}"),
        }
    }

    #[test]
    fn deny_unknown_paths_and_oversized_content_before_any_io() {
        for action in [
            Action::Unknown {
                name: "bash".into(),
            },
            Action::Read {
                path: "../README.md".into(),
            },
            Action::Read {
                path: "/etc/passwd".into(),
            },
            Action::Write {
                path: "README.md".into(),
                content: "changed".into(),
            },
            Action::Write {
                path: "../outside.txt".into(),
                content: "changed".into(),
            },
            Action::Write {
                path: "notes/summary.txt".into(),
                content: "x".repeat(1025),
            },
        ] {
            let mut runtime = Runtime::new().unwrap();
            status(
                runtime.submit(ToolCall {
                    call_id: "write-1".into(),
                    action,
                }),
                "denied",
            );
            assert_eq!(runtime.counters.read_attempts, 0);
            assert_eq!(runtime.counters.write_attempts, 0);
            assert_eq!(
                fs::read_to_string(runtime.workspace.0.join("README.md")).unwrap(),
                README
            );
            assert!(!runtime.workspace.0.join("notes/summary.txt").exists());
        }
    }

    #[test]
    fn waiting_blocks_new_calls_and_has_no_tool_result() {
        let mut runtime = Runtime::new().unwrap();
        waiting(&mut runtime);
        assert_eq!(runtime.counters.tool_results, 0);
        assert_eq!(runtime.counters.write_attempts, 0);
        assert!(matches!(
            runtime.submit(read_call()),
            Step::RejectedInput("approval_pending")
        ));
        assert_eq!(runtime.counters.read_attempts, 0);
    }

    #[test]
    fn approval_binds_every_field_and_preserves_original_pending_call() {
        let mut runtime = Runtime::new().unwrap();
        let original = waiting(&mut runtime);
        let mut variants = Vec::new();
        let mut changed = original.clone();
        changed.id.scope = PathBuf::from("another_workspace");
        variants.push(changed);
        let mut changed = original.clone();
        changed.id.sequence += 1;
        variants.push(changed);
        let mut changed = original.clone();
        changed.call.call_id = "write-2".into();
        variants.push(changed);
        let mut changed = original.clone();
        changed.call.action = Action::Read {
            path: "README.md".into(),
        };
        variants.push(changed);
        for (path, content) in [("README.md", README), ("notes/summary.txt", "different")] {
            let mut changed = original.clone();
            changed.call.action = Action::Write {
                path: path.into(),
                content: content.into(),
            };
            variants.push(changed);
        }
        for reply in variants {
            assert!(matches!(
                runtime.resume(&reply, HumanDecision::Approve),
                Step::RejectedInput("approval_mismatch")
            ));
            assert_eq!(runtime.pending.as_ref(), Some(&original));
            assert_eq!(runtime.counters.write_attempts, 0);
        }
        status(runtime.resume(&original, HumanDecision::Approve), "ok");
        assert_eq!(
            fs::read_to_string(runtime.workspace.0.join("notes/summary.txt")).unwrap(),
            README
        );
        assert!(matches!(
            runtime.resume(&original, HumanDecision::Approve),
            Step::RejectedInput("no_pending_approval")
        ));
        assert!(matches!(
            runtime.submit(write_call()),
            Step::RejectedInput("duplicate_call_id")
        ));
        assert_eq!(runtime.counters.write_attempts, 1);
    }

    #[test]
    fn another_session_cannot_use_the_same_call_and_sequence() {
        let mut first = Runtime::new().unwrap();
        let foreign = waiting(&mut first);
        let mut second = Runtime::new().unwrap();
        let local = waiting(&mut second);
        assert_eq!(foreign.call, local.call);
        assert_eq!(foreign.id.sequence, local.id.sequence);
        assert!(matches!(
            second.resume(&foreign, HumanDecision::Approve),
            Step::RejectedInput("approval_mismatch")
        ));
        assert_eq!(second.counters.write_attempts, 0);
    }

    #[test]
    fn decline_returns_a_paired_result_without_writing() {
        let mut runtime = Runtime::new().unwrap();
        let request = waiting(&mut runtime);
        status(runtime.resume(&request, HumanDecision::Decline), "declined");
        assert_eq!(runtime.counters.write_attempts, 0);
        assert!(runtime.pending.is_none());
    }

    #[test]
    fn failure_consumes_approval_and_does_not_claim_success() {
        let mut runtime = Runtime::new().unwrap();
        fs::create_dir(runtime.workspace.0.join("notes/summary.txt")).unwrap();
        let request = waiting(&mut runtime);
        status(
            runtime.resume(&request, HumanDecision::Approve),
            "tool_error",
        );
        assert!(matches!(
            runtime.resume(&request, HumanDecision::Approve),
            Step::RejectedInput("no_pending_approval")
        ));
        assert_eq!(runtime.counters.write_attempts, 1);
        assert_eq!(runtime.counters.write_successes, 0);
    }
}
