use crate::{Receipt, Request, Result, crash, database};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::path::Path;

fn open(path: &Path) -> Result<rusqlite::Connection> {
    let db = database(path)?;
    db.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT, tenant TEXT NOT NULL,
            operation_id TEXT NOT NULL, request TEXT NOT NULL, digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS keys(
            tenant TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL,
            receipt TEXT NOT NULL, expires_at INTEGER NOT NULL,
            PRIMARY KEY(tenant, operation_id));
        CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, action TEXT NOT NULL);
    ",
    )?;
    Ok(db)
}

// region provider-transaction
pub fn apply(path: &Path, request: Request, mode: &str, now: i64, fault: &str) -> Result<Value> {
    request.validate()?;
    if !matches!(mode, "key" | "none") || now < 0 {
        return Err("invalid_provider_argument".into());
    }
    let mut db = open(path)?;
    // The key reservation, business row, and reusable receipt share one transaction.
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute("INSERT INTO calls(action) VALUES('apply')", [])?;
    let digest = request.digest();
    if mode == "key" {
        let saved: Option<(String, String, i64)> = tx
            .query_row(
                "SELECT digest, receipt, expires_at FROM keys WHERE tenant=?1 AND operation_id=?2",
                params![request.tenant, request.operation_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        if let Some((original, receipt, expires_at)) = saved {
            if now < expires_at {
                if original != digest {
                    tx.commit()?;
                    return Err("idempotency_conflict".into());
                }
                tx.commit()?;
                return Ok(
                    json!({"replayed":true,"receipt":serde_json::from_str::<Receipt>(&receipt)?}),
                );
            }
            tx.execute(
                "DELETE FROM keys WHERE tenant=?1 AND operation_id=?2",
                params![request.tenant, request.operation_id],
            )?;
        }
    }
    let serialized = serde_json::to_string(&request)?;
    tx.execute(
        "INSERT INTO tickets(tenant,operation_id,request,digest) VALUES(?1,?2,?3,?4)",
        params![request.tenant, request.operation_id, serialized, digest],
    )?;
    let receipt = Receipt {
        ticket_id: tx.last_insert_rowid(),
        request,
        digest,
    };
    if mode == "key" {
        tx.execute(
            "INSERT INTO keys VALUES(?1,?2,?3,?4,?5)",
            params![
                receipt.request.tenant,
                receipt.request.operation_id,
                receipt.digest,
                serde_json::to_string(&receipt)?,
                now.checked_add(100).ok_or("time_overflow")?
            ],
        )?;
    }
    crash(fault, "before-commit", 81);
    tx.commit()?;
    crash(fault, "after-commit", 82);
    if fault == "bad-receipt" {
        let mut bad = receipt.clone();
        bad.request.tenant = "forged".into();
        return Ok(json!({"replayed":false,"receipt":bad}));
    }
    Ok(json!({"replayed":false,"receipt":receipt}))
}
// endregion provider-transaction

// region reconciliation-query
pub fn query(path: &Path, tenant: &str, operation_id: &str, fault: &str) -> Result<Value> {
    let db = open(path)?;
    db.execute("INSERT INTO calls(action) VALUES('query')", [])?;
    crash(fault, "unavailable", 84);
    if fault == "hidden" {
        return Ok(json!({"matches":[],"complete":false}));
    }
    let mut statement = db.prepare(
        "SELECT id,request,digest FROM tickets WHERE tenant=?1 AND operation_id=?2 ORDER BY id",
    )?;
    let rows = statement.query_map(params![tenant, operation_id], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })?;
    let mut matches = Vec::new();
    for row in rows {
        let (ticket_id, request, digest) = row?;
        matches.push(Receipt {
            ticket_id,
            request: serde_json::from_str(&request)?,
            digest,
        });
    }
    Ok(json!({"matches":matches,"complete":true}))
}
// endregion reconciliation-query

pub fn expire(path: &Path, now: i64) -> Result<Value> {
    let db = open(path)?;
    let removed = db.execute("DELETE FROM keys WHERE expires_at<=?1", [now])?;
    Ok(json!({"keys_removed":removed}))
}

pub fn inspect(path: &Path) -> Result<Value> {
    let db = open(path)?;
    let mut statement = db.prepare("SELECT id,request,digest FROM tickets ORDER BY id")?;
    let rows = statement.query_map([], |r| {
        Ok((
            r.get::<_, i64>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })?;
    let mut tickets = Vec::new();
    for row in rows {
        let (ticket_id, request, digest) = row?;
        tickets.push(Receipt {
            ticket_id,
            request: serde_json::from_str(&request)?,
            digest,
        });
    }
    let apply_calls: i64 =
        db.query_row("SELECT count(*) FROM calls WHERE action='apply'", [], |r| {
            r.get(0)
        })?;
    let query_calls: i64 =
        db.query_row("SELECT count(*) FROM calls WHERE action='query'", [], |r| {
            r.get(0)
        })?;
    let keys: i64 = db.query_row("SELECT count(*) FROM keys", [], |r| r.get(0))?;
    Ok(
        json!({"tickets":tickets,"ticket_count":tickets.len(),"committed_apply_calls":apply_calls,"query_calls":query_calls,"keys":keys}),
    )
}
