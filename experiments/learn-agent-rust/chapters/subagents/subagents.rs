//! R06: isolated model histories, shared budgets and cooperative child cleanup.
//! rustc --edition=2024 -D warnings subagents.rs -o subagents
//! ./subagents normal
use std::{
    env,
    error::Error,
    fs, io,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc::{self, Receiver, SyncSender},
    },
    thread::{self, JoinHandle},
};

const PARENT_ONLY: &str = "PARENT_ONLY_NOTE=release-check";
const CHILD_ONLY: &str = "CHILD_RAW_ONLY=fixture-detail";
const QUESTION: &str = "读取 README，告诉我项目启动命令。";
const SUMMARY_LIMIT: usize = 160; // Application policy, measured in UTF-8 bytes.

// region messages
#[derive(Clone, Debug)]
struct Call {
    id: String,
    name: String,
    argument: String,
}

#[derive(Clone, Debug)]
enum Message {
    System(String),
    User(String),
    Request(Call),
    Tool {
        call_id: String,
        content: Result<String, String>,
    },
    Final(String),
}

impl Message {
    fn display(&self) -> String {
        match self {
            Self::System(s) => format!("system | {s}"),
            Self::User(s) => format!("user | {s}"),
            Self::Request(c) => {
                format!("assistant | call_id={} {}({:?})", c.id, c.name, c.argument)
            }
            Self::Tool { call_id, content } => {
                let (status, text) = match content {
                    Ok(s) => ("ok", s),
                    Err(s) => ("error", s),
                };
                format!(
                    "tool | call_id={call_id} status={status} | {}",
                    text.trim_end().replace('\n', " / ")
                )
            }
            Self::Final(s) => format!("assistant | {s}"),
        }
    }
}
// endregion messages

// region contract
#[derive(Clone)]
struct ChildTask {
    session_id: String,
    instruction: String,
    limits: Limits,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Stop {
    Completed,
    ChildModelBudget,
    ChildToolBudget,
    GlobalModelBudget,
    GlobalToolBudget,
    Cancelled,
    Denied,
    MissingFile,
    ToolError,
    InvalidTask,
    OutputLimit,
    ModelError,
    WorkerFailed,
}

#[derive(Debug)]
struct ChildReport {
    session_id: String,
    stop: Stop,
    summary: Option<String>,
    usage: Usage,
}

impl ChildReport {
    fn for_parent(&self) -> String {
        format!(
            "session={} status={:?} summary={} child_models={} child_tools={}",
            self.session_id,
            self.stop,
            self.summary.as_deref().unwrap_or("无"),
            self.usage.models,
            self.usage.tools
        )
    }
}

struct ChildRun {
    report: ChildReport,
    // Diagnostics belong to the host. Only report.for_parent() enters the parent model history.
    history: Vec<Message>,
}
// endregion contract

// region budget
#[derive(Clone, Copy)]
struct Limits {
    models: usize,
    tools: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct Usage {
    models: usize,
    tools: usize,
}

struct Budget {
    limit: Limits,
    used: Usage,
}
type SharedBudget = Arc<Mutex<Budget>>;

#[derive(Clone, Copy)]
enum Cost {
    Model,
    Tool,
}

impl Budget {
    fn charge(&mut self, kind: Cost) -> Result<(), Stop> {
        let (used, limit, stop) = match kind {
            Cost::Model => (
                &mut self.used.models,
                self.limit.models,
                Stop::GlobalModelBudget,
            ),
            Cost::Tool => (
                &mut self.used.tools,
                self.limit.tools,
                Stop::GlobalToolBudget,
            ),
        };
        if *used >= limit {
            return Err(stop);
        }
        *used += 1;
        Ok(())
    }
}

fn charge_child(
    shared: &SharedBudget,
    limits: Limits,
    usage: &mut Usage,
    kind: Cost,
) -> Result<(), Stop> {
    let (used, limit, stop) = match kind {
        Cost::Model => (&mut usage.models, limits.models, Stop::ChildModelBudget),
        Cost::Tool => (&mut usage.tools, limits.tools, Stop::ChildToolBudget),
    };
    if *used >= limit {
        return Err(stop);
    }
    shared.lock().expect("budget mutex").charge(kind)?;
    *used += 1;
    Ok(())
}
// endregion budget

#[derive(Default)]
struct Metrics {
    active: AtomicUsize,
    reads: AtomicUsize,
    successes: AtomicUsize,
}

// region cleanup
struct ChildResources {
    scratch: PathBuf,
    metrics: Arc<Metrics>,
}

impl ChildResources {
    fn create(root: &Workspace, metrics: Arc<Metrics>) -> io::Result<Self> {
        let scratch = root.0.join("child-scratch");
        fs::create_dir(&scratch)?;
        metrics.active.fetch_add(1, Ordering::SeqCst);
        Ok(Self { scratch, metrics })
    }
}

impl Drop for ChildResources {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.scratch);
        self.metrics.active.fetch_sub(1, Ordering::SeqCst);
    }
}
// endregion cleanup

