use crate::state::{Error, Result, State, identifier};
use postgres::{Client, NoTls, Transaction};
use serde_json::{Value, json};
use std::io::{Read, Write};

impl From<postgres::Error> for Error {
    fn from(error: postgres::Error) -> Self {
        let code = error.code().map(|s| s.code());
        Self(match code {
            Some("55P03") => "store_busy",
            Some("57014") => "store_timeout",
            Some("23505") => "duplicate_session",
            _ => "store_unavailable",
        })
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Fault {
    None,
    Gate,
    Hold,
    Fail,
    BeforeCommit,
    AfterCommit,
    AfterAction,
    AfterModel,
}
impl Fault {
    pub fn parse(input: Option<&str>) -> Result<Self> {
        match input {
            None => Ok(Self::None),
            Some("--gate") => Ok(Self::Gate),
            Some("--hold") => Ok(Self::Hold),
            Some("--fail-before-commit") => Ok(Self::Fail),
            Some("--exit-before-commit") => Ok(Self::BeforeCommit),
            Some("--exit-after-commit") => Ok(Self::AfterCommit),
            Some("--exit-after-action") => Ok(Self::AfterAction),
            Some("--exit-after-model") => Ok(Self::AfterModel),
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

pub struct Store {
    pub client: Client,
}
impl Store {
    pub fn connect() -> Result<Self> {
        let config =
            std::env::var("P01_DATABASE_URL").map_err(|_| Error("missing_database_url"))?;
        let mut client = Client::connect(&config, NoTls)?;
        client.batch_execute("SET statement_timeout='5s'; SET lock_timeout='1s'; SET synchronous_commit=on; SET default_transaction_isolation='read committed'")?;
        Ok(Self { client })
    }

    // region schema
    pub fn initialize(&mut self) -> Result<Value> {
        self.client.batch_execute("BEGIN;
            CREATE TABLE p01_sessions (
              session_id TEXT PRIMARY KEY, revision BIGINT NOT NULL CHECK(revision>=0),
              format_version INTEGER NOT NULL, workflow_version TEXT NOT NULL, state JSONB NOT NULL);
            CREATE TABLE p01_checkpoints (
              session_id TEXT NOT NULL REFERENCES p01_sessions(session_id),
              revision BIGINT NOT NULL CHECK(revision>=0), save_id TEXT NOT NULL,
              state JSONB NOT NULL,
              PRIMARY KEY(session_id, revision), UNIQUE(session_id,save_id));
            COMMIT;")?;
        Ok(json!({"status":"initialized"}))
    }
    // endregion schema

    pub fn create(&mut self, id: &str, state: State) -> Result<Value> {
        if !identifier(id) {
            return Err(Error("invalid_id"));
        }
        state.validate()?;
        let value = serde_json::to_value(&state).map_err(|_| Error("encode_failed"))?;
        let mut tx = self.client.transaction()?;
        tx.execute(
            "INSERT INTO p01_sessions VALUES ($1,0,1,'p01-v1',$2)",
            &[&id, &value],
        )?;
        tx.execute(
            "INSERT INTO p01_checkpoints VALUES ($1,0,'initial',$2)",
            &[&id, &value],
        )?;
        tx.commit()?;
        Ok(json!({"status":"created","revision":0,"state":state}))
    }

    fn decode(row: &postgres::Row) -> Result<(i64, State)> {
        let revision: i64 = row.get("revision");
        let format: i32 = row.get("format_version");
        let workflow: String = row.get("workflow_version");
        if format != 1 {
            return Err(Error("format_version"));
        }
        if workflow != "p01-v1" {
            return Err(Error("workflow_version"));
        }
        let value: Value = row.get("state");
        let state: State = serde_json::from_value(value).map_err(|_| Error("corrupt_state"))?;
        state.validate()?;
        if revision < 0 {
            return Err(Error("corrupt_state"));
        }
        Ok((revision, state))
    }

    pub fn load(&mut self, id: &str) -> Result<(i64, State)> {
        if !identifier(id) {
            return Err(Error("invalid_id"));
        }
        let row = self
            .client
            .query_opt("SELECT * FROM p01_sessions WHERE session_id=$1", &[&id])?
            .ok_or(Error("session_missing"))?;
        Self::decode(&row)
    }

    fn existing(
        tx: &mut Transaction<'_>,
        id: &str,
        save_id: &str,
        expected: i64,
        value: &Value,
    ) -> Result<Option<i64>> {
        if let Some(row) = tx.query_opt(
            "SELECT revision,state FROM p01_checkpoints WHERE session_id=$1 AND save_id=$2",
            &[&id, &save_id],
        )? {
            let revision: i64 = row.get(0);
            let saved: Value = row.get(1);
            if revision != expected + 1 || saved != *value {
                return Err(Error("save_identity_conflict"));
            }
            return Ok(Some(revision));
        }
        Ok(None)
    }

    // region save
    pub fn save(
        &mut self,
        id: &str,
        expected: i64,
        save_id: &str,
        state: &State,
        fault: Fault,
    ) -> Result<Value> {
        if !identifier(id) || !identifier(save_id) || !(0..1000).contains(&expected) {
            return Err(Error("invalid_save"));
        }
        state.validate()?;
        let value = serde_json::to_value(state).map_err(|_| Error("encode_failed"))?;
        if fault == Fault::Gate {
            barrier("ready")?;
        }
        let mut tx = self.client.transaction()?;
        let row = tx
            .query_opt(
                "SELECT * FROM p01_sessions WHERE session_id=$1 FOR UPDATE NOWAIT",
                &[&id],
            )?
            .ok_or(Error("session_missing"))?;
        let (current, _) = Self::decode(&row)?;
        if let Some(revision) = Self::existing(&mut tx, id, save_id, expected, &value)? {
            return Ok(json!({"status":"saved","revision":revision,"replayed":true}));
        }
        if current != expected {
            return Err(Error("revision_conflict"));
        }
        let revision = expected + 1;
        let changed = tx.execute(
            "UPDATE p01_sessions SET revision=$1,state=$2 WHERE session_id=$3 AND revision=$4",
            &[&revision, &value, &id, &expected],
        )?;
        if changed != 1 {
            return Err(Error("revision_conflict"));
        }
        tx.execute(
            "INSERT INTO p01_checkpoints VALUES ($1,$2,$3,$4)",
            &[&id, &revision, &save_id, &value],
        )?;
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
        Ok(json!({"status":"saved","revision":revision,"replayed":false}))
    }
    // endregion save

    pub fn snapshot(&mut self, id: &str) -> Result<Value> {
        let (revision, state) = self.load(id)?;
        Ok(json!({"status":"snapshot","revision":revision,"state":state}))
    }

    pub fn history(&mut self, id: &str) -> Result<Value> {
        self.load(id)?;
        let rows=self.client.query("SELECT revision,save_id,state FROM p01_checkpoints WHERE session_id=$1 ORDER BY revision",&[&id])?;
        let checkpoints:Vec<_>=rows.iter().map(|r| json!({"revision":r.get::<_,i64>(0),"save_id":r.get::<_,String>(1),"state":r.get::<_,Value>(2)})).collect();
        Ok(json!({"status":"history","checkpoints":checkpoints}))
    }
}
