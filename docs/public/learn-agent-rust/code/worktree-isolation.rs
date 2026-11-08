//! R18: real Git worktrees in a newly created, dedicated exercise repository.
//! rustc --edition=2024 -D warnings worktree-isolation.rs -o worktree-lab
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::{Arc, Mutex, mpsc};
use std::thread::{self, JoinHandle};

type Result<T> = std::result::Result<T, String>;
const SCENARIOS: &[&str] = &[
    "clean",
    "parallel",
    "tracked",
    "staged",
    "untracked",
    "ignored",
    "unmerged",
    "accepted",
    "conflict",
    "busy",
    "stale",
    "duplicate",
    "existing-path",
    "branch-exists",
    "denied",
    "invalid-task",
    "unknown",
    "locked",
    "wrong-branch",
];
const BASE_TEXT: &str = "startup=cargo run\n";

// region binding
#[derive(Clone, Debug, PartialEq, Eq)]
struct Actor {
    owner: String,
    epoch: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Disposition {
    Active,
    Retained(&'static str),
    Removed,
}

struct Writer {
    release: mpsc::Sender<bool>,
    handle: JoinHandle<Result<()>>,
}

struct Binding {
    task: String,
    attempt: u32,
    actor: Actor,
    base: String,
    branch: String,
    path: PathBuf,
    disposition: Disposition,
    writer: Option<Writer>,
}

struct Lab {
    root: PathBuf,
    repo: PathBuf,
    bindings: BTreeMap<String, Binding>,
    // Trusted fixture standing in for R17's authoritative claim store.
    claims: Arc<Mutex<BTreeMap<String, Actor>>>,
}
// endregion binding

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 24
        && value.as_bytes()[0].is_ascii_lowercase()
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

impl Lab {
    fn create(root: &Path) -> Result<Self> {
        // Must be new. Never initialize or operate on the caller's existing repository.
        fs::create_dir(root).map_err(|_| "root_exists_or_unavailable".to_string())?;
        let root = fs::canonicalize(root).map_err(|e| e.to_string())?;
        let repo = root.join("repository");
        fs::create_dir(&repo).map_err(|e| e.to_string())?;
        fs::create_dir(root.join("workspaces")).map_err(|e| e.to_string())?;
        fs::create_dir(root.join("empty-hooks")).map_err(|e| e.to_string())?;
        fs::write(root.join("empty-config"), "").map_err(|e| e.to_string())?;
        let lab = Self {
            root,
            repo,
            bindings: BTreeMap::new(),
            claims: Arc::default(),
        };
        lab.git(&lab.repo, &["init", "--initial-branch=main"])?;
        fs::write(lab.repo.join("README.md"), BASE_TEXT).map_err(|e| e.to_string())?;
        fs::write(lab.repo.join(".gitignore"), "scratch/\n").map_err(|e| e.to_string())?;
        lab.git(&lab.repo, &["add", "--", "README.md", ".gitignore"])?;
        lab.git(&lab.repo, &["commit", "-m", "exercise baseline"])?;
        Ok(lab)
    }

    // region git-command
    fn command(&self, cwd: &Path, args: &[&str]) -> Result<Output> {
        let mut command = Command::new("git");
        // Remove inherited Git routing/config variables so -C remains authoritative.
        for (key, _) in std::env::vars_os() {
            if key.to_string_lossy().starts_with("GIT_") {
                command.env_remove(key);
            }
        }
        command
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .env("GIT_CONFIG_GLOBAL", self.root.join("empty-config"))
            .env("GIT_TERMINAL_PROMPT", "0")
            .env("GIT_AUTHOR_DATE", "2026-01-01T00:00:00+0000")
            .env("GIT_COMMITTER_DATE", "2026-01-01T00:00:00+0000")
            .arg("-C")
            .arg(cwd)
            .arg("-c")
            .arg("user.name=R18 Lab")
            .arg("-c")
            .arg("user.email=r18@example.invalid")
            .arg("-c")
            .arg("commit.gpgsign=false")
            .arg("-c")
            .arg("core.autocrlf=false")
            .arg("-c")
            .arg("core.filemode=false")
            .arg("-c")
            .arg(format!(
                "core.hooksPath={}",
                self.root.join("empty-hooks").display()
            ))
            .arg("-c")
            .arg(format!(
                "init.templateDir={}",
                self.root.join("empty-hooks").display()
            ))
            .args(args)
            .output()
            .map_err(|e| format!("git_unavailable: {e}"))
    }

    fn git(&self, cwd: &Path, args: &[&str]) -> Result<String> {
        let output = self.command(cwd, args)?;
        if !output.status.success() {
            return Err("git_command_failed".into());
        }
        String::from_utf8(output.stdout).map_err(|_| "git_output_encoding".into())
    }
    // endregion git-command

    fn claim(&self, task: &str, actor: &Actor) {
        self.claims
            .lock()
            .unwrap()
            .insert(task.into(), actor.clone());
    }

    fn authorized(&self, task: &str, actor: &Actor, allowed: bool) -> Result<()> {
        if !allowed {
            return Err("permission_denied".into());
        }
        if self.claims.lock().unwrap().get(task) != Some(actor) {
            return Err("stale_owner".into());
        }
        Ok(())
    }

    // region allocate
    fn allocate(&mut self, task: &str, attempt: u32, actor: &Actor, allowed: bool) -> Result<()> {
        if !valid_id(task) || attempt == 0 {
            return Err("invalid_identity".into());
        }
        self.authorized(task, actor, allowed)?;
        if self.bindings.contains_key(task) {
            return Err("duplicate_binding".into());
        }
        let name = format!("{task}-a{attempt}");
        let path = self.root.join("workspaces").join(&name);
        if fs::symlink_metadata(&path).is_ok() {
            return Err("path_exists".into());
        }
        let branch = format!("codex/r18-{name}");
        let base = self
            .git(&self.repo, &["rev-parse", "--verify", "main^{commit}"])?
            .trim()
            .to_owned();
        let path_arg = path.to_str().ok_or("path_encoding")?;
        // No shell, no --force, no checkout of an existing branch.
        self.git(
            &self.repo,
            &["worktree", "add", "-b", &branch, path_arg, &base],
        )
        .map_err(|_| "worktree_add_failed".to_string())?;
        self.bindings.insert(
            task.into(),
            Binding {
                task: task.into(),
                attempt,
                actor: actor.clone(),
                base,
                branch,
                path,
                disposition: Disposition::Active,
                writer: None,
            },
        );
        Ok(())
    }
    // endregion allocate

    // region validate
    fn validate(&self, task: &str, actor: &Actor) -> Result<&Binding> {
        self.authorized(task, actor, true)?;
        let binding = self.bindings.get(task).ok_or("unknown_binding")?;
        if binding.actor != *actor {
            return Err("binding_owner_mismatch".into());
        }
        if binding.disposition == Disposition::Removed {
            return Err("already_removed".into());
        }
        let expected = self
            .root
            .join("workspaces")
            .join(format!("{}-a{}", binding.task, binding.attempt));
        let metadata = fs::symlink_metadata(&binding.path).map_err(|_| "workspace_missing")?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() || expected != binding.path {
            return Err("workspace_path_mismatch".into());
        }
        let top = self.git(&binding.path, &["rev-parse", "--show-toplevel"])?;
        if fs::canonicalize(top.trim()).map_err(|_| "workspace_top_missing")? != binding.path {
            return Err("workspace_top_mismatch".into());
        }
        let common = self.git(&binding.path, &["rev-parse", "--git-common-dir"])?;
        let common = binding.path.join(common.trim());
        if fs::canonicalize(common).map_err(|_| "common_dir_missing")? != self.repo.join(".git") {
            return Err("repository_mismatch".into());
        }
        let branch = self.git(&binding.path, &["symbolic-ref", "--quiet", "HEAD"])?;
        if branch.trim() != format!("refs/heads/{}", binding.branch) {
            return Err("branch_mismatch".into());
        }
        Ok(binding)
    }
    // endregion validate

    // Fixed local file tool, deliberately not an arbitrary command runner.
    fn edit(&self, task: &str, actor: &Actor, content: &str) -> Result<()> {
        let binding = self.validate(task, actor)?;
        if binding.writer.is_some() {
            return Err("writer_busy".into());
        }
        fs::write(binding.path.join("README.md"), content).map_err(|e| e.to_string())
    }

    fn start_writer(&mut self, task: &str, actor: &Actor, content: &'static str) -> Result<()> {
        let binding = self.validate(task, actor)?;
        if binding.writer.is_some() {
            return Err("writer_busy".into());
        }
        let path = binding.path.clone();
        let claims = self.claims.clone();
        let actor = actor.clone();
        let task_name = task.to_owned();
        let (release, receive) = mpsc::channel();
        let (ready, waiting) = mpsc::channel();
        let handle = thread::spawn(move || {
            ready.send(()).map_err(|_| "ready_disconnected")?;
            if !receive.recv().map_err(|_| "release_disconnected")? {
                return Ok(());
            }
            let claims = claims.lock().unwrap();
            if claims.get(&task_name) != Some(&actor) {
                return Err("stale_owner".into());
            }
            fs::write(path.join("README.md"), content).map_err(|e| e.to_string())
        });
        self.bindings.get_mut(task).unwrap().writer = Some(Writer { release, handle });
        waiting.recv().map_err(|_| "worker_start_failed".into())
    }

    fn release_writer(&self, task: &str, write: bool) -> Result<()> {
        self.bindings[task]
            .writer
            .as_ref()
            .ok_or("no_writer")?
            .release
            .send(write)
            .map_err(|_| "worker_disconnected".into())
    }

    fn join_writer(&mut self, task: &str) -> Result<()> {
        let writer = self
            .bindings
            .get_mut(task)
            .ok_or("unknown_binding")?
            .writer
            .take()
            .ok_or("no_writer")?;
        writer.handle.join().map_err(|_| "worker_panicked")?
    }

    fn commit(&self, task: &str, actor: &Actor) -> Result<()> {
        let binding = self.validate(task, actor)?;
        if binding.writer.is_some() {
            return Err("writer_busy".into());
        }
        self.git(&binding.path, &["add", "--", "README.md"])?;
        self.git(&binding.path, &["commit", "-m", &format!("finish {task}")])?;
        Ok(())
    }

    fn retain(&mut self, task: &str, reason: &'static str) -> Result<&'static str> {
        self.bindings
            .get_mut(task)
            .ok_or("unknown_binding")?
            .disposition = Disposition::Retained(reason);
        Ok(reason)
    }

    // region retire
    fn retire(&mut self, task: &str, actor: &Actor) -> Result<&'static str> {
        let binding = self.validate(task, actor)?;
        if binding.writer.is_some() {
            return self.retain(task, "busy");
        }
        let path = binding.path.clone();
        let base = binding.base.clone();
        // -z avoids filename quoting; include ignored files so caches are not silently lost.
        let changes = self.git(
            &path,
            &[
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignored",
            ],
        )?;
        if !changes.is_empty() {
            return self.retain(task, "changes");
        }
        if !self
            .git(
                &self.repo,
                &[
                    "status",
                    "--porcelain=v1",
                    "-z",
                    "--untracked-files=all",
                    "--ignored",
                ],
            )?
            .is_empty()
        {
            return self.retain(task, "target_dirty");
        }
        let head = self.git(&path, &["rev-parse", "HEAD"])?;
        if !self
            .command(&path, &["merge-base", "--is-ancestor", &base, head.trim()])?
            .status
            .success()
        {
            return self.retain(task, "history_changed");
        }
        if !self
            .command(
                &self.repo,
                &["merge-base", "--is-ancestor", head.trim(), "main"],
            )?
            .status
            .success()
        {
            return self.retain(task, "unmerged");
        }
        // Git performs a final safety check. Locked or concurrently changed worktrees remain.
        if self
            .git(
                &self.repo,
                &["worktree", "remove", path.to_str().ok_or("path_encoding")?],
            )
            .is_err()
        {
            return self.retain(task, "git_refused");
        }
        self.bindings.get_mut(task).unwrap().disposition = Disposition::Removed;
        Ok("removed") // Branch refs are deliberately retained for review; no branch deletion.
    }
    // endregion retire

    fn linked_count(&self) -> usize {
        self.git(&self.repo, &["worktree", "list", "--porcelain"])
            .unwrap()
            .lines()
            .filter(|line| line.starts_with("worktree "))
            .count()
            - 1
    }
}

// region shutdown
impl Drop for Lab {
    fn drop(&mut self) {
        // Stop and join hosted writers. Keep worktrees and all files for inspection.
        for binding in self.bindings.values_mut() {
            if let Some(writer) = binding.writer.take() {
                let _ = writer.release.send(false);
                let _ = writer.handle.join();
            }
        }
    }
}
// endregion shutdown

fn actor() -> Actor {
    Actor {
        owner: "worker-a".into(),
        epoch: 1,
    }
}

fn scenario(name: &str, root: &Path) -> Result<String> {
    let mut lab = Lab::create(root)?;
    let owner = actor();
    lab.claim("alpha", &owner);
    lab.claim("beta", &owner);
    let mut lines = vec![format!("scenario={name}")];
    match name {
        "denied" => lines.push(format!(
            "allocate={}",
            lab.allocate("alpha", 1, &owner, false).unwrap_err()
        )),
        "invalid-task" => lines.push(format!(
            "allocate={}",
            lab.allocate("../outside", 1, &owner, true).unwrap_err()
        )),
        "unknown" => lines.push(format!(
            "retire={}",
            lab.retire("alpha", &owner).unwrap_err()
        )),
        "existing-path" => {
            let path = lab.root.join("workspaces/alpha-a1");
            fs::create_dir(&path).unwrap();
            fs::write(path.join("keep.txt"), "keep\n").unwrap();
            lines.push(format!(
                "allocate={}",
                lab.allocate("alpha", 1, &owner, true).unwrap_err()
            ));
        }
        "branch-exists" => {
            lab.git(&lab.repo, &["branch", "codex/r18-alpha-a1"])?;
            lines.push(format!(
                "allocate={}",
                lab.allocate("alpha", 1, &owner, true).unwrap_err()
            ));
        }
        _ => {
            lab.allocate("alpha", 1, &owner, true)?;
            let path = lab.bindings["alpha"].path.clone();
            match name {
                "clean" => lines.push(format!("retire={}", lab.retire("alpha", &owner)?)),
                "parallel" => {
                    lab.allocate("beta", 1, &owner, true)?;
                    lab.start_writer("alpha", &owner, "startup=alpha\n")?;
                    lab.start_writer("beta", &owner, "startup=beta\n")?;
                    lines.push("writers_ready=2 separate_directories=true".into());
                    lab.release_writer("alpha", true)?;
                    lab.release_writer("beta", true)?;
                    lab.join_writer("alpha")?;
                    lab.join_writer("beta")?;
                    let a = fs::read_to_string(path.join("README.md")).unwrap();
                    let b =
                        fs::read_to_string(lab.bindings["beta"].path.join("README.md")).unwrap();
                    lines.push(format!("alpha={} beta={}", a.trim(), b.trim()));
                    lines.push(format!(
                        "retire_alpha={} retire_beta={}",
                        lab.retire("alpha", &owner)?,
                        lab.retire("beta", &owner)?
                    ));
                }
                "tracked" | "staged" | "unmerged" | "accepted" => {
                    lab.edit("alpha", &owner, "startup=alpha\n")?;
                    if name == "staged" {
                        lab.git(&path, &["add", "--", "README.md"])?;
                    }
                    if name == "unmerged" || name == "accepted" {
                        lab.commit("alpha", &owner)?;
                    }
                    if name == "accepted" {
                        // Exercise driver explicitly integrates the reviewed fixture change.
                        lab.git(&lab.repo, &["merge", "--ff-only", "codex/r18-alpha-a1"])?;
                        lines.push("integration=fast_forward".into());
                    }
                    lines.push(format!("retire={}", lab.retire("alpha", &owner)?));
                }
                "untracked" => {
                    fs::write(path.join("notes.txt"), "unfinished\n").unwrap();
                    lines.push(format!("retire={}", lab.retire("alpha", &owner)?));
                }
                "ignored" => {
                    fs::create_dir(path.join("scratch")).unwrap();
                    fs::write(path.join("scratch/cache.bin"), b"keep-cache").unwrap();
                    lines.push(format!("retire={}", lab.retire("alpha", &owner)?));
                }
                "conflict" => {
                    lab.allocate("beta", 1, &owner, true)?;
                    lab.edit("alpha", &owner, "startup=alpha\n")?;
                    lab.edit("beta", &owner, "startup=beta\n")?;
                    lab.commit("alpha", &owner)?;
                    lab.commit("beta", &owner)?;
                    lab.git(&lab.repo, &["merge", "--ff-only", "codex/r18-alpha-a1"])?;
                    let merge =
                        lab.command(&lab.repo, &["merge", "--no-edit", "codex/r18-beta-a1"])?;
                    assert!(!merge.status.success());
                    lines.push("integration=conflict preserved_for_review=true".into());
                    lines.push(format!(
                        "retire_alpha={} retire_beta={}",
                        lab.retire("alpha", &owner)?,
                        lab.retire("beta", &owner)?
                    ));
                }
                "busy" => {
                    lab.start_writer("alpha", &owner, "startup=alpha\n")?;
                    lines.push(format!("before_join={}", lab.retire("alpha", &owner)?));
                    lab.release_writer("alpha", false)?;
                    lab.join_writer("alpha")?;
                    lines.push(format!("after_join={}", lab.retire("alpha", &owner)?));
                }
                "stale" => {
                    lab.start_writer("alpha", &owner, "startup=alpha\n")?;
                    lab.claim(
                        "alpha",
                        &Actor {
                            owner: "worker-b".into(),
                            epoch: 2,
                        },
                    );
                    lab.release_writer("alpha", true)?;
                    lines.push(format!("writer={}", lab.join_writer("alpha").unwrap_err()));
                    lines.push(format!(
                        "edit={} retire={}",
                        lab.edit("alpha", &owner, "bad\n").unwrap_err(),
                        lab.retire("alpha", &owner).unwrap_err()
                    ));
                }
                "duplicate" => lines.push(format!(
                    "allocate={}",
                    lab.allocate("alpha", 2, &owner, true).unwrap_err()
                )),
                "locked" => {
                    lab.git(
                        &lab.repo,
                        &[
                            "worktree",
                            "lock",
                            path.to_str().unwrap(),
                            "--reason",
                            "review in progress",
                        ],
                    )?;
                    lines.push(format!("retire={}", lab.retire("alpha", &owner)?));
                }
                "wrong-branch" => {
                    lab.git(&path, &["checkout", "-b", "codex/manual-review"])?;
                    lines.push(format!(
                        "retire={}",
                        lab.retire("alpha", &owner).unwrap_err()
                    ));
                }
                _ => unreachable!(),
            }
        }
    }
    let primary = fs::read_to_string(lab.repo.join("README.md")).unwrap();
    let removed = lab
        .bindings
        .values()
        .filter(|b| b.disposition == Disposition::Removed)
        .count();
    let retained = lab
        .bindings
        .values()
        .filter(|b| matches!(b.disposition, Disposition::Retained(_)))
        .count();
    lines.push(format!(
        "stats bindings={} linked={} retained={} removed={} primary_baseline={}",
        lab.bindings.len(),
        lab.linked_count(),
        retained,
        removed,
        primary == BASE_TEXT
    ));
    Ok(lines.join("\n") + "\n")
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args.len() != 2 || !SCENARIOS.contains(&args[0].as_str()) {
        eprintln!(
            "usage: worktree-lab [{}] <new-directory>",
            SCENARIOS.join("|")
        );
        std::process::exit(2);
    }
    match scenario(&args[0], Path::new(&args[1])) {
        Ok(output) => print!("{output}"),
        Err(error) => {
            eprintln!("experiment stopped: {error}; keep directory for inspection");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let id = COUNTER.fetch_add(1, Ordering::Relaxed);
            let root = std::env::temp_dir().join(format!("r18-tests-{}-{id}", std::process::id()));
            assert!(!root.exists());
            Self(root)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn setup() -> (Fixture, Lab, Actor) {
        let fixture = Fixture::new();
        let lab = Lab::create(&fixture.0).unwrap();
        let owner = actor();
        lab.claim("alpha", &owner);
        (fixture, lab, owner)
    }

    #[test]
    fn separate_indexes_and_common_object_store() {
        let (_fixture, mut lab, owner) = setup();
        lab.claim("beta", &owner);
        lab.allocate("alpha", 1, &owner, true).unwrap();
        lab.allocate("beta", 1, &owner, true).unwrap();
        let a = &lab.bindings["alpha"].path;
        let b = &lab.bindings["beta"].path;
        lab.git(a, &["add", "README.md"]).unwrap();
        fs::write(a.join("README.md"), "a\n").unwrap();
        lab.git(a, &["add", "README.md"]).unwrap();
        assert!(
            lab.git(a, &["status", "--porcelain"])
                .unwrap()
                .contains("M  README.md")
        );
        assert!(lab.git(b, &["status", "--porcelain"]).unwrap().is_empty());
        assert_eq!(fs::read_to_string(b.join("README.md")).unwrap(), BASE_TEXT);
        assert!(
            lab.git(a, &["rev-parse", "--git-common-dir"])
                .unwrap()
                .contains("repository/.git")
        );
    }

    #[test]
    fn clean_removed_but_branch_ref_survives() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "removed");
        assert_eq!(lab.linked_count(), 0);
        assert!(
            lab.git(
                &lab.repo,
                &["show-ref", "--verify", "refs/heads/codex/r18-alpha-a1"]
            )
            .is_ok()
        );
        assert_eq!(lab.retire("alpha", &owner).unwrap_err(), "already_removed");
    }

    #[test]
    fn ignored_files_are_retained() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        let path = lab.bindings["alpha"].path.clone();
        fs::create_dir(path.join("scratch")).unwrap();
        fs::write(path.join("scratch/value"), "keep").unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "changes");
        assert_eq!(
            fs::read_to_string(path.join("scratch/value")).unwrap(),
            "keep"
        );
    }