// region model
enum Reply {
    Call(Call),
    Final(String),
    Failed(Stop),
}

fn scripted_child(history: &[Message], task: &ChildTask, scenario: &str) -> Reply {
    // Fixed model fixture: no LLM or HTTP. It receives only the child history.
    match history.last() {
        Some(Message::User(_)) => Reply::Call(Call {
            id: format!("{}/read-1", task.session_id),
            name: if scenario == "recursive" {
                "delegate"
            } else {
                "read_file"
            }
            .into(),
            argument: if scenario == "forbidden-path" {
                "private.txt"
            } else {
                "README.md"
            }
            .into(),
        }),
        Some(Message::Tool {
            content: Ok(text), ..
        }) => {
            if scenario == "model-error" {
                return Reply::Failed(Stop::ModelError);
            }
            if scenario == "oversized-result" {
                return Reply::Final("长摘要".repeat(100));
            }
            match text.lines().find(|line| line.starts_with("启动命令：")) {
                Some(line) => Reply::Final(line.into()),
                None => Reply::Failed(Stop::ModelError),
            }
        }
        Some(Message::Tool {
            content: Err(reason),
            ..
        }) => Reply::Failed(if reason == "missing_file" {
            Stop::MissingFile
        } else if reason.starts_with("denied") {
            Stop::Denied
        } else {
            Stop::ToolError
        }),
        _ => Reply::Failed(Stop::ModelError),
    }
}
// endregion model

