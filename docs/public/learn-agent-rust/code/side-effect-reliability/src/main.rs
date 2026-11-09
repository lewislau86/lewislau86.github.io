mod client;
mod provider;
#[cfg(test)]
mod tests;

use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::path::Path;
use std::process::{Command, Output};
use std::time::Duration;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

// region identity
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub tenant: String,
    pub operation_id: String,
    pub title: String,
}

impl Request {
    fn validate(&self) -> Result<()> {
        for identity in [&self.tenant, &self.operation_id] {
            if identity.is_empty()
                || identity.len() > 64
                || !identity
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"-_".contains(&b))
            {
                return Err("invalid_identity".into());
            }
        }
        if self.title.trim().is_empty() || self.title.len() > 256 {
            return Err("invalid_title".into());
        }
        Ok(())
    }

    fn digest(&self) -> String {
        format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(self).expect("request JSON"))
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Receipt {
    pub ticket_id: i64,
    pub request: Request,
    pub digest: String,
}

impl Receipt {
    fn verify(&self, request: &Request) -> Result<()> {
        if self.ticket_id <= 0 || self.request != *request || self.digest != request.digest() {
            return Err("receipt_mismatch".into());
        }
        Ok(())
    }
}
// endregion identity

fn database(path: &Path) -> Result<Connection> {
    let db = Connection::open(path)?;
    db.busy_timeout(Duration::from_secs(5))?;
    db.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;")?;
    Ok(db)
}

fn crash(fault: &str, point: &str, code: i32) {
    if fault == point {
        eprintln!("injected_exit={point}");
        // No Rust unwinding: committed and uncommitted states are inspected by another process.
        std::process::exit(code);
    }
}

fn invoke(args: &[String]) -> Result<Output> {
    Ok(Command::new(std::env::current_exe()?).args(args).output()?)
}

fn checked(output: Output) -> Result<Value> {
    if !output.status.success() {
        return Err(format!("child_failed:{}", output.status.code().unwrap_or(-1)).into());
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}

fn demo() -> Result<Value> {
    let temp = tempfile::tempdir()?;
    let local = temp
        .path()
        .join("client.sqlite")
        .to_string_lossy()
        .to_string();
    let remote = temp
        .path()
        .join("provider.sqlite")
        .to_string_lossy()
        .to_string();
    let request = Request {
        tenant: "course".into(),
        operation_id: "review-42".into(),
        title: "Review Rust timeout handling".into(),
    };
    let payload = serde_json::to_string(&request)?;
    checked(invoke(&[
        "prepare".into(),
        local.clone(),
        payload,
        "key".into(),
        "0".into(),
        "none".into(),
    ])?)?;
    let lost = invoke(&[
        "dispatch".into(),
        local.clone(),
        remote.clone(),
        "course".into(),
        "review-42".into(),
        "1".into(),
        "provider-after-commit".into(),
    ])?;
    if lost.status.code() != Some(10) {
        return Err("expected unknown provider result".into());
    }
    let before = checked(invoke(&["inspect-client".into(), local.clone()])?)?;
    let recovery = checked(invoke(&[
        "recover".into(),
        local.clone(),
        remote.clone(),
        "course".into(),
        "review-42".into(),
        "2".into(),
        "none".into(),
    ])?)?;
    let provider = checked(invoke(&["inspect-provider".into(), remote])?)?;
    let after = checked(invoke(&["inspect-client".into(), local])?)?;
    let original = temp.path().to_owned();
    temp.close()?;
    Ok(
        json!({"scenario":"demo", "before_recovery":before, "recovery":recovery,
        "provider":provider, "after_recovery":after, "workspace_removed":!original.exists()}),
    )
}

fn execute(args: &[String]) -> Result<Value> {
    let get = |i: usize| -> Result<&str> {
        args.get(i)
            .map(String::as_str)
            .ok_or_else(|| "missing_argument".into())
    };
    match get(0)? {
        "prepare" if args.len() == 6 => client::prepare(Path::new(get(1)?), serde_json::from_str(get(2)?)?, get(3)?, get(4)?.parse()?, get(5)?),
        "dispatch" | "recover" if args.len() == 7 => client::deliver(Path::new(get(1)?), Path::new(get(2)?), get(3)?, get(4)?, get(5)?.parse()?, get(6)?, get(0)? == "recover"),
        "apply" if args.len() == 6 => provider::apply(Path::new(get(1)?), serde_json::from_str(get(2)?)?, get(3)?, get(4)?.parse()?, get(5)?),
        "query" if args.len() == 5 => provider::query(Path::new(get(1)?), get(2)?, get(3)?, get(4)?),
        "expire" if args.len() == 3 => provider::expire(Path::new(get(1)?), get(2)?.parse()?),
        "inspect-client" if args.len() == 2 => client::inspect(Path::new(get(1)?)),
        "inspect-provider" if args.len() == 2 => provider::inspect(Path::new(get(1)?)),
        _ => Err("usage: [prepare|dispatch|recover|apply|query|expire|inspect-client|inspect-provider]; see README".into()),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = if args.is_empty() {
        demo()
    } else {
        execute(&args)
    };
    match result {
        Ok(value) => println!("{}", serde_json::to_string_pretty(&value).unwrap()),
        Err(error) => {
            println!("{}", json!({"error":error.to_string()}));
            std::process::exit(10);
        }
    }
}
