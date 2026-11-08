use postgres::{Client, NoTls};
use serde_json::{Value, json};
use std::io::{self, BufRead, Write};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn fail<T>(reason: &str) -> Result<T> {
    Err(reason.into())
}
fn field<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("Missing:{key}").into())
}
fn number(v: &Value, key: &str) -> Result<i64> {
    v[key]
        .as_i64()
        .ok_or_else(|| format!("Missing:{key}").into())
}

// region authority
struct Actor {
    tenant: &'static str,
    approver: bool,
}
// Fixed credentials stand in for a trusted authentication adapter, not a model field.
fn authenticate(credential: &str) -> Result<Actor> {
    match credential {
        "fixture-reader-a" => Ok(Actor {
            tenant: "a",
            approver: false,
        }),
        "fixture-approver-a" => Ok(Actor {
            tenant: "a",
            approver: true,
        }),
        "fixture-approver-b" => Ok(Actor {
            tenant: "b",
            approver: true,
        }),
        _ => fail("Unauthenticated"),
    }
}
fn authorize(actor: &Actor, tenant: &str, approval: bool) -> Result<()> {
    if actor.tenant != tenant {
        return fail("TenantDenied");
    }
    if approval && !actor.approver {
        return fail("RoleDenied");
    }
    Ok(())
}
fn approve(db: &mut Client, v: &Value) -> Result<Value> {
    let actor = authenticate(field(v, "credential")?)?;
    let tenant = field(v, "tenant")?;
    authorize(&actor, tenant, true)?;
    let n = db.execute(
        "UPDATE approvals SET approved=true WHERE tenant=$1 AND id=$2
         AND revision=$3 AND NOT approved",
        &[&tenant, &field(v, "id")?, &number(v, "revision")?],
    )?;
    if n != 1 {
        return fail("ApprovalConflict");
    }
    Ok(json!({"approved": true}))
}
// endregion authority

// region migration
fn migrate(db: &mut Client, injected_failure: bool) -> Result<Value> {
    let mut tx = db.transaction()?;
    let version: i32 = tx
        .query_one("SELECT schema FROM settings FOR UPDATE", &[])?
        .get(0);
    if version == 2 {
        return Ok(json!({"schema": 2, "replayed": true}));
    }
    if version != 1 {
        return fail("UnknownSchema");
    }
    let invalid: i64 = tx
        .query_one(
            "SELECT count(*) FROM sessions WHERE version != 1 OR jsonb_typeof(payload) != 'object'
         OR NOT (payload ? 'next' AND payload ? 'spent')",
            &[],
        )?
        .get(0);
    if invalid != 0 {
        return fail("UnmigratableSession");
    }
    tx.batch_execute(
        "ALTER TABLE sessions ADD COLUMN workflow text;
         UPDATE sessions SET version=2, workflow='review-v2',
           payload=payload || '{\"status\":\"paused\"}'::jsonb;
         UPDATE settings SET schema=2;",
    )?;
    if injected_failure {
        return fail("MigrationInjected");
    } // Drop rolls back DDL and data.
    tx.commit()?;
    Ok(json!({"schema": 2, "replayed": false}))
}
fn read_session(db: &mut Client, v: &Value) -> Result<Value> {
    let actor = authenticate(field(v, "credential")?)?;
    let tenant = field(v, "tenant")?;
    authorize(&actor, tenant, false)?;
    let row = db
        .query_opt(
            "SELECT version,payload FROM sessions WHERE tenant=$1 AND id=$2",
            &[&tenant, &field(v, "id")?],
        )?
        .ok_or("NotFound")?;
    let version: i32 = row.get(0);
    let reader = number(v, "reader")?;
    if !matches!((reader, version), (1, 1) | (2, 1) | (2, 2)) {
        return fail("IncompatibleSnapshot");
    }
    Ok(json!({"version": version, "payload": row.get::<_, Value>(1)}))
}
// endregion migration

// region admission
fn admit(db: &mut Client, id: &str) -> Result<Value> {
    let mut tx = db.transaction()?;
    let row = tx.query_one(
        "SELECT active,capacity,draining,approved,recovery,schema,release
        FROM settings FOR UPDATE",
        &[],
    )?;
    if row.get::<_, bool>(2)
        || !row.get::<_, bool>(3)
        || row.get::<_, bool>(4)
        || row.get::<_, i32>(5) != 2
        || row.get::<_, String>(6) != "p04-v2"
    {
        return fail("NotReady");
    }
    if tx
        .query_opt("SELECT id FROM jobs WHERE id=$1", &[&id])?
        .is_some()
    {
        return fail("DuplicateRequest");
    }
    if row.get::<_, i32>(0) >= row.get::<_, i32>(1) {
        tx.execute("UPDATE settings SET rejected=rejected+1", &[])?;
        tx.commit()?; // Preserve rejection evidence, even though the request is rejected.
        return fail("Overloaded");
    }
    tx.execute("INSERT INTO jobs VALUES($1,'running')", &[&id])?;
    tx.execute(
        "UPDATE settings SET active=active+1,admitted=admitted+1",
        &[],
    )?;
    tx.commit()?;
    Ok(json!({"admitted": true}))
}
fn finish(db: &mut Client, id: &str) -> Result<Value> {
    let mut tx = db.transaction()?;
    tx.query_one("SELECT active FROM settings FOR UPDATE", &[])?;
    let changed = tx.execute(
        "UPDATE jobs SET state='done' WHERE id=$1 AND state='running'",
        &[&id],
    )?;
    if changed != 1 {
        return fail("AlreadyFinishedOrMissing");
    }
    tx.execute(
        "UPDATE settings SET active=active-1,finished=finished+1",
        &[],
    )?;
    tx.commit()?;
    Ok(json!({"finished": true}))
}
// endregion admission