// region tool
fn read_for_child(call: &Call, root: &Workspace, metrics: &Metrics) -> Result<String, String> {
    // Tool listing and execution-time permission both restrict the child.
    if call.name != "read_file" || call.argument != "README.md" {
        return Err("denied：子任务只允许 read_file(README.md)".into());
    }
    metrics.reads.fetch_add(1, Ordering::SeqCst);
    match fs::read_to_string(root.0.join(&call.argument)) {
        Ok(text) => {
            metrics.successes.fetch_add(1, Ordering::SeqCst);
            Ok(text)
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Err("missing_file".into()),
        Err(_) => Err("read_error".into()),
    }
}
// endregion tool

// region child-loop
fn child_loop(
    task: ChildTask,
    root: Workspace,
    shared: SharedBudget,
    cancel: Arc<AtomicBool>,
    ready: SyncSender<()>,
    proceed: Receiver<()>,
    metrics: Arc<Metrics>,
    scenario: String,
) -> ChildRun {
    let mut run = ChildRun {
        report: ChildReport {
            session_id: task.session_id.clone(),
            stop: Stop::InvalidTask,
            summary: None,
            usage: Usage::default(),
        },
        history: vec![
            Message::System("只读 README；只回传启动命令；不允许再次委派。".into()),
            Message::User(task.instruction.clone()),
        ],
    };
    if task.instruction.is_empty() || task.instruction.len() > 256 {
        return run;
    }
    let Ok(_resources) = ChildResources::create(&root, metrics.clone()) else {
        run.report.stop = Stop::WorkerFailed;
        return run;
    };
    // root is a non-owning path view. The parent keeps its fixture alive until join.
    loop {
        if cancel.load(Ordering::SeqCst) {
            run.report.stop = Stop::Cancelled;
            return run;
        }
        if let Err(stop) = charge_child(&shared, task.limits, &mut run.report.usage, Cost::Model) {
            run.report.stop = stop;
            return run;
        }
        match scripted_child(&run.history, &task, &scenario) {
            Reply::Final(summary) => {
                if summary.len() > SUMMARY_LIMIT {
                    run.report.stop = Stop::OutputLimit;
                    return run;
                }
                run.history.push(Message::Final(summary.clone()));
                run.report.summary = Some(summary);
                run.report.stop = Stop::Completed;
                return run;
            }
            Reply::Failed(stop) => {
                run.report.stop = stop;
                return run;
            }
            Reply::Call(call) => {
                run.history.push(Message::Request(call.clone()));
                // A deterministic checkpoint lets the parent cancel before any file read.
                // This fixture makes exactly one tool request; no wall-clock sleep is used.
                if ready.send(()).is_err()
                    || proceed.recv().is_err()
                    || cancel.load(Ordering::SeqCst)
                {
                    run.history.push(Message::Tool {
                        call_id: call.id,
                        content: Err("cancelled".into()),
                    });
                    run.report.stop = Stop::Cancelled;
                    return run;
                }
                if let Err(stop) =
                    charge_child(&shared, task.limits, &mut run.report.usage, Cost::Tool)
                {
                    run.history.push(Message::Tool {
                        call_id: call.id,
                        content: Err(format!("{stop:?}")),
                    });
                    run.report.stop = stop;
                    return run;
                }
                let content = read_for_child(&call, &root, &metrics);
                run.history.push(Message::Tool {
                    call_id: call.id,
                    content,
                });
            }
        }
    }
}
// endregion child-loop

// region child-handle
struct ChildHandle {
    cancel: Arc<AtomicBool>,
    ready: Receiver<()>,
    proceed: Option<SyncSender<()>>,
    worker: Option<JoinHandle<ChildRun>>,
}

impl ChildHandle {
    fn spawn(
        task: ChildTask,
        root: &Workspace,
        shared: SharedBudget,
        metrics: Arc<Metrics>,
        scenario: &str,
    ) -> io::Result<Self> {
        let cancel = Arc::new(AtomicBool::new(scenario == "cancel-before-start"));
        let child_cancel = cancel.clone();
        let child_root = Workspace(root.0.clone(), false);
        let (ready_tx, ready) = mpsc::sync_channel(1);
        let (proceed, proceed_rx) = mpsc::sync_channel(1);
        let scenario = scenario.to_string();
        let worker = thread::Builder::new()
            .name(task.session_id.clone())
            .spawn(move || {
                child_loop(
                    task,
                    child_root,
                    shared,
                    child_cancel,
                    ready_tx,
                    proceed_rx,
                    metrics,
                    scenario,
                )
            })?;
        Ok(Self {
            cancel,
            ready,
            proceed: Some(proceed),
            worker: Some(worker),
        })
    }

    fn finish(mut self, cancel_now: bool, close_gate: bool) -> Result<ChildRun, Stop> {
        let _ = self.ready.recv(); // Disconnection also wakes us if the child returned before its tool.
        if cancel_now {
            self.cancel.store(true, Ordering::SeqCst);
        }
        if let Some(tx) = self.proceed.take() {
            if !close_gate {
                let _ = tx.send(());
            }
        }
        self.worker
            .take()
            .expect("owned worker")
            .join()
            .map_err(|_| Stop::WorkerFailed)
    }
}

impl Drop for ChildHandle {
    fn drop(&mut self) {
        // Dropping a plain JoinHandle detaches. Our owner requests cancellation and joins.
        self.cancel.store(true, Ordering::SeqCst);
        self.proceed.take(); // Closing the gate wakes a child blocked on recv().
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
// endregion child-handle

struct Workspace(PathBuf, bool);
impl Workspace {
    fn create(scenario: &str) -> Result<Self, Box<dyn Error>> {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let sequence = NEXT.fetch_add(1, Ordering::SeqCst);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_nanos();
        let path = env::temp_dir().join(format!(
            "learn-agent-r06-{}-{stamp}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&path)?;
        let root = Self(path, true);
        if scenario != "missing-file" {
            let command = if scenario == "changed-readme" {
                "cargo run --release"
            } else {
                "cargo run"
            };
            fs::write(
                root.0.join("README.md"),
                format!("# 练习项目\n启动命令：{command}\n{CHILD_ONLY}\n"),
            )?;
        }
        fs::write(
            root.0.join("private.txt"),
            "这份练习文件没有授予子任务读取权限。",
        )?;
        Ok(root)
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        if self.1 {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
}

struct Experiment {
    parent: Vec<Message>,
    child: Option<ChildRun>,
    total: Usage,
    parent_stop: Stop,
    reads: usize,
    successes: usize,
    active: usize,
    scratch_removed: bool,
    workspace_removed: bool,
}

// region parent
fn experiment(scenario: &str) -> Result<Experiment, Box<dyn Error>> {
    let root = Workspace::create(scenario)?;
    let root_path = root.0.clone();
    let limits = Limits {
        models: match scenario {
            "global-model-budget" => 2,
            "parent-answer-budget" => 3,
            _ => 4,
        },
        tools: if scenario == "global-tool-budget" {
            1
        } else {
            2
        },
    };
    let shared = Arc::new(Mutex::new(Budget {
        limit: limits,
        used: Usage::default(),
    }));
    let metrics = Arc::new(Metrics::default());
    let mut parent = vec![
        Message::System(PARENT_ONLY.into()),
        Message::User(QUESTION.into()),
    ];
    shared
        .lock()
        .expect("budget")
        .charge(Cost::Model)
        .expect("first parent turn");
    let call_id = "parent/delegate-1".to_string();
    parent.push(Message::Request(Call {
        id: call_id.clone(),
        name: "delegate".into(),
        argument: QUESTION.into(),
    }));
    // The delegation itself is a parent tool execution, charged to the same total budget.
    shared
        .lock()
        .expect("budget")
        .charge(Cost::Tool)
        .expect("parent delegation");
    let task = ChildTask {
        session_id: "child-1".into(),
        instruction: if scenario == "invalid-task" {
            String::new()
        } else {
            QUESTION.into()
        },
        limits: Limits {
            models: if scenario == "child-model-budget" {
                1
            } else {
                2
            },
            tools: if scenario == "child-tool-budget" {
                0
            } else {
                1
            },
        },
    };
    // Only task, workspace capability, counters and control channels cross this boundary.
    // The parent message vector is never passed into the worker.
    let handle = ChildHandle::spawn(task, &root, shared.clone(), metrics.clone(), scenario)?;
    let child = handle
        .finish(scenario == "cancel", scenario == "gate-closed")
        .ok();
    let content = match &child {
        Some(run) => Ok(run.report.for_parent()),
        None => Err("WorkerFailed".into()),
    };
    parent.push(Message::Tool { call_id, content });
    let parent_stop = match shared.lock().expect("budget").charge(Cost::Model) {
        Err(stop) => stop,
        Ok(()) => {
            let answer = match child.as_ref().map(|run| &run.report) {
                Some(report) if report.stop == Stop::Completed => format!(
                    "项目{}",
                    report.summary.as_deref().expect("completed summary")
                ),
                Some(report) => format!("任务未完成：子任务状态 {:?}", report.stop),
                None => "任务未完成：子执行者异常退出".into(),
            };
            parent.push(Message::Final(answer));
            Stop::Completed
        }
    };
    let total = shared.lock().expect("budget").used;
    let scratch_removed = !root.0.join("child-scratch").exists();
    drop(root); // ChildHandle has already joined, so no worker can still use this fixture.
    Ok(Experiment {
        parent,
        child,
        total,
        parent_stop,
        reads: metrics.reads.load(Ordering::SeqCst),
        successes: metrics.successes.load(Ordering::SeqCst),
        active: metrics.active.load(Ordering::SeqCst),
        scratch_removed,
        workspace_removed: !root_path.exists(),
    })
}
// endregion parent

impl Experiment {
    fn isolation_ok(&self) -> bool {
        let parent = self
            .parent
            .iter()
            .map(Message::display)
            .collect::<Vec<_>>()
            .join("\n");
        let child = self
            .child
            .as_ref()
            .map(|run| {
                run.history
                    .iter()
                    .map(Message::display)
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_default();
        !child.contains(PARENT_ONLY) && !parent.contains(CHILD_ONLY)
    }
    fn goal_met(&self, scenario: &str) -> bool {
        let expected = if scenario == "changed-readme" {
            "项目启动命令：cargo run --release"
        } else {
            "项目启动命令：cargo run"
        };
        self.successes == 1
            && matches!(self.parent.last(), Some(Message::Final(text)) if text == expected)
    }
}

const SCENARIOS: &[&str] = &[
    "normal",
    "changed-readme",
    "missing-file",
    "child-model-budget",
    "child-tool-budget",
    "global-model-budget",
    "global-tool-budget",
    "parent-answer-budget",
    "cancel",
    "cancel-before-start",
    "gate-closed",
    "forbidden-path",
    "recursive",
    "invalid-task",
    "oversized-result",
    "model-error",
];

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = env::args().skip(1).collect();
    let scenario = match args.as_slice() {
        [] => "normal",
        [name] if SCENARIOS.contains(&name.as_str()) => name,
        _ => return Err(format!("usage: subagents [{}]", SCENARIOS.join("|")).into()),
    };
    let result = experiment(scenario)?;
    println!("场景：{scenario}；模型：父子均为固定规则替身；运行：同进程、单个子线程");
    println!("父模型上下文（只有结构化子任务报告进入工具结果）：");
    for (i, message) in result.parent.iter().enumerate() {
        println!("父 {} | {}", i + 1, message.display());
    }
    println!("宿主诊断：子上下文（不发送给父模型）：");
    if let Some(run) = &result.child {
        for (i, message) in run.history.iter().enumerate() {
            println!("子 {} | {}", i + 1, message.display());
        }
        println!(
            "子统计：models={} tools={} messages={} stop={:?}",
            run.report.usage.models,
            run.report.usage.tools,
            run.history.len(),
            run.report.stop
        );
    }
    println!(
        "总统计：models={} tools={} reads={} successes={} parent_messages={} parent_stop={:?}",
        result.total.models,
        result.total.tools,
        result.reads,
        result.successes,
        result.parent.len(),
        result.parent_stop
    );
    println!(
        "边界：context_isolated={} fixture_goal_met={}",
        result.isolation_ok(),
        result.goal_met(scenario)
    );
    println!(
        "清理：active_workers={} scratch_removed={} workspace_removed={}",
        result.active, result.scratch_removed, result.workspace_removed
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shared(models: usize, tools: usize) -> SharedBudget {
        Arc::new(Mutex::new(Budget {
            limit: Limits { models, tools },
            used: Usage::default(),
        }))
    }
    fn task() -> ChildTask {
        ChildTask {
            session_id: "test-child".into(),
            instruction: QUESTION.into(),
            limits: Limits {
                models: 2,
                tools: 1,
            },
        }
    }

    #[test]
    fn histories_and_result_are_separate() {
        let run = experiment("normal").unwrap();
        assert!(run.isolation_ok() && run.goal_met("normal"));
        assert_eq!(
            (run.parent.len(), run.child.as_ref().unwrap().history.len()),
            (5, 5)
        );
        assert_eq!((run.total.models, run.total.tools), (4, 2));
        assert!(
            matches!(&run.parent[3], Message::Tool {call_id, ..} if call_id == "parent/delegate-1")
        );
    }

    #[test]
    fn cancellation_and_gate_disconnect_join_before_cleanup() {
        for scenario in ["cancel", "cancel-before-start", "gate-closed"] {
            let run = experiment(scenario).unwrap();
            assert_eq!(run.child.as_ref().unwrap().report.stop, Stop::Cancelled);
            assert_eq!((run.reads, run.active), (0, 0));
            assert!(run.scratch_removed && run.workspace_removed && !run.goal_met(scenario));
        }
    }

    #[test]
    fn dropping_the_owner_cancels_and_joins_a_waiting_child() {
        let root = Workspace::create("normal").unwrap();
        let metrics = Arc::new(Metrics::default());
        let handle =
            ChildHandle::spawn(task(), &root, shared(2, 1), metrics.clone(), "normal").unwrap();
        handle.ready.recv().unwrap();
        assert_eq!(metrics.active.load(Ordering::SeqCst), 1);
        assert!(root.0.join("child-scratch").exists());
        drop(handle);
        assert_eq!(
            (
                metrics.active.load(Ordering::SeqCst),
                metrics.reads.load(Ordering::SeqCst)
            ),
            (0, 0)
        );
        assert!(!root.0.join("child-scratch").exists());
    }

    #[test]
    fn repeated_children_do_not_reset_the_shared_budget() {
        let root = Workspace::create("normal").unwrap();
        let budget = shared(2, 1);
        for (i, expected) in [Stop::Completed, Stop::GlobalModelBudget]
            .into_iter()
            .enumerate()
        {
            let mut child = task();
            child.session_id = format!("test-{i}");
            let run = ChildHandle::spawn(
                child,
                &root,
                budget.clone(),
                Arc::new(Metrics::default()),
                "normal",
            )
            .unwrap()
            .finish(false, false)
            .unwrap();
            assert_eq!(run.report.stop, expected);
        }
        let used = budget.lock().unwrap().used;
        assert_eq!((used.models, used.tools), (2, 1));
    }

    #[test]
    fn child_budget_rejection_does_not_charge_shared_budget() {
        let budget = shared(4, 2);
        let mut usage = Usage::default();
        assert_eq!(
            charge_child(
                &budget,
                Limits {
                    models: 0,
                    tools: 0
                },
                &mut usage,
                Cost::Model
            ),
            Err(Stop::ChildModelBudget)
        );
        assert_eq!((usage.models, budget.lock().unwrap().used.models), (0, 0));
        let full = shared(0, 0);
        assert_eq!(
            charge_child(
                &full,
                Limits {
                    models: 2,
                    tools: 1
                },
                &mut usage,
                Cost::Tool
            ),
            Err(Stop::GlobalToolBudget)
        );
        assert_eq!(usage.tools, 0);
    }

    #[test]
    fn child_success_does_not_create_budget_for_the_parent_answer() {
        let run = experiment("parent-answer-budget").unwrap();
        assert_eq!(run.child.as_ref().unwrap().report.stop, Stop::Completed);
        assert_eq!(run.parent_stop, Stop::GlobalModelBudget);
        assert!(!run.goal_met("parent-answer-budget"));
        assert_eq!(run.parent.len(), 4);
    }

    #[test]
    fn child_permissions_precede_file_io_and_disallow_delegation() {
        for scenario in ["forbidden-path", "recursive"] {
            let run = experiment(scenario).unwrap();
            assert_eq!(run.child.as_ref().unwrap().report.stop, Stop::Denied);
            assert_eq!(run.reads, 0);
            assert!(run.scratch_removed && run.workspace_removed);
        }
    }

    #[test]
    fn report_byte_limit_rejects_oversized_utf8_without_returning_it() {
        let run = experiment("oversized-result").unwrap();
        let report = &run.child.as_ref().unwrap().report;
        assert_eq!(report.stop, Stop::OutputLimit);
        assert!(report.summary.is_none());
        assert!(
            !run.parent
                .iter()
                .any(|message| message.display().contains("长摘要"))
        );
    }

    #[test]
    fn failed_model_and_missing_file_cannot_report_success() {
        for (scenario, stop) in [
            ("model-error", Stop::ModelError),
            ("missing-file", Stop::MissingFile),
        ] {
            let run = experiment(scenario).unwrap();
            assert_eq!(run.child.as_ref().unwrap().report.stop, stop);
            assert!(!run.goal_met(scenario));
            assert_eq!(run.active, 0);
        }
    }
}