    #[test]
    fn unmerged_commit_is_retained_until_explicit_integration() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        lab.edit("alpha", &owner, "edited\n").unwrap();
        lab.commit("alpha", &owner).unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "unmerged");
        lab.git(&lab.repo, &["merge", "--ff-only", "codex/r18-alpha-a1"])
            .unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "removed");
        assert_eq!(
            fs::read_to_string(lab.repo.join("README.md")).unwrap(),
            "edited\n"
        );
    }

    #[test]
    fn owner_epoch_is_checked_before_dispatch_and_after_worker_gate() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        lab.start_writer("alpha", &owner, "wrong\n").unwrap();
        lab.claim(
            "alpha",
            &Actor {
                owner: owner.owner.clone(),
                epoch: 2,
            },
        );
        lab.release_writer("alpha", true).unwrap();
        assert_eq!(lab.join_writer("alpha").unwrap_err(), "stale_owner");
        assert_eq!(lab.retire("alpha", &owner).unwrap_err(), "stale_owner");
        assert_eq!(
            fs::read_to_string(lab.bindings["alpha"].path.join("README.md")).unwrap(),
            BASE_TEXT
        );
    }

    #[test]
    fn writer_must_be_joined_before_remove() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        lab.start_writer("alpha", &owner, "unused\n").unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "busy");
        lab.release_writer("alpha", false).unwrap();
        lab.join_writer("alpha").unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "removed");
    }

    #[test]
    fn drop_joins_writer_and_preserves_worktree() {
        let (fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        lab.start_writer("alpha", &owner, "unused\n").unwrap();
        drop(lab);
        assert_eq!(
            fs::read_to_string(fixture.0.join("workspaces/alpha-a1/README.md")).unwrap(),
            BASE_TEXT
        );
    }

    #[test]
    fn permissions_and_identity_rejection_have_no_git_side_effect() {
        let (_fixture, mut lab, owner) = setup();
        assert_eq!(
            lab.allocate("alpha", 1, &owner, false).unwrap_err(),
            "permission_denied"
        );
        assert_eq!(
            lab.allocate("../escape", 1, &owner, true).unwrap_err(),
            "invalid_identity"
        );
        assert_eq!(
            lab.allocate("alpha", 0, &owner, true).unwrap_err(),
            "invalid_identity"
        );
        assert_eq!(lab.linked_count(), 0);
        assert!(
            lab.git(
                &lab.repo,
                &["show-ref", "--verify", "refs/heads/codex/r18-alpha-a1"]
            )
            .is_err()
        );
    }

    #[test]
    fn existing_root_and_existing_worktree_path_are_preserved() {
        let (fixture, mut lab, owner) = setup();
        assert!(Lab::create(&fixture.0).is_err());
        let path = lab.root.join("workspaces/alpha-a1");
        fs::create_dir(&path).unwrap();
        fs::write(path.join("keep"), "keep").unwrap();
        assert_eq!(
            lab.allocate("alpha", 1, &owner, true).unwrap_err(),
            "path_exists"
        );
        assert_eq!(fs::read_to_string(path.join("keep")).unwrap(), "keep");
    }

    #[test]
    fn changed_branch_and_lock_stop_cleanup() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        let path = lab.bindings["alpha"].path.clone();
        lab.git(&lab.repo, &["worktree", "lock", path.to_str().unwrap()])
            .unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap(), "git_refused");
        lab.git(&path, &["checkout", "-b", "codex/elsewhere"])
            .unwrap();
        assert_eq!(lab.retire("alpha", &owner).unwrap_err(), "branch_mismatch");
        assert!(path.exists());
    }

    #[test]
    fn missing_directory_does_not_trigger_prune_or_recreation() {
        let (_fixture, mut lab, owner) = setup();
        lab.allocate("alpha", 1, &owner, true).unwrap();
        fs::remove_dir_all(&lab.bindings["alpha"].path).unwrap(); // Fault injection in fixture only.
        assert_eq!(
            lab.retire("alpha", &owner).unwrap_err(),
            "workspace_missing"
        );
        assert_eq!(lab.linked_count(), 1); // Registration intentionally remains for diagnosis.
    }

    #[cfg(unix)]
    #[test]
    fn symlink_target_is_never_removed() {
        use std::os::unix::fs::symlink;
        let (_fixture, mut lab, owner) = setup();
        let outside = lab.root.join("outside");
        fs::create_dir(&outside).unwrap();
        fs::write(outside.join("keep"), "keep").unwrap();
        symlink(&outside, lab.root.join("workspaces/alpha-a1")).unwrap();
        assert_eq!(
            lab.allocate("alpha", 1, &owner, true).unwrap_err(),
            "path_exists"
        );
        assert_eq!(fs::read_to_string(outside.join("keep")).unwrap(), "keep");
    }
}
