use crate::tasks::{Board, Error, Result, Update};
use serde_json::{Value, json};
use std::fs::{self, File, OpenOptions, TryLockError};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

const MAX_BYTES: u64 = 65536;

#[derive(Clone, Copy)]
pub enum Fault {
    None,
    BeforeRename,
    AfterRename,
    PauseBeforeRename,
    PauseAfterCommit,
}

struct Pending(PathBuf);
impl Drop for Pending {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

pub struct Storage {
    root: PathBuf,
    _lock: File,
}

fn regular(path: &Path, missing: &'static str) -> Result<()> {
    match fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_file() => Ok(()),
        Ok(_) => Err(Error::before("invalid_store_file")),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Err(Error::before(missing)),
        Err(_) => Err(Error::before("read_failed")),
    }
}

fn barrier(event: &str, committed: bool) -> Result<()> {
    println!("{}", json!({"event":event}));
    std::io::stdout().flush().map_err(|_| Error {
        code: "output_failed",
        committed,
    })?;
    let mut byte = [0];
    std::io::stdin().read_exact(&mut byte).map_err(|_| Error {
        code: "barrier_closed",
        committed,
    })
}

impl Storage {
    // region lock
    pub fn open(root: &Path, initialize: bool) -> Result<Self> {
        if initialize {
            fs::create_dir_all(root).map_err(|_| Error::before("store_unavailable"))?;
        }
        if !root.is_dir() {
            return Err(Error::before("store_missing"));
        }
        let path = root.join(".tasks.lock");
        match fs::symlink_metadata(&path) {
            Ok(meta) if !meta.file_type().is_file() => {
                return Err(Error::before("invalid_lock_file"));
            }
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => {
                return Err(Error::before("lock_failed"));
            }
            _ => {}
        }
        let lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .map_err(|_| Error::before("lock_failed"))?;
        match lock.try_lock() {
            Ok(()) => Ok(Self {
                root: root.to_path_buf(),
                _lock: lock,
            }),
            Err(TryLockError::WouldBlock) => Err(Error::before("store_busy")),
            Err(TryLockError::Error(_)) => Err(Error::before("lock_failed")),
        }
    }
    // endregion lock

    // region load
    pub fn load(&self) -> Result<Board> {
        let path = self.root.join("tasks.json");
        regular(&path, "store_missing")?;
        let mut bytes = Vec::new();
        File::open(path)
            .map_err(|_| Error::before("read_failed"))?
            .take(MAX_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| Error::before("read_failed"))?;
        if bytes.len() as u64 > MAX_BYTES {
            return Err(Error::before("size_limit"));
        }
        let board: Board =
            serde_json::from_slice(&bytes).map_err(|_| Error::before("corrupt_store"))?;
        board.validate()?;
        Ok(board)
    }
    // endregion load

    // region save
    fn save(&self, board: &Board, fault: Fault) -> Result<()> {
        board.validate()?;
        let mut bytes =
            serde_json::to_vec_pretty(board).map_err(|_| Error::before("encode_failed"))?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_BYTES {
            return Err(Error::before("size_limit"));
        }
        let pending = self.root.join(".tasks.pending");
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&pending)
            .map_err(|_| Error::before("pending_unavailable"))?;
        let _cleanup = Pending(pending.clone()); // Only remove the temporary file we created.
        file.write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| Error::before("save_failed"))?;
        drop(file);
        if matches!(fault, Fault::BeforeRename) {
            return Err(Error::before("injected_before_rename"));
        }
        if matches!(fault, Fault::PauseBeforeRename) {
            barrier("before_rename", false)?;
        }
        fs::rename(&pending, self.root.join("tasks.json"))
            .map_err(|_| Error::before("rename_failed"))?;
        if matches!(fault, Fault::AfterRename) {
            return Err(Error::after("durability_unknown"));
        }
        #[cfg(unix)]
        File::open(&self.root)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| Error::after("durability_unknown"))?;
        if matches!(fault, Fault::PauseAfterCommit) {
            barrier("after_commit", true)?;
        }
        Ok(())
    }
    // endregion save

    pub fn initialize(&self) -> Result<Value> {
        match fs::symlink_metadata(self.root.join("tasks.json")) {
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            _ => return Err(Error::before("store_exists")),
        }
        let board = Board::empty();
        self.save(&board, Fault::None)?;
        Ok(view(&board))
    }

    // region transaction
    pub fn apply(&self, expected: u64, update: Update, fault: Fault) -> Result<Value> {
        let current = self.load()?;
        let candidate = current.propose(expected, update)?;
        self.save(&candidate, fault)?;
        Ok(view(&candidate)) // Acknowledgement comes after the save boundary.
    }
    // endregion transaction
}

pub fn view(board: &Board) -> Value {
    json!({"status":"ok", "revision":board.revision, "ready":board.ready(),
           "reconcile":board.reconcile(), "board":board})
}