// region fencing
fn claim(db: &mut Client, owner: &str) -> Result<Value> {
    let row = db.query_opt(
        "UPDATE lease SET owner=$1,epoch=epoch+1,
        deadline=clock_timestamp()+interval '2 seconds'
        WHERE id=1 AND (owner IS NULL OR deadline <= clock_timestamp()) RETURNING epoch",
        &[&owner],
    )?;
    match row {
        Some(row) => Ok(json!({"epoch": row.get::<_, i64>(0)})),
        None => fail("LeaseBusy"),
    }
}
fn commit_result(db: &mut Client, owner: &str, epoch: i64) -> Result<Value> {
    let mut tx = db.transaction()?;
    let row = tx.query_one(
        "SELECT owner,epoch,deadline>clock_timestamp() FROM lease WHERE id=1 FOR UPDATE",
        &[],
    )?;
    if row.get::<_, Option<String>>(0).as_deref() != Some(owner)
        || row.get::<_, i64>(1) != epoch
        || !row.get::<_, bool>(2)
    {
        return fail("Fenced");
    }
    // This is a local database result ledger, NOT a remote payment service.
    tx.execute(
        "INSERT INTO results VALUES('review', $1, $2)",
        &[&owner, &epoch],
    )?;
    tx.execute("UPDATE lease SET owner=NULL, deadline=NULL WHERE id=1", &[])?;
    tx.commit()?;
    Ok(json!({"committed": true, "epoch": epoch}))
}
// endregion fencing

// region health
fn health(db: &mut Client) -> Result<Value> {
    let row = db.query_one(
        "SELECT schema,release,draining,approved,recovery,active,capacity,
        admitted,rejected,finished FROM settings",
        &[],
    )?;
    let ready = row.get::<_, i32>(0) == 2
        && row.get::<_, String>(1) == "p04-v2"
        && !row.get::<_, bool>(2)
        && row.get::<_, bool>(3)
        && !row.get::<_, bool>(4);
    Ok(
        json!({"live":true,"ready":ready,"active":row.get::<_, i32>(5),
        "capacity":row.get::<_, i32>(6),"admitted":row.get::<_, i64>(7),
        "rejected":row.get::<_, i64>(8),"finished":row.get::<_, i64>(9)}),
    )
}
// endregion health

fn run(v: &Value) -> Result<Value> {
    let op = field(v, "op")?;
    let connection = Client::connect(&std::env::var("P04_DATABASE_URL")?, NoTls);
    let mut db = match connection {
        Ok(db) => db,
        Err(_) if op == "health" => {
            return Ok(json!({"live":true,"ready":false,"reason":"DatabaseUnavailable"}));
        }
        Err(e) => return Err(e.into()),
    };
    match op {
        "init" => {
            db.batch_execute(include_str!("schema.sql"))?;
            Ok(json!({"schema":1}))
        }
        "read" => read_session(&mut db, v),
        "approve" => approve(&mut db, v),
        "migrate" => migrate(&mut db, v["fail"].as_bool().unwrap_or(false)),
        "health" => health(&mut db)
            .or_else(|_| Ok(json!({"live":true,"ready":false,"reason":"SchemaUnavailable"}))),
        "admit" => admit(&mut db, field(v, "id")?),
        "finish" => finish(&mut db, field(v, "id")?),
        "claim" => claim(&mut db, field(v, "owner")?),
        "commit" => commit_result(&mut db, field(v, "owner")?, number(v, "epoch")?),
        "worker" => {
            let owner = field(v, "owner")?;
            let claimed = claim(&mut db, owner)?;
            println!("{}", json!({"claimed":claimed["epoch"]}));
            io::stdout().flush()?;
            let mut input = String::new();
            io::stdin().lock().read_line(&mut input)?;
            if input.trim() != "commit" {
                return fail("Cancelled");
            }
            commit_result(
                &mut db,
                owner,
                claimed["epoch"].as_i64().ok_or("MissingEpoch")?,
            )
        }
        _ => fail("UnknownCommand"),
    }
}
fn main() {
    let result = std::env::args()
        .nth(1)
        .ok_or_else(|| "MissingCommand".into())
        .and_then(|s| serde_json::from_str::<Value>(&s).map_err(Into::into))
        .and_then(|v| run(&v));
    match result {
        Ok(v) => println!("{v}"),
        Err(e) => {
            println!("{}", json!({"error": e.to_string()}));
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn credentials_do_not_accept_model_role_text() {
        assert!(authenticate("admin").is_err());
        assert!(authenticate("").is_err());
    }
    #[test]
    fn reader_cannot_approve() {
        assert!(authorize(&authenticate("fixture-reader-a").unwrap(), "a", true).is_err());
    }
    #[test]
    fn approver_cannot_cross_tenants() {
        assert!(authorize(&authenticate("fixture-approver-b").unwrap(), "a", true).is_err());
    }
    #[test]
    fn valid_reader_can_read_own_tenant() {
        assert!(authorize(&authenticate("fixture-reader-a").unwrap(), "a", false).is_ok());
    }
}
