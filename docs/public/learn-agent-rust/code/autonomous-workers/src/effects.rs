//! A local business-service fixture. It deliberately does NOT enforce queue leases.
use crate::queue::{Error, Result};
use rusqlite::{Connection, OpenFlags, TransactionBehavior, params};
use serde_json::{Value, json};
use std::path::Path;
use std::time::Duration;

// region effect
pub fn deliver(path: &Path, task: &str, token: i64, dedupe: bool) -> Result<Value> {
    let mut db = Connection::open(path)?;
    db.busy_timeout(Duration::ZERO)?;
    db.pragma_update(None, "synchronous", "FULL")?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch("CREATE TABLE IF NOT EXISTS calls (n INTEGER PRIMARY KEY, operation TEXT NOT NULL, token INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reports (n INTEGER PRIMARY KEY, operation TEXT NOT NULL, token INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS accepted (operation TEXT PRIMARY KEY NOT NULL);")?;
    // Stable across lease generations. No attempt/token in the operation identity.
    let operation = format!("report:{task}");
    tx.execute(
        "INSERT INTO calls(operation,token) VALUES (?1,?2)",
        params![operation, token],
    )?;
    let inserted = if dedupe {
        tx.execute(
            "INSERT OR IGNORE INTO accepted(operation) VALUES (?1)",
            [&operation],
        )? == 1
    } else {
        true
    };
    if inserted {
        tx.execute(
            "INSERT INTO reports(operation,token) VALUES (?1,?2)",
            params![operation, token],
        )?;
    }
    tx.commit()?; // The queue completion is a later, separate transaction.
    Ok(json!({"operation":operation,"token":token,"inserted":inserted,"dedupe":dedupe}))
}
// endregion effect

pub fn snapshot(path: &Path) -> Result<Value> {
    let db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let tx = db.unchecked_transaction()?;
    let mut tables = serde_json::Map::new();
    for table in ["calls", "reports"] {
        let mut stmt = tx.prepare(&format!("SELECT operation,token FROM {table} ORDER BY n"))?;
        let rows = stmt
            .query_map([], |r| {
                Ok(json!({"operation":r.get::<_,String>(0)?,"token":r.get::<_,i64>(1)?}))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        tables.insert(table.into(), Value::Array(rows));
    }
    if tables.len() != 2 {
        return Err(Error("invalid_ledger"));
    }
    tables.insert("status".into(), json!("effects"));
    Ok(Value::Object(tables))
}
