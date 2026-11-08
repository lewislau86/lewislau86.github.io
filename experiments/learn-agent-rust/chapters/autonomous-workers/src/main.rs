mod effects;
mod queue;
#[cfg(test)]
mod tests;

use queue::{Command, Error, Fault, Queue, Result};
use serde_json::{Value, json};
use std::path::Path;

// region worker
fn work(db: &Path, command: Command, fault: Fault) -> Result<Value> {
    let Command::Work {
        owner,
        now,
        ttl,
        ledger,
        dedupe,
    } = command
    else {
        return Err(Error("invalid_command"));
    };
    let mut queue = Queue::open(db, false)?;
    let receipt = queue.apply(
        Command::Claim {
            owner: owner.clone(),
            now,
            ttl,
        },
        Fault::None,
    )?;
    if receipt["status"] == "empty" {
        return Ok(receipt);
    }
    let id = receipt["task"]["id"]
        .as_str()
        .ok_or(Error("invalid_receipt"))?;
    let token = receipt["task"]["token"]
        .as_i64()
        .ok_or(Error("invalid_receipt"))?;
    // A local business-service fixture, in a DIFFERENT SQLite database.
    let action = effects::deliver(&ledger, id, token, dedupe)?;
    if fault == Fault::AfterEffect {
        std::process::exit(75);
    }
    let completion = queue.apply(
        Command::Complete {
            id: id.to_owned(),
            owner,
            token,
            now,
            result: "local report delivered".into(),
        },
        Fault::None,
    )?;
    Ok(json!({"status":"worked", "claim":receipt, "action":action, "completion":completion}))
}
// endregion worker

fn run() -> Result<Value> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args == ["versions"] {
        return Ok(json!({"sqlite":rusqlite::version(), "rusqlite":"0.37.0"}));
    }
    if !(2..=3).contains(&args.len()) || args[1].len() > 16384 {
        return Err(Error("usage"));
    }
    let command: Command = serde_json::from_str(&args[1]).map_err(|_| Error("invalid_command"))?;
    let fault = Fault::parse(args.get(2).map(String::as_str))?;
    let db = Path::new(&args[0]);
    match command {
        Command::Work { .. } => {
            if !matches!(fault, Fault::None | Fault::AfterEffect) {
                return Err(Error("invalid_fault"));
            }
            work(db, command, fault)
        }
        Command::Effects {} => {
            if fault != Fault::None {
                return Err(Error("invalid_fault"));
            }
            effects::snapshot(db)
        }
        _ => {
            if fault == Fault::AfterEffect {
                return Err(Error("invalid_fault"));
            }
            let mut queue = Queue::open(db, matches!(command, Command::Init {}))?;
            queue.apply(command, fault)
        }
    }
}

fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            println!("{}", json!({"status":"error", "error":error.0}));
            std::process::exit(1);
        }
    }
}
