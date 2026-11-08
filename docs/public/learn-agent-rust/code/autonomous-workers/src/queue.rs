use rusqlite::{
    Connection, ErrorCode, OpenFlags, OptionalExtension, Transaction, TransactionBehavior, params,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug, PartialEq, Eq)]
pub struct Error(pub &'static str);

impl From<rusqlite::Error> for Error {
    fn from(error: rusqlite::Error) -> Self {
        match error.sqlite_error_code() {
            Some(ErrorCode::DatabaseBusy | ErrorCode::DatabaseLocked) => Self("store_busy"),
            _ => Self("store_error"),
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub enum Command {
    Init {},
    Add {
        id: String,
        title: String,
        max_claims: i64,
    },
    Show {},
    Claim {
        owner: String,
        now: Option<i64>,
        ttl: i64,
    },
    Renew {
        id: String,
        owner: String,
        token: i64,
        now: Option<i64>,
        ttl: i64,
    },
    Complete {
        id: String,
        owner: String,
        token: i64,
        now: Option<i64>,
        result: String,
    },
    Work {
        owner: String,
        now: Option<i64>,
        ttl: i64,
        ledger: PathBuf,
        dedupe: bool,
    },
    Effects {},
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Fault {
    None,
    Gate,
    Hold,
    BeforeCommit,
    AfterCommit,
    Fail,
    AfterEffect,
}
impl Fault {
    pub fn parse(value: Option<&str>) -> Result<Self> {
        match value {
            None => Ok(Self::None),
            Some("--gate") => Ok(Self::Gate),
            Some("--hold") => Ok(Self::Hold),
            Some("--exit-before-commit") => Ok(Self::BeforeCommit),
            Some("--exit-after-commit") => Ok(Self::AfterCommit),
            Some("--fail-before-commit") => Ok(Self::Fail),
            Some("--exit-after-effect") => Ok(Self::AfterEffect),
            _ => Err(Error("invalid_fault")),
        }
    }
}

pub fn barrier(event: &str) -> Result<()> {
    println!("{}", json!({"event":event}));
    std::io::stdout()
        .flush()
        .map_err(|_| Error("output_failed"))?;
    let mut byte = [0];
    std::io::stdin()
        .read_exact(&mut byte)
        .map_err(|_| Error("gate_closed"))
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 40
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
}
fn detail(value: &str, limit: usize) -> bool {
    !value.trim().is_empty() && value.len() <= limit
}
fn credential(id: &str, owner: &str, token: i64) -> Result<()> {
    if !identifier(id) || !identifier(owner) || !(1..=8).contains(&token) {
        return Err(Error("invalid_credential"));
    }
    Ok(())
}
fn deadline(now: i64, ttl: i64) -> Result<i64> {
    if !(1..=3600).contains(&ttl) {
        return Err(Error("invalid_ttl"));
    }
    now.checked_add(ttl)
        .filter(|v| *v <= 4_000_000_000)
        .ok_or(Error("time_limit"))
}

pub struct Queue {
    db: Connection,
}
impl Queue {
    pub fn open(path: &Path, initialize: bool) -> Result<Self> {
        let mut flags = OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX;
        if initialize {
            flags |= OpenFlags::SQLITE_OPEN_CREATE;
        }
        let db = Connection::open_with_flags(path, flags)?;
        db.busy_timeout(Duration::ZERO)?;
        db.pragma_update(None, "synchronous", "FULL")?;
        let version: i64 = db.pragma_query_value(None, "user_version", |r| r.get(0))?;
        if version != if initialize { 0 } else { 1 } {
            return Err(Error("schema_version"));
        }
        Ok(Self { db })
    }

    #[cfg(test)]
    pub fn memory() -> Self {
        let mut queue = Self {
            db: Connection::open_in_memory().unwrap(),
        };
        queue.apply(Command::Init {}, Fault::None).unwrap();
        queue
    }

    // region schema
    fn initialize(tx: &Transaction<'_>) -> Result<Value> {
        tx.execute_batch("CREATE TABLE meta (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            last_now INTEGER NOT NULL CHECK(last_now BETWEEN 0 AND 4000000000));
            INSERT INTO meta VALUES (1,0);
            CREATE TABLE tasks (
            id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','running','done')),
            token INTEGER NOT NULL CHECK(token BETWEEN 0 AND 8),
            max_claims INTEGER NOT NULL CHECK(max_claims BETWEEN 1 AND 8 AND token<=max_claims),
            owner TEXT, lease_until INTEGER, result TEXT,
            CHECK ((state='pending' AND token=0 AND owner IS NULL AND lease_until IS NULL AND result IS NULL)
                OR (state='running' AND token>0 AND owner IS NOT NULL AND lease_until IS NOT NULL AND result IS NULL)
                OR (state='done' AND token>0 AND owner IS NOT NULL AND lease_until IS NOT NULL AND result IS NOT NULL)));
            PRAGMA user_version=1;")?;
        Ok(json!({"status":"initialized"}))
    }
    // endregion schema

    // region clock
    fn clock(tx: &Transaction<'_>, fixture: Option<i64>) -> Result<i64> {
        // Sample the real clock only AFTER acquiring the write transaction.
        let now = match fixture {
            Some(value) => value,
            None => i64::try_from(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map_err(|_| Error("invalid_time"))?
                    .as_secs(),
            )
            .map_err(|_| Error("invalid_time"))?,
        };
        if !(0..=4_000_000_000).contains(&now) {
            return Err(Error("invalid_time"));
        }
        let last: i64 = tx.query_row("SELECT last_now FROM meta WHERE singleton=1", [], |r| {
            r.get(0)
        })?;
        if now < last {
            return Err(Error("clock_regression"));
        }
        tx.execute("UPDATE meta SET last_now=?1 WHERE singleton=1", [now])?;
        Ok(now)
    }
    // endregion clock

    fn task(tx: &Connection, id: &str) -> Result<Value> {
        Ok(tx.query_row("SELECT id,title,state,token,max_claims,owner,lease_until,result FROM tasks WHERE id=?1", [id], |r| {
            Ok(json!({"id":r.get::<_,String>(0)?,"title":r.get::<_,String>(1)?,"state":r.get::<_,String>(2)?,
                "token":r.get::<_,i64>(3)?,"max_claims":r.get::<_,i64>(4)?,"owner":r.get::<_,Option<String>>(5)?,
                "lease_until":r.get::<_,Option<i64>>(6)?,"result":r.get::<_,Option<String>>(7)?}))
        })?)
    }

    fn snapshot(&self) -> Result<Value> {
        let tx = self.db.unchecked_transaction()?;
        let mut stmt = tx.prepare("SELECT id FROM tasks ORDER BY id")?;
        let ids = stmt
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        let tasks = ids
            .iter()
            .map(|id| Self::task(&tx, id))
            .collect::<Result<Vec<_>>>()?;
        let now: i64 = tx.query_row("SELECT last_now FROM meta WHERE singleton=1", [], |r| {
            r.get(0)
        })?;
        Ok(json!({"status":"snapshot","last_now":now,"tasks":tasks}))
    }

    // region claim
    fn claim(tx: &Transaction<'_>, owner: &str, now: i64, ttl: i64) -> Result<Value> {
        if !identifier(owner) {
            return Err(Error("invalid_owner"));
        }
        let until = deadline(now, ttl)?;
        let id: Option<String> = tx
            .query_row(
                "SELECT id FROM tasks WHERE token<max_claims AND
             (state='pending' OR (state='running' AND lease_until<=?1)) ORDER BY id LIMIT 1",
                [now],
                |r| r.get(0),
            )
            .optional()?;
        let Some(id) = id else {
            return Ok(json!({"status":"empty","now":now}));
        };
        let changed = tx.execute(
            "UPDATE tasks SET state='running',owner=?1,token=token+1,lease_until=?2
             WHERE id=?3 AND token<max_claims AND
             (state='pending' OR (state='running' AND lease_until<=?4))",
            params![owner, until, id, now],
        )?;
        if changed != 1 {
            return Err(Error("claim_conflict"));
        }
        Ok(json!({"status":"claimed","now":now,"task":Self::task(tx,&id)?}))
    }
    // endregion claim

    // region renew
    fn renew(
        tx: &Transaction<'_>,
        id: &str,
        owner: &str,
        token: i64,
        now: i64,
        ttl: i64,
    ) -> Result<Value> {
        credential(id, owner, token)?;
        let until = deadline(now, ttl)?;
        let changed = tx.execute(
            "UPDATE tasks SET lease_until=?1 WHERE id=?2 AND state='running'
             AND owner=?3 AND token=?4 AND lease_until>?5 AND lease_until<?1",
            params![until, id, owner, token, now],
        )?;
        if changed != 1 {
            return Err(Error("lease_rejected"));
        }
        Ok(json!({"status":"renewed","now":now,"task":Self::task(tx,id)?}))
    }
    // endregion renew

    // region complete
    fn complete(
        tx: &Transaction<'_>,
        id: &str,
        owner: &str,
        token: i64,
        now: i64,
        result: &str,
    ) -> Result<Value> {
        credential(id, owner, token)?;
        if !detail(result, 512) {
            return Err(Error("invalid_result"));
        }
        let changed = tx.execute(
            "UPDATE tasks SET state='done',result=?1 WHERE id=?2 AND state='running'
             AND owner=?3 AND token=?4 AND lease_until>?5",
            params![result, id, owner, token, now],
        )?;
        if changed != 1 {
            return Err(Error("lease_rejected"));
        }
        Ok(json!({"status":"completed","now":now,"task":Self::task(tx,id)?}))
    }
    // endregion complete

    // region transaction
    pub fn apply(&mut self, command: Command, fault: Fault) -> Result<Value> {
        if matches!(command, Command::Show {}) {
            if fault != Fault::None {
                return Err(Error("invalid_fault"));
            }
            return self.snapshot();
        }
        if fault == Fault::Gate {
            barrier("ready")?;
        }
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let value = match command {
            Command::Init {} => Self::initialize(&tx)?,
            Command::Add {
                id,
                title,
                max_claims,
            } => {
                if !identifier(&id) || !detail(&title, 160) || !(1..=8).contains(&max_claims) {
                    return Err(Error("invalid_task"));
                }
                let exists: bool = tx.query_row(
                    "SELECT EXISTS(SELECT 1 FROM tasks WHERE id=?1)",
                    [&id],
                    |r| r.get(0),
                )?;
                if exists {
                    return Err(Error("duplicate_id"));
                }
                let count: i64 = tx.query_row("SELECT count(*) FROM tasks", [], |r| r.get(0))?;
                if count >= 32 {
                    return Err(Error("task_limit"));
                }
                tx.execute("INSERT INTO tasks(id,title,state,token,max_claims) VALUES (?1,?2,'pending',0,?3)", params![id,title,max_claims])?;
                json!({"status":"added","task":Self::task(&tx,&id)?})
            }
            Command::Claim { owner, now, ttl } => {
                let now = Self::clock(&tx, now)?;
                Self::claim(&tx, &owner, now, ttl)?
            }
            Command::Renew {
                id,
                owner,
                token,
                now,
                ttl,
            } => {
                let now = Self::clock(&tx, now)?;
                Self::renew(&tx, &id, &owner, token, now, ttl)?
            }
            Command::Complete {
                id,
                owner,
                token,
                now,
                result,
            } => {
                let now = Self::clock(&tx, now)?;
                Self::complete(&tx, &id, &owner, token, now, &result)?
            }
            _ => return Err(Error("invalid_command")),
        };
        if fault == Fault::Hold {
            barrier("updated_uncommitted")?;
        }
        if fault == Fault::Fail {
            return Err(Error("injected_failure"));
        }
        if fault == Fault::BeforeCommit {
            std::process::exit(73);
        }
        tx.commit()?;
        if fault == Fault::AfterCommit {
            std::process::exit(74);
        }
        Ok(value) // Dispatch external work only after this successful commit.
    }
    // endregion transaction
}
