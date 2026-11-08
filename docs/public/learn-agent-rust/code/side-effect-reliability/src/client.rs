use crate::{Receipt, Request, Result, checked, crash, database, invoke};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::path::Path;

fn open(path: &Path) -> Result<rusqlite::Connection> {
    let db = database(path)?;
    db.execute_batch("
        CREATE TABLE IF NOT EXISTS actions(tenant TEXT, operation_id TEXT, state TEXT NOT NULL,
            PRIMARY KEY(tenant,operation_id));
        CREATE TABLE IF NOT EXISTS outbox(tenant TEXT, operation_id TEXT, request TEXT NOT NULL,
            digest TEXT NOT NULL, mode TEXT NOT NULL, safe_until INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL, last_tick INTEGER NOT NULL,
            receipt TEXT, PRIMARY KEY(tenant,operation_id));
        CREATE TABLE IF NOT EXISTS checkpoints(tenant TEXT, operation_id TEXT, receipt TEXT NOT NULL,
            PRIMARY KEY(tenant,operation_id));
    ")?;
    Ok(db)
}

// region outbox-prepare
pub fn prepare(path: &Path, request: Request, mode: &str, now: i64, fault: &str) -> Result<Value> {
    request.validate()?;
    if !matches!(mode, "key" | "none") || now < 0 {
        return Err("invalid_prepare_argument".into());
    }
    let mut db = open(path)?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let saved: Option<(String, String)> = tx
        .query_row(
            "SELECT digest,mode FROM outbox WHERE tenant=?1 AND operation_id=?2",
            params![request.tenant, request.operation_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()?;
    if let Some((digest, original_mode)) = saved {
        if digest != request.digest() || original_mode != mode {
            return Err("local_intent_conflict".into());
        }
        return Ok(json!({"prepared":false,"reason":"existing_intent"}));
    }
    tx.execute(
        "INSERT INTO actions VALUES(?1,?2,'queued')",
        params![request.tenant, request.operation_id],
    )?;
    crash(fault, "between-local-writes", 80);
    tx.execute(
        "INSERT INTO outbox VALUES(?1,?2,?3,?4,?5,?6,'pending',0,?7,NULL)",
        params![
            request.tenant,
            request.operation_id,
            serde_json::to_string(&request)?,
            request.digest(),
            mode,
            now.checked_add(100).ok_or("time_overflow")?,
            now
        ],
    )?;
    crash(fault, "before-prepare-commit", 81);
    tx.commit()?;
    crash(fault, "after-prepare-commit", 82);
    Ok(json!({"prepared":true,"operation_id":request.operation_id,"digest":request.digest()}))
}
// endregion outbox-prepare

struct Intent {
    request: Request,
    mode: String,
    safe_until: i64,
    state: String,
    attempts: i64,
    last_tick: i64,
    receipt: Option<String>,
}

fn load(db: &rusqlite::Connection, tenant: &str, id: &str) -> Result<Intent> {
    let row: (String,String,String,i64,String,i64,i64,Option<String>) = db.query_row(
        "SELECT request,digest,mode,safe_until,state,attempts,last_tick,receipt FROM outbox WHERE tenant=?1 AND operation_id=?2",
        params![tenant,id], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?,r.get(6)?,r.get(7)?)))?;
    let request: Request = serde_json::from_str(&row.0)?;
    request.validate()?;
    if request.tenant != tenant || request.operation_id != id || request.digest() != row.1 {
        return Err("corrupt_intent".into());
    }
    if !matches!(row.2.as_str(), "key" | "none") {
        return Err("corrupt_mode".into());
    }
    Ok(Intent {
        request,
        mode: row.2,
        safe_until: row.3,
        state: row.4,
        attempts: row.5,
        last_tick: row.6,
        receipt: row.7,
    })
}

fn acknowledge(db: &rusqlite::Connection, request: &Request, receipt: &Receipt) -> Result<()> {
    receipt.verify(request)?;
    let changed = db.execute("UPDATE outbox SET state='acked',receipt=?3 WHERE tenant=?1 AND operation_id=?2 AND state IN ('unknown','acked')",
        params![request.tenant,request.operation_id,serde_json::to_string(receipt)?])?;
    if changed != 1 {
        return Err("ack_state_conflict".into());
    }
    Ok(())
}

// region checkpoint
fn checkpoint(
    db: &mut rusqlite::Connection,
    request: &Request,
    receipt: &Receipt,
    fault: &str,
) -> Result<Value> {
    receipt.verify(request)?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let state: String = tx.query_row(
        "SELECT state FROM outbox WHERE tenant=?1 AND operation_id=?2",
        params![request.tenant, request.operation_id],
        |r| r.get(0),
    )?;
    if !matches!(state.as_str(), "acked" | "completed") {
        return Err("checkpoint_requires_receipt".into());
    }
    tx.execute("INSERT INTO checkpoints VALUES(?1,?2,?3) ON CONFLICT(tenant,operation_id) DO UPDATE SET receipt=excluded.receipt",
        params![request.tenant,request.operation_id,serde_json::to_string(receipt)?])?;
    tx.execute(
        "UPDATE actions SET state='completed' WHERE tenant=?1 AND operation_id=?2",
        params![request.tenant, request.operation_id],
    )?;
    tx.execute(
        "UPDATE outbox SET state='completed' WHERE tenant=?1 AND operation_id=?2",
        params![request.tenant, request.operation_id],
    )?;
    crash(fault, "before-checkpoint-commit", 85);
    tx.commit()?;
    crash(fault, "after-checkpoint-commit", 86);
    Ok(json!({"state":"completed","receipt":receipt}))
}
// endregion checkpoint

#[allow(clippy::too_many_arguments)]
pub fn deliver(
    local: &Path,
    remote: &Path,
    tenant: &str,
    id: &str,
    now: i64,
    fault: &str,
    reconcile: bool,
) -> Result<Value> {
    let mut db = open(local)?;
    let intent = load(&db, tenant, id)?;
    if now < intent.last_tick {
        return Err("clock_regression".into());
    }
    if matches!(intent.state.as_str(), "acked" | "completed") {
        let receipt: Receipt =
            serde_json::from_str(intent.receipt.as_deref().ok_or("missing_receipt")?)?;
        return checkpoint(&mut db, &intent.request, &receipt, fault);
    }
    if reconcile && intent.state == "unknown" {
        let query_fault = match fault {
            "query-hidden" => "hidden",
            "query-unavailable" => "unavailable",
            _ => "none",
        };
        let output = invoke(&[
            "query".into(),
            remote.to_string_lossy().into(),
            tenant.into(),
            id.into(),
            query_fault.into(),
        ])?;
        let result = checked(output).map_err(|_| "reconciliation_unavailable")?;
        if result["complete"] != true {
            return Err("reconciliation_incomplete".into());
        }
        let matches: Vec<Receipt> = serde_json::from_value(result["matches"].clone())?;
        if matches.len() > 1 {
            return Err("reconciliation_ambiguous".into());
        }
        if let Some(receipt) = matches.first() {
            receipt.verify(&intent.request)?;
            acknowledge(&db, &intent.request, receipt)?;
            return checkpoint(&mut db, &intent.request, receipt, fault);
        }
        // Even an empty authoritative lookup is not permission to resend a
        // non-idempotent operation: an earlier request might still be in flight.
    }
    send(&mut db, remote, tenant, id, now, fault)
}

// region dispatch
fn send(
    db: &mut rusqlite::Connection,
    remote: &Path,
    tenant: &str,
    id: &str,
    now: i64,
    fault: &str,
) -> Result<Value> {
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let intent = load(&tx, tenant, id)?;
    if now < intent.last_tick {
        return Err("clock_regression".into());
    }
    if !matches!(intent.state.as_str(), "pending" | "unknown") {
        return Err("dispatch_state_conflict".into());
    }
    if intent.state == "unknown" && intent.mode == "none" {
        return Err("manual_reconciliation_required".into());
    }
    if now >= intent.safe_until {
        return Err("retry_window_expired".into());
    }
    if intent.attempts >= 3 {
        return Err("attempt_budget".into());
    }
    tx.execute("UPDATE outbox SET state='unknown',attempts=attempts+1,last_tick=?3 WHERE tenant=?1 AND operation_id=?2", params![tenant,id,now])?;
    tx.commit()?;
    crash(fault, "before-send", 83);
    let provider_fault = match fault {
        "provider-before-commit" => "before-commit",
        "provider-after-commit" => "after-commit",
        "bad-receipt" => "bad-receipt",
        _ => "none",
    };
    let output = invoke(&[
        "apply".into(),
        remote.to_string_lossy().into(),
        serde_json::to_string(&intent.request)?,
        intent.mode,
        now.to_string(),
        provider_fault.into(),
    ])?;
    let result = checked(output).map_err(|_| "outcome_unknown")?;
    crash(fault, "after-response", 84);
    let receipt: Receipt = serde_json::from_value(result["receipt"].clone())?;
    acknowledge(db, &intent.request, &receipt)?;
    crash(fault, "after-ack", 87);
    checkpoint(db, &intent.request, &receipt, fault)
}
// endregion dispatch

pub fn inspect(path: &Path) -> Result<Value> {
    let db = open(path)?;
    let mut statement = db.prepare("SELECT tenant,operation_id,state,attempts,receipt FROM outbox ORDER BY tenant,operation_id")?;
    let rows = statement.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, i64>(3)?,
            r.get::<_, Option<String>>(4)?,
        ))
    })?;
    let mut outbox = Vec::new();
    for row in rows {
        let (tenant, operation_id, state, attempts, receipt) = row?;
        outbox.push(
            json!({"tenant":tenant,"operation_id":operation_id,"state":state,"attempts":attempts,
            "receipt":receipt.map(|r|serde_json::from_str::<Receipt>(&r)).transpose()?}),
        );
    }
    let actions: i64 = db.query_row("SELECT count(*) FROM actions", [], |r| r.get(0))?;
    let checkpoints: i64 = db.query_row("SELECT count(*) FROM checkpoints", [], |r| r.get(0))?;
    let completed_actions: i64 = db.query_row(
        "SELECT count(*) FROM actions WHERE state='completed'",
        [],
        |r| r.get(0),
    )?;
    Ok(
        json!({"outbox":outbox,"actions":actions,"completed_actions":completed_actions,"checkpoints":checkpoints}),
    )
}
