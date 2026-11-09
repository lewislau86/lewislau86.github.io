use crate::AnyError;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::path::Path;

pub struct Store(pub Connection);
impl Store {
    pub fn open(path: &Path) -> Result<Self, AnyError> {
        let db = Connection::open(path)?;
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS task (trigger_id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL, owner TEXT, epoch INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS event (seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
            call_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL);")?;
        Ok(Self(db))
    }
    // region intake
    pub fn trigger(&self) -> Result<usize, AnyError> {
        // A fixed due trigger supplied by the test clock. Scheduling rules remain R14's job.
        Ok(self.0.execute(
            "INSERT OR IGNORE INTO task(trigger_id,task_id,status) VALUES (?1,?2,'queued')",
            params!["startup@2026-11-08T08:00:00+08:00", "startup-1"],
        )?)
    }
    pub fn claim(&self) -> Result<(), AnyError> {
        let changed = self.0.execute(
            "UPDATE task SET status='running',owner='lead',epoch=1
            WHERE task_id='startup-1' AND status='queued'",
            [],
        )?;
        if changed != 1 {
            return Err("claim_refused".into());
        }
        Ok(())
    }
    pub fn owned(&self) -> bool {
        self.0
            .query_row(
                "SELECT count(*) FROM task WHERE task_id='startup-1' AND status='running'
            AND owner='lead' AND epoch=1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .unwrap()
            == 1
    }
    // endregion intake
    pub fn event(&self, call: Option<&str>, kind: &str, detail: &str) {
        self.0
            .execute(
                "INSERT INTO event(task_id,call_id,kind,detail) VALUES ('startup-1',?1,?2,?3)",
                params![call, kind, detail],
            )
            .unwrap();
    }
    // region terminal
    pub fn terminal(&mut self, success: bool, fail_before_commit: bool) -> Result<(), AnyError> {
        let tx = self.0.transaction()?;
        let changed = tx.execute("UPDATE task SET status=?1 WHERE task_id='startup-1' AND owner='lead' AND epoch=1 AND status='running'",
            [if success { "completed" } else { "failed" }])?;
        if changed != 1 {
            return Err("stale_owner".into());
        }
        if success {
            tx.execute(
                "INSERT OR REPLACE INTO memory VALUES ('startup-report','report.txt verified')",
                [],
            )?;
        }
        tx.execute(
            "INSERT INTO event(task_id,kind,detail) VALUES ('startup-1','terminal',?1)",
            [if success { "completed" } else { "failed" }],
        )?;
        if fail_before_commit {
            return Err("injected_before_terminal_commit".into());
        }
        tx.commit()?;
        Ok(())
    }
    // endregion terminal
    pub fn snapshot(&self) -> Value {
        let (status, owner, epoch): (String, Option<String>, i64) = self
            .0
            .query_row(
                "SELECT status,owner,epoch FROM task WHERE task_id='startup-1'",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .unwrap();
        let memory: i64 = self
            .0
            .query_row("SELECT count(*) FROM memory", [], |r| r.get(0))
            .unwrap();
        let mut query = self
            .0
            .prepare("SELECT seq,call_id,kind,detail FROM event ORDER BY seq")
            .unwrap();
        let events: Vec<Value> = query
            .query_map([], |r| {
                Ok(
                    json!({"seq":r.get::<_,i64>(0)?,"call_id":r.get::<_,Option<String>>(1)?,
            "kind":r.get::<_,String>(2)?,"detail":r.get::<_,String>(3)?}),
                )
            })
            .unwrap()
            .map(Result::unwrap)
            .collect();
        json!({"status":status,"owner":owner,"epoch":epoch,"memory_records":memory,"events":events})
    }
}
