//! R13: bounded process-local background jobs. No model, network or database.
//! rustc --edition=2024 -D warnings background-tasks.rs -o background
use std::collections::{BTreeMap, VecDeque};
use std::fs::{self, File};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Condvar, Mutex, mpsc};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const LIMIT: usize = 2;
const HISTORY: usize = 4;
const CHUNKS: usize = 3;
const SCENARIOS: &[&str] = &[
    "normal",
    "cancel",
    "cancel-before-work",
    "late-cancel",
    "repeat-cancel",
    "capacity",
    "failure",
    "panic",
    "notifications",
    "unknown",
    "shutdown",
    "drop",
    "history",
    "closed",
];

// region ownership
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum State {
    Running,
    CancelRequested,
    Completed,
    Cancelled,
    Failed,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CancelReply {
    Accepted,
    AlreadyRequested,
    TooLate,
    Unknown,
}

#[derive(Clone, Copy, Debug)]
enum Mode {
    Normal,
    Fail,
    Panic,
}

#[derive(Default)]
struct Gate {
    ready: bool,
    permits: usize, // Lab control: release one real file write at a time.
    progress: usize,
    cancel: bool,
    published: bool,
}

type Control = Arc<(Mutex<Gate>, Condvar)>;

struct RunningJob {
    control: Control,
    handle: JoinHandle<Result<State, String>>,
}

struct Manager {
    root: PathBuf,
    next_id: u64,
    jobs: BTreeMap<u64, RunningJob>, // Sole owner of every join permission.
    states: BTreeMap<u64, State>,
    finished: VecDeque<u64>,
    notices: mpsc::SyncSender<u64>,
    inbox: mpsc::Receiver<u64>,
    closed: bool,
    started: usize,
    joined: usize,
    peak: usize,
    dropped_notices: usize,
}
// endregion ownership

// Removes an incomplete artifact on error, cancellation or panic unwind.
struct Partial(PathBuf);
impl Drop for Partial {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

// region worker
fn worker(root: &Path, id: u64, control: &Control, mode: Mode) -> Result<State, String> {
    let partial = Partial(root.join(format!("job-{id}.part")));
    let mut file = File::create(&partial.0).map_err(|e| e.to_string())?;
    let (lock, wake) = &**control;
    {
        let mut gate = lock.lock().unwrap();
        gate.ready = true;
        wake.notify_all();
    }
    for chunk in 1..=CHUNKS {
        let gate = lock.lock().unwrap();
        // Always check the predicate again after waking (including spurious wakes).
        let mut gate = wake
            .wait_while(gate, |g| g.permits == 0 && !g.cancel)
            .unwrap();
        if gate.cancel {
            return Ok(State::Cancelled);
        }
        gate.permits -= 1;
        // The lock covers a small local write. Cancellation waits for this chunk.
        writeln!(file, "chunk={chunk}").map_err(|e| e.to_string())?;
        gate.progress = chunk;
        wake.notify_all();
        drop(gate);
        if chunk == 1 {
            match mode {
                Mode::Fail => return Err("injected tool failure".into()),
                Mode::Panic => panic!("injected worker panic"),
                Mode::Normal => {}
            }
        }
    }
    drop(file); // Close before rename; also works on Windows.
    let mut gate = lock.lock().unwrap();
    if gate.cancel {
        return Ok(State::Cancelled);
    }
    // Publication and cancel admission use the SAME lock: one wins first.
    fs::rename(&partial.0, root.join(format!("job-{id}.txt"))).map_err(|e| e.to_string())?;
    gate.published = true;
    wake.notify_all();
    Ok(State::Completed)
}
// endregion worker

impl Manager {
    fn new(root: PathBuf) -> Self {
        let (notices, inbox) = mpsc::sync_channel(1);
        Self {
            root,
            next_id: 1,
            jobs: BTreeMap::new(),
            states: BTreeMap::new(),
            finished: VecDeque::new(),
            notices,
            inbox,
            closed: false,
            started: 0,
            joined: 0,
            peak: 0,
            dropped_notices: 0,
        }
    }

    // region start
    fn start(&mut self, mode: Mode) -> Result<u64, &'static str> {
        self.poll();
        if self.closed {
            return Err("closed");
        }
        if self.jobs.len() >= LIMIT {
            return Err("capacity"); // Reject BEFORE spawning; there is no waiting queue.
        }
        let id = self.next_id;
        self.next_id = self.next_id.checked_add(1).ok_or("id_exhausted")?;
        let control = Arc::new((Mutex::new(Gate::default()), Condvar::new()));
        let child_control = control.clone();
        let root = self.root.clone();
        let handle = thread::Builder::new()
            .name(format!("r13-{id}"))
            .spawn(move || worker(&root, id, &child_control, mode))
            .map_err(|_| "spawn_failed")?;
        self.jobs.insert(id, RunningJob { control, handle });
        self.states.insert(id, State::Running);
        self.started += 1;
        self.peak = self.peak.max(self.jobs.len());
        Ok(id) // No join, no wait for tool completion.
    }
    // endregion start

    fn query(&self, id: u64) -> Option<State> {
        self.states.get(&id).copied()
    }

    // region cancel
    fn cancel(&mut self, id: u64) -> CancelReply {
        let Some(state) = self.query(id) else {
            return CancelReply::Unknown;
        };
        if !matches!(state, State::Running | State::CancelRequested) {
            return CancelReply::TooLate;
        }
        let job = &self.jobs[&id];
        let (lock, wake) = &*job.control;
        let mut gate = lock.lock().unwrap();
        if gate.published || job.handle.is_finished() {
            return CancelReply::TooLate;
        }
        if gate.cancel {
            return CancelReply::AlreadyRequested;
        }
        gate.cancel = true;
        self.states.insert(id, State::CancelRequested);
        wake.notify_all(); // Wake an idle worker so shutdown cannot wait on its gate.
        CancelReply::Accepted
    }
    // endregion cancel

    // region collect
    fn poll(&mut self) {
        let finished: Vec<_> = self
            .jobs
            .iter()
            .filter(|(_, job)| job.handle.is_finished())
            .map(|(&id, _)| id)
            .collect();
        for id in finished {
            self.join_one(id);
        }
    }

    fn join_one(&mut self, id: u64) {
        let Some(job) = self.jobs.remove(&id) else {
            return;
        };
        let state = match job.handle.join() {
            Ok(Ok(state)) => state,
            Ok(Err(_)) | Err(_) => State::Failed,
        };
        self.joined += 1;
        self.states.insert(id, state); // Terminal state only AFTER join.
        self.finished.push_back(id);
        if self.notices.try_send(id).is_err() {
            self.dropped_notices += 1;
        }
        // Keep completed metadata and result files bounded as well as active workers.
        while self.finished.len() > HISTORY {
            let old = self.finished.pop_front().unwrap();
            self.states.remove(&old);
            let _ = fs::remove_file(self.root.join(format!("job-{old}.txt")));
        }
    }
    // endregion collect

    // region shutdown
    fn shutdown(&mut self) {
        self.closed = true;
        let ids: Vec<_> = self.jobs.keys().copied().collect();
        for &id in &ids {
            self.cancel(id);
        }
        for id in ids {
            self.join_one(id);
        }
    }
    // endregion shutdown

    // Lab harness only: grant steps and await observations without sleep-based races.
    fn release(&self, id: u64, steps: usize) {
        let (lock, wake) = &*self.jobs[&id].control;
        lock.lock().unwrap().permits += steps;
        wake.notify_all();
    }

    fn await_progress(&self, id: u64, progress: usize) {
        let (lock, wake) = &*self.jobs[&id].control;
        let gate = lock.lock().unwrap();
        let (gate, timeout) = wake
            .wait_timeout_while(gate, Duration::from_secs(5), |g| {
                !g.ready || g.progress < progress
            })
            .unwrap();
        assert!(
            gate.ready && gate.progress >= progress,
            "worker observation timeout: {timeout:?}"
        );
    }

    fn drain_notices(&self) -> Vec<u64> {
        self.inbox.try_iter().collect()
    }
}

impl Drop for Manager {
    fn drop(&mut self) {
        self.shutdown();
    }
}

struct Workspace {
    path: PathBuf,
    keep: bool,
}
impl Workspace {
    fn create(path: Option<PathBuf>) -> io::Result<Self> {
        let keep = path.is_some();
        let path = path.unwrap_or_else(|| {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            std::env::temp_dir().join(format!("agent-r13-{}-{nonce}", std::process::id()))
        });
        fs::create_dir(&path)?; // Refuse an existing directory; never overwrite user data.
        Ok(Self { path, keep })
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        if !self.keep {
            let _ = fs::remove_dir_all(&self.path);
        }
    }
}

fn files(root: &Path, suffix: &str) -> usize {
    fs::read_dir(root)
        .unwrap()
        .map(Result::unwrap)
        .filter(|p| p.file_name().to_string_lossy().ends_with(suffix))
        .count()
}

fn complete(manager: &mut Manager, id: u64) {
    manager.release(id, CHUNKS);
    manager.join_one(id);
}

fn scenario(name: &str, root: &Path) -> String {
    let mut lines = vec![format!("scenario={name}")];
    let mut manager = Manager::new(root.to_owned());
    match name {
        "normal" => {
            let id = manager.start(Mode::Normal).unwrap();
            manager.await_progress(id, 0);
            lines.push(format!(
                "start id={id} query={:?}",
                manager.query(id).unwrap()
            ));
            lines.push("foreground=can_handle_another_request".into());
            manager.release(id, 1);
            manager.await_progress(id, 1);
            lines.push(format!(
                "checkpoint progress=1 partial_files={}",
                files(root, ".part")
            ));
            manager.release(id, 2);
            manager.join_one(id);
            lines.push(format!(
                "query={:?} notices={:?}",
                manager.query(id).unwrap(),
                manager.drain_notices()
            ));
        }
        "cancel" | "cancel-before-work" | "repeat-cancel" => {
            let id = manager.start(Mode::Normal).unwrap();
            manager.await_progress(id, 0);
            if name != "cancel-before-work" {
                manager.release(id, 1);
                manager.await_progress(id, 1);
            }
            lines.push(format!("cancel={:?}", manager.cancel(id)));
            // Repeat uses a controlled gate below in the unit test; here terminal may win.
            if name == "repeat-cancel" {
                let reply = manager.cancel(id);
                assert!(matches!(
                    reply,
                    CancelReply::AlreadyRequested | CancelReply::TooLate
                ));
                lines.push("repeat=AlreadyRequested_or_TooLate".into());
            }
            manager.join_one(id);
            lines.push(format!("query={:?}", manager.query(id).unwrap()));
        }
        "late-cancel" => {
            let id = manager.start(Mode::Normal).unwrap();
            complete(&mut manager, id);
            lines.push(format!(
                "cancel={:?} query={:?}",
                manager.cancel(id),
                manager.query(id).unwrap()
            ));
        }
        "capacity" => {
            let first = manager.start(Mode::Normal).unwrap();
            let second = manager.start(Mode::Normal).unwrap();
            manager.await_progress(first, 0);
            manager.await_progress(second, 0);
            lines.push(format!(
                "simultaneously_ready={} rejected={}",
                manager.jobs.len(),
                manager.start(Mode::Normal).unwrap_err()
            ));
            complete(&mut manager, first);
            let replacement = manager.start(Mode::Normal).unwrap();
            lines.push(format!("replacement_id={replacement}"));
            manager.shutdown();
        }
        "failure" | "panic" => {
            let mode = if name == "failure" {
                Mode::Fail
            } else {
                Mode::Panic
            };
            let id = manager.start(mode).unwrap();
            manager.release(id, 1);
            manager.join_one(id);
            lines.push(format!(
                "query={:?} notices={:?}",
                manager.query(id).unwrap(),
                manager.drain_notices()
            ));
        }
        "notifications" => {
            let a = manager.start(Mode::Normal).unwrap();
            let b = manager.start(Mode::Normal).unwrap();
            complete(&mut manager, a);
            complete(&mut manager, b);
            lines.push(format!(
                "notices={:?} query_1={:?} query_2={:?}",
                manager.drain_notices(),
                manager.query(a).unwrap(),
                manager.query(b).unwrap()
            ));
        }
        "unknown" => {
            lines.push(format!(
                "query={:?} cancel={:?}",
                manager.query(999),
                manager.cancel(999)
            ));
        }
        "shutdown" | "drop" => {
            let a = manager.start(Mode::Normal).unwrap();
            let b = manager.start(Mode::Normal).unwrap();
            manager.release(a, 1);
            manager.await_progress(a, 1);
            manager.await_progress(b, 0);
            if name == "drop" {
                drop(manager);
                lines.push(format!(
                    "drop_returned=true partial_files={} result_files={}",
                    files(root, ".part"),
                    files(root, ".txt")
                ));
                return lines.join("\n") + "\n";
            }
            manager.shutdown();
            lines.push(format!(
                "query_1={:?} query_2={:?} closed={}",
                manager.query(a).unwrap(),
                manager.query(b).unwrap(),
                manager.closed
            ));
        }
        "history" => {
            for _ in 0..(HISTORY + 2) {
                let id = manager.start(Mode::Normal).unwrap();
                complete(&mut manager, id);
                manager.drain_notices();
            }
            lines.push(format!(
                "retained={} first_query={:?} latest_query={:?}",
                manager.states.len(),
                manager.query(1),
                manager.query(6).unwrap()
            ));
        }
        "closed" => {
            manager.shutdown();
            lines.push(format!(
                "start_error={}",
                manager.start(Mode::Normal).unwrap_err()
            ));
        }
        _ => unreachable!(),
    }
    manager.shutdown();
    lines.push(format!("stats started={} joined={} peak={} active={} records={} dropped_notices={} partial_files={} result_files={}",
        manager.started, manager.joined, manager.peak, manager.jobs.len(), manager.states.len(),
        manager.dropped_notices, files(root, ".part"), files(root, ".txt")));
    lines.join("\n") + "\n"
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let name = args.first().map(String::as_str).unwrap_or("normal");
    if args.len() > 2 || !SCENARIOS.contains(&name) {
        eprintln!(
            "usage: background [{}] [new-workspace]",
            SCENARIOS.join("|")
        );
        std::process::exit(2);
    }
    let workspace = match Workspace::create(args.get(1).map(PathBuf::from)) {
        Ok(workspace) => workspace,
        Err(error) => {
            eprintln!("workspace rejected: {error}");
            std::process::exit(1);
        }
    };
    print!("{}", scenario(name, &workspace.path));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup() -> (Workspace, Manager) {
        let workspace = Workspace::create(None).unwrap();
        let manager = Manager::new(workspace.path.clone());
        (workspace, manager)
    }

    #[test]
    fn start_returns_while_two_workers_are_waiting() {
        let (_workspace, mut manager) = setup();
        let a = manager.start(Mode::Normal).unwrap();
        let b = manager.start(Mode::Normal).unwrap();
        manager.await_progress(a, 0);
        manager.await_progress(b, 0);
        assert_eq!(manager.query(a), Some(State::Running));
        assert_eq!(manager.start(Mode::Normal), Err("capacity"));
        assert_eq!(manager.started, 2);
    }

    #[test]
    fn cancel_after_partial_write_removes_partial_and_joins() {
        let (workspace, mut manager) = setup();
        let id = manager.start(Mode::Normal).unwrap();
        manager.release(id, 1);
        manager.await_progress(id, 1);
        assert_eq!(
            fs::read_to_string(workspace.path.join("job-1.part")).unwrap(),
            "chunk=1\n"
        );
        assert_eq!(manager.cancel(id), CancelReply::Accepted);
        // Query is a snapshot until poll; the request itself never claims completion.
        assert_eq!(manager.query(id), Some(State::CancelRequested));
        manager.join_one(id);
        assert_eq!(manager.query(id), Some(State::Cancelled));
        assert_eq!(files(&workspace.path, ".part"), 0);
        assert_eq!(files(&workspace.path, ".txt"), 0);
        assert_eq!(manager.joined, 1);
    }

    #[test]
    fn publication_wins_before_poll_and_cannot_be_cancelled() {
        let (workspace, mut manager) = setup();
        let id = manager.start(Mode::Normal).unwrap();
        let control = manager.jobs[&id].control.clone();
        manager.release(id, CHUNKS);
        let (lock, wake) = &*control;
        let gate = lock.lock().unwrap();
        let (gate, _) = wake
            .wait_timeout_while(gate, Duration::from_secs(5), |g| !g.published)
            .unwrap();
        assert!(gate.published);
        drop(gate);
        assert_eq!(manager.query(id), Some(State::Running));
        assert_eq!(manager.cancel(id), CancelReply::TooLate);
        manager.join_one(id);
        assert_eq!(
            fs::read_to_string(workspace.path.join("job-1.txt")).unwrap(),
            "chunk=1\nchunk=2\nchunk=3\n"
        );
    }

    #[test]
    fn cancellation_before_last_permit_wins() {
        let (workspace, mut manager) = setup();
        let id = manager.start(Mode::Normal).unwrap();
        manager.release(id, 2);
        manager.await_progress(id, 2);
        assert_eq!(manager.cancel(id), CancelReply::Accepted);
        manager.release(id, 1);
        manager.join_one(id);
        assert_eq!(manager.query(id), Some(State::Cancelled));
        assert!(!workspace.path.join("job-1.txt").exists());
    }

    #[test]
    fn repeated_cancel_does_not_create_another_result() {
        let (_workspace, mut manager) = setup();
        let id = manager.start(Mode::Normal).unwrap();
        assert_eq!(manager.cancel(id), CancelReply::Accepted);
        assert!(matches!(
            manager.cancel(id),
            CancelReply::AlreadyRequested | CancelReply::TooLate
        ));
        manager.join_one(id);
        assert_eq!(manager.cancel(id), CancelReply::TooLate);
        manager.join_one(id);
        assert_eq!(manager.joined, 1);
        assert_eq!(manager.drain_notices(), [id]);
    }

    #[test]
    fn failure_and_panic_cleanup_and_release_capacity() {
        for mode in [Mode::Fail, Mode::Panic] {
            let (workspace, mut manager) = setup();
            let id = manager.start(mode).unwrap();
            manager.release(id, 1);
            manager.join_one(id);
            assert_eq!(manager.query(id), Some(State::Failed));
            assert_eq!(files(&workspace.path, ".part"), 0);
            assert_eq!(files(&workspace.path, ".txt"), 0);
            let next = manager.start(Mode::Normal).unwrap();
            assert!(next > id);
        }
    }

    #[test]
    fn bounded_notification_overflow_keeps_queryable_state() {
        let (_workspace, mut manager) = setup();
        let a = manager.start(Mode::Normal).unwrap();
        let b = manager.start(Mode::Normal).unwrap();
        complete(&mut manager, a);
        complete(&mut manager, b);
        assert_eq!(manager.drain_notices(), [a]);
        assert_eq!(manager.dropped_notices, 1);
        assert_eq!(manager.query(b), Some(State::Completed));
    }

    #[test]
    fn shutdown_wakes_all_joins_and_refuses_more_work() {
        let (workspace, mut manager) = setup();
        let a = manager.start(Mode::Normal).unwrap();
        let b = manager.start(Mode::Normal).unwrap();
        manager.await_progress(a, 0);
        manager.await_progress(b, 0);
        manager.shutdown();
        manager.shutdown();
        assert_eq!(manager.joined, 2);
        assert!(manager.jobs.is_empty());
        assert_eq!(manager.start(Mode::Normal), Err("closed"));
        assert_eq!(files(&workspace.path, ".part"), 0);
    }

    #[test]
    fn history_and_results_are_bounded_and_ids_never_reused() {
        let (workspace, mut manager) = setup();
        for expected in 1..=6 {
            let id = manager.start(Mode::Normal).unwrap();
            assert_eq!(id, expected);
            complete(&mut manager, id);
        }
        assert_eq!(manager.states.len(), HISTORY);
        assert_eq!(manager.query(1), None);
        assert_eq!(manager.cancel(1), CancelReply::Unknown);
        assert_eq!(files(&workspace.path, ".txt"), HISTORY);
    }

    #[test]
    fn drop_waits_before_workspace_is_removed() {
        let (workspace, mut manager) = setup();
        let a = manager.start(Mode::Normal).unwrap();
        manager.release(a, 1);
        manager.await_progress(a, 1);
        drop(manager);
        assert_eq!(files(&workspace.path, ".part"), 0);
        assert_eq!(files(&workspace.path, ".txt"), 0);
    }

    #[test]
    fn existing_workspace_is_preserved() {
        let workspace = Workspace::create(None).unwrap();
        fs::write(workspace.path.join("keep"), "keep").unwrap();
        assert!(Workspace::create(Some(workspace.path.clone())).is_err());
        assert_eq!(
            fs::read_to_string(workspace.path.join("keep")).unwrap(),
            "keep"
        );
    }

    #[test]
    fn poll_collects_completed_worker_once() {
        let (_workspace, mut manager) = setup();
        let id = manager.start(Mode::Normal).unwrap();
        manager.release(id, CHUNKS);
        // The condvar records the three writes; thread completion is polled by the host.
        manager.await_progress(id, CHUNKS);
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        while manager.joined == 0 {
            manager.poll();
            assert!(std::time::Instant::now() < deadline);
            thread::yield_now();
        }
        manager.poll();
        assert_eq!(manager.joined, 1);
        assert_eq!(manager.query(id), Some(State::Completed));
    }
}
