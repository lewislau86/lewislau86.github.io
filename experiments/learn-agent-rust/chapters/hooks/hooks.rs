//! R04: lifecycle hooks, a real file tool, and bounded owned hook workers.
//! rustc --edition=2024 -D warnings hooks.rs -o hooks
//! ./hooks normal
use std::fs;
use std::io;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const PROMPT: &str = "把启动命令写入已批准的摘要";
const SUMMARY: &str = "启动命令：cargo run\n";

// region contracts
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Event {
    UserPromptSubmit,
    PreToolUse,
    PostToolUse,
    Stop,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ToolCall {
    call_id: String,
    path: String,
    content: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ToolResult {
    call_id: String,
    status: &'static str,
}

struct HookContext<'a> {
    prompt: &'a str,
    call: Option<&'a ToolCall>,
    result: Option<&'a ToolResult>,
    stop_reason: Option<&'a str>,
}

#[derive(Debug, PartialEq, Eq)]
enum Decision {
    Continue,
    Block,
}

#[derive(Debug, PartialEq, Eq)]
enum HookError {
    Reported,
    WorkerExited,
    TimeoutReaped,
    WorkerIo,
    InvalidDecision,
}

trait Hook {
    fn name(&self) -> &'static str;
    fn event(&self) -> Event;
    fn call(&self, context: &HookContext<'_>) -> Result<Decision, HookError>;
}
// endregion contracts

// region dispatch
#[derive(Debug, PartialEq, Eq)]
enum ChainResult {
    Continue,
    Blocked,
    Failed,
}

fn dispatch(
    hooks: &[Box<dyn Hook>],
    event: Event,
    context: &HookContext<'_>,
    trace: &mut Vec<String>,
    failures: &mut Vec<String>,
) -> ChainResult {
    trace.push(format!("event={event:?}"));
    for hook in hooks.iter().filter(|hook| hook.event() == event) {
        let outcome = match hook.call(context) {
            Ok(Decision::Block) if matches!(event, Event::PostToolUse | Event::Stop) => {
                Err(HookError::InvalidDecision)
            }
            other => other,
        };
        let label = match &outcome {
            Ok(Decision::Continue) => "continue".into(),
            Ok(Decision::Block) => "block".into(),
            Err(error) => format!("error:{error:?}"),
        };
        trace.push(format!("hook={event:?}/{} outcome={label}", hook.name()));
        match outcome {
            Ok(Decision::Continue) => {}
            Ok(Decision::Block) => return ChainResult::Blocked,
            Err(error) => {
                failures.push(format!("{event:?}/{}:{error:?}", hook.name()));
                return ChainResult::Failed;
            }
        }
    }
    ChainResult::Continue
}
// endregion dispatch

struct OwnedWorker {
    child: Child,
    reaped: bool,
}

impl Drop for OwnedWorker {
    fn drop(&mut self) {
        // Best-effort cleanup also covers early I/O error returns.
        if !self.reaped {
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

// region worker
fn run_worker(mode: &str, budget: Duration) -> Result<Decision, HookError> {
    let executable = std::env::current_exe().map_err(|_| HookError::WorkerIo)?;
    let child = Command::new(executable)
        .args(["--hook-worker", mode])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| HookError::WorkerIo)?;
    let mut worker = OwnedWorker {
        child,
        reaped: false,
    };
    let started = Instant::now();
    loop {
        if let Some(status) = worker.child.try_wait().map_err(|_| HookError::WorkerIo)? {
            worker.reaped = true;
            return if status.success() {
                Ok(Decision::Continue)
            } else {
                Err(HookError::WorkerExited)
            };
        }
        if started.elapsed() >= budget {
            // kill does not reap a child: wait is required as a separate step.
            worker.child.kill().map_err(|_| HookError::WorkerIo)?;
            worker.child.wait().map_err(|_| HookError::WorkerIo)?;
            worker.reaped = true;
            return Err(HookError::TimeoutReaped);
        }
        thread::sleep(Duration::from_millis(2));
    }
}
// endregion worker

#[derive(Clone, Copy)]
enum Behavior {
    Record,
    Block,
    Fail,
    PanicWorker,
    HangWorker,
}

struct LabHook {
    name: &'static str,
    event: Event,
    behavior: Behavior,
}

impl Hook for LabHook {
    fn name(&self) -> &'static str {
        self.name
    }
    fn event(&self) -> Event {
        self.event
    }

    fn call(&self, context: &HookContext<'_>) -> Result<Decision, HookError> {
        // Check the read-only view supplied by the runtime at each boundary.
        assert!(!context.prompt.is_empty());
        match self.event {
            Event::UserPromptSubmit => assert!(context.call.is_none()),
            Event::PreToolUse => assert!(context.call.is_some() && context.result.is_none()),
            Event::PostToolUse => {
                assert_eq!(
                    context.call.unwrap().call_id,
                    context.result.unwrap().call_id
                );
            }
            Event::Stop => assert!(context.stop_reason.is_some()),
        }
        match self.behavior {
            Behavior::Record => Ok(Decision::Continue),
            Behavior::Block => Ok(Decision::Block),
            Behavior::Fail => Err(HookError::Reported),
            Behavior::PanicWorker => run_worker("panic", Duration::from_secs(5)),
            Behavior::HangWorker => run_worker("hang", Duration::from_millis(40)),
        }
    }
}

fn hook(name: &'static str, event: Event, behavior: Behavior) -> Box<dyn Hook> {
    Box::new(LabHook {
        name,
        event,
        behavior,
    })
}

struct Workspace(PathBuf);
impl Workspace {
    fn new() -> io::Result<Self> {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!("agent-r04-{}-{stamp}", std::process::id()));
        fs::create_dir(&root)?;
        let workspace = Self(root);
        fs::create_dir(workspace.0.join("notes"))?;
        Ok(workspace)
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[derive(Debug)]
struct RunReport {
    trace: Vec<String>,
    failures: Vec<String>,
    result: Option<ToolResult>,
    stop_reason: &'static str,
    write_attempts: usize,
    write_successes: usize,
    stop_calls: usize,
    summary_matches: bool,
}

// region finish
fn finish(hooks: &[Box<dyn Hook>], call: Option<&ToolCall>, mut report: RunReport) -> RunReport {
    // One exit funnel: observer failure never recursively triggers Stop again.
    let context = HookContext {
        prompt: PROMPT,
        call,
        result: report.result.as_ref(),
        stop_reason: Some(report.stop_reason),
    };
    report.stop_calls += 1;
    dispatch(
        hooks,
        Event::Stop,
        &context,
        &mut report.trace,
        &mut report.failures,
    );
    report
}

// endregion finish

// region authorize
fn authorized(call: &ToolCall, approved: Option<&ToolCall>) -> bool {
    // The trusted caller supplies the exact previously approved action.
    // This is the boundary AFTER R03 resume, not a new approval UI.
    call.path == "notes/summary.txt" && call.content.len() <= 1024 && approved == Some(call)
}
// endregion authorize

// region lifecycle
fn run(
    workspace: &Workspace,
    hooks: &[Box<dyn Hook>],
    call: &ToolCall,
    approved: Option<&ToolCall>,
) -> RunReport {
    let mut report = RunReport {
        trace: Vec::new(),
        failures: Vec::new(),
        result: None,
        stop_reason: "completed",
        write_attempts: 0,
        write_successes: 0,
        stop_calls: 0,
        summary_matches: false,
    };
    let context = HookContext {
        prompt: PROMPT,
        call: None,
        result: None,
        stop_reason: None,
    };
    match dispatch(
        hooks,
        Event::UserPromptSubmit,
        &context,
        &mut report.trace,
        &mut report.failures,
    ) {
        ChainResult::Continue => {}
        ChainResult::Blocked => {
            report.stop_reason = "prompt_blocked";
            return finish(hooks, None, report);
        }
        ChainResult::Failed => {
            report.stop_reason = "prompt_hook_failed";
            return finish(hooks, None, report);
        }
    }
    report
        .trace
        .push(format!("scripted_request call_id={}", call.call_id));
    // region before_tool
    if !authorized(call, approved) {
        report.trace.push("authorization=denied".into());
        report.result = Some(ToolResult {
            call_id: call.call_id.clone(),
            status: "permission_denied",
        });
        report.stop_reason = "permission_denied";
        return finish(hooks, Some(call), report);
    }
    report
        .trace
        .push("authorization=approved_exact_call".into());
    let context = HookContext {
        prompt: PROMPT,
        call: Some(call),
        result: None,
        stop_reason: None,
    };
    match dispatch(
        hooks,
        Event::PreToolUse,
        &context,
        &mut report.trace,
        &mut report.failures,
    ) {
        ChainResult::Continue => {}
        ChainResult::Blocked => {
            report.result = Some(ToolResult {
                call_id: call.call_id.clone(),
                status: "hook_blocked",
            });
            report.stop_reason = "pre_hook_blocked";
            return finish(hooks, Some(call), report);
        }
        ChainResult::Failed => {
            report.result = Some(ToolResult {
                call_id: call.call_id.clone(),
                status: "hook_error",
            });
            report.stop_reason = "pre_hook_failed";
            return finish(hooks, Some(call), report);
        }
    }
    // endregion before_tool
    // region after_tool
    report
        .trace
        .push(format!("tool=write_summary call_id={}", call.call_id));
    report.write_attempts += 1;
    let status = if fs::write(workspace.0.join(&call.path), &call.content).is_ok() {
        report.write_successes += 1;
        "ok"
    } else {
        report.stop_reason = "tool_failed";
        "tool_error"
    };
    report.result = Some(ToolResult {
        call_id: call.call_id.clone(),
        status,
    });
    report.trace.push(format!(
        "tool_result call_id={} status={status}",
        call.call_id
    ));
    let context = HookContext {
        prompt: PROMPT,
        call: Some(call),
        result: report.result.as_ref(),
        stop_reason: None,
    };
    if dispatch(
        hooks,
        Event::PostToolUse,
        &context,
        &mut report.trace,
        &mut report.failures,
    ) != ChainResult::Continue
    {
        report.stop_reason = "post_hook_failed";
    }
    report.summary_matches = fs::read_to_string(workspace.0.join(&call.path))
        .ok()
        .as_deref()
        == Some(call.content.as_str());
    // endregion after_tool
    finish(hooks, Some(call), report)
}
// endregion lifecycle

const SCENARIOS: &[&str] = &[
    "normal",
    "prompt-block",
    "permission-deny",
    "pre-block",
    "pre-error",
    "pre-panic",
    "pre-timeout",
    "post-error",
    "post-timeout",
    "post-block",
    "tool-error",
    "stop-error",
    "stop-timeout",
    "stop-block",
];

// region registration
fn registered_hooks(scenario: &str) -> Vec<Box<dyn Hook>> {
    let mut hooks = vec![hook("input-log", Event::UserPromptSubmit, Behavior::Record)];
    if scenario == "prompt-block" {
        hooks.push(hook(
            "input-check",
            Event::UserPromptSubmit,
            Behavior::Block,
        ));
    }
    let before = match scenario {
        "pre-block" => Behavior::Block,
        "pre-error" => Behavior::Fail,
        "pre-panic" => Behavior::PanicWorker,
        "pre-timeout" => Behavior::HangWorker,
        _ => Behavior::Record,
    };
    hooks.push(hook("before-check", Event::PreToolUse, before));
    hooks.push(hook("before-log", Event::PreToolUse, Behavior::Record));
    let after = match scenario {
        "post-error" => Behavior::Fail,
        "post-timeout" => Behavior::HangWorker,
        "post-block" => Behavior::Block,
        _ => Behavior::Record,
    };
    hooks.push(hook("after-check", Event::PostToolUse, after));
    hooks.push(hook("after-log", Event::PostToolUse, Behavior::Record));
    let stop = match scenario {
        "stop-error" => Behavior::Fail,
        "stop-timeout" => Behavior::HangWorker,
        "stop-block" => Behavior::Block,
        _ => Behavior::Record,
    };
    hooks.push(hook("stop-log", Event::Stop, stop));
    hooks
}
// endregion registration

fn worker_main(mode: &str) -> ! {
    match mode {
        "panic" => panic!("injected hook worker panic"),
        "hang" => loop {
            thread::park();
        },
        _ => std::process::exit(2),
    }
}

fn sample_call() -> ToolCall {
    ToolCall {
        call_id: "write-1".into(),
        path: "notes/summary.txt".into(),
        content: SUMMARY.into(),
    }
}

fn main() -> io::Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--hook-worker") {
        worker_main(args.get(2).map(String::as_str).unwrap_or("invalid"));
    }
    let scenario = args.get(1).map(String::as_str).unwrap_or("normal");
    if !SCENARIOS.contains(&scenario) {
        eprintln!("usage: hooks [{}]", SCENARIOS.join("|"));
        std::process::exit(2);
    }
    let workspace = Workspace::new()?;
    if scenario == "tool-error" {
        fs::create_dir(workspace.0.join("notes/summary.txt"))?;
    }
    let call = sample_call();
    // Simulate a trusted caller AFTER approval; no model can set this value.
    let approved = (scenario != "permission-deny").then_some(&call);
    let report = run(&workspace, &registered_hooks(scenario), &call, approved);
    let actual_summary = fs::read_to_string(workspace.0.join("notes/summary.txt")).ok();
    assert_eq!(
        report.summary_matches,
        actual_summary.as_deref() == Some(SUMMARY)
    );
    println!("scenario={scenario} source=scripted_request approval=trusted_fixture");
    for (index, line) in report.trace.iter().enumerate() {
        println!("trace[{}] {line}", index + 1);
    }
    if let Some(result) = &report.result {
        println!("result call_id={} status={}", result.call_id, result.status);
    } else {
        println!("result none");
    }
    for failure in &report.failures {
        println!("hook_failure={failure}");
    }
    let success = report.stop_reason == "completed" && report.failures.is_empty();
    println!(
        "stats write_attempts={} write_successes={} stop_calls={} hook_failures={} summary_matches={} stop_reason={} task_ok={}",
        report.write_attempts,
        report.write_successes,
        report.stop_calls,
        report.failures.len(),
        report.summary_matches,
        report.stop_reason,
        success
    );
    assert_eq!(report.stop_calls, 1);
    assert_eq!(report.summary_matches, report.write_successes == 1);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normal_order_and_context_are_preserved() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        let report = run(&workspace, &registered_hooks("normal"), &call, Some(&call));
        let hooks: Vec<_> = report
            .trace
            .iter()
            .filter(|line| line.starts_with("hook="))
            .map(String::as_str)
            .collect();
        assert_eq!(
            hooks,
            vec![
                "hook=UserPromptSubmit/input-log outcome=continue",
                "hook=PreToolUse/before-check outcome=continue",
                "hook=PreToolUse/before-log outcome=continue",
                "hook=PostToolUse/after-check outcome=continue",
                "hook=PostToolUse/after-log outcome=continue",
                "hook=Stop/stop-log outcome=continue",
            ]
        );
        assert_eq!(report.result.unwrap().call_id, call.call_id);
        assert_eq!(report.write_successes, 1);
        assert!(report.summary_matches);
    }

    #[test]
    fn empty_hook_list_keeps_authorization_mandatory() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        let denied = run(&workspace, &[], &call, None);
        assert_eq!(denied.result.unwrap().status, "permission_denied");
        assert_eq!(denied.write_attempts, 0);
        assert!(!workspace.0.join(&call.path).exists());
        let mut changed = call.clone();
        changed.content = "different".into();
        assert!(!authorized(&changed, Some(&call)));
        changed = call.clone();
        changed.path = "../outside.txt".into();
        assert!(!authorized(&changed, Some(&changed)));
        let allowed = run(&workspace, &[], &call, Some(&call));
        assert_eq!(allowed.write_successes, 1);
    }

    #[test]
    fn prompt_block_has_no_tool_request_or_result_but_still_stops() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        let report = run(
            &workspace,
            &registered_hooks("prompt-block"),
            &call,
            Some(&call),
        );
        assert!(report.result.is_none());
        assert!(
            report
                .trace
                .iter()
                .all(|line| !line.starts_with("scripted_request"))
        );
        assert_eq!(report.stop_calls, 1);
        assert_eq!(report.write_attempts, 0);
    }

    #[test]
    fn pre_block_and_error_short_circuit_before_io() {
        for scenario in ["pre-block", "pre-error"] {
            let workspace = Workspace::new().unwrap();
            let call = sample_call();
            let report = run(&workspace, &registered_hooks(scenario), &call, Some(&call));
            assert_eq!(report.write_attempts, 0);
            assert!(
                report
                    .trace
                    .iter()
                    .all(|line| !line.contains("before-log") && !line.contains("PostToolUse"))
            );
            assert!(!workspace.0.join(&call.path).exists());
            assert_eq!(report.stop_calls, 1);
        }
    }

    #[test]
    fn post_error_preserves_result_and_actual_file() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        let report = run(
            &workspace,
            &registered_hooks("post-error"),
            &call,
            Some(&call),
        );
        assert_eq!(report.result.unwrap().status, "ok");
        assert_eq!(report.stop_reason, "post_hook_failed");
        assert!(report.summary_matches);
        assert!(report.trace.iter().all(|line| !line.contains("after-log")));
        assert_eq!(
            fs::read_to_string(workspace.0.join(&call.path)).unwrap(),
            SUMMARY
        );
        assert_eq!(report.stop_calls, 1);
    }

    #[test]
    fn tool_failure_still_runs_post_and_stop() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        fs::create_dir(workspace.0.join(&call.path)).unwrap();
        let report = run(&workspace, &registered_hooks("normal"), &call, Some(&call));
        assert_eq!(report.result.unwrap().status, "tool_error");
        assert!(report.trace.iter().any(|line| line == "event=PostToolUse"));
        assert_eq!(report.write_attempts, 1);
        assert_eq!(report.write_successes, 0);
        assert_eq!(report.stop_calls, 1);
    }

    #[test]
    fn stop_error_never_reenters_stop_or_overwrites_tool_result() {
        let workspace = Workspace::new().unwrap();
        let call = sample_call();
        let report = run(
            &workspace,
            &registered_hooks("stop-error"),
            &call,
            Some(&call),
        );
        assert_eq!(report.result.unwrap().status, "ok");
        assert_eq!(report.stop_reason, "completed");
        assert_eq!(report.failures.len(), 1);
        assert_eq!(report.stop_calls, 1);
    }

    #[test]
    fn late_block_is_a_protocol_error_not_a_rollback() {
        for scenario in ["post-block", "stop-block"] {
            let workspace = Workspace::new().unwrap();
            let call = sample_call();
            let report = run(&workspace, &registered_hooks(scenario), &call, Some(&call));
            assert_eq!(report.result.unwrap().status, "ok");
            assert_eq!(report.write_successes, 1);
            assert!(report.failures[0].contains("InvalidDecision"));
            assert_eq!(report.stop_calls, 1);
        }
    }
}
