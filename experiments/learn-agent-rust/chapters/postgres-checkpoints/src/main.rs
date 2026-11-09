mod driver;
mod state;
mod store;
#[cfg(test)]
mod tests;

use serde::Deserialize;
use serde_json::{Value, json};
use state::{Error, Granularity, Result, State};
use std::path::PathBuf;
use store::{Fault, Store};

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Command {
    Init {},
    Versions {},
    Create {
        id: String,
        profile: String,
        granularity: Granularity,
    },
    Show {
        id: String,
    },
    History {
        id: String,
    },
    Save {
        id: String,
        expected: i64,
        save_id: String,
        state: State,
    },
    Step {
        id: String,
        expected: i64,
        workspace: PathBuf,
    },
}
fn run() -> Result<Value> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if !(1..=2).contains(&args.len()) || args[0].len() > 32768 {
        return Err(Error("usage"));
    }
    let command: Command = serde_json::from_str(&args[0]).map_err(|_| Error("invalid_command"))?;
    let fault = Fault::parse(args.get(1).map(String::as_str))?;
    if !matches!(command, Command::Save { .. } | Command::Step { .. }) && fault != Fault::None {
        return Err(Error("invalid_fault"));
    }
    let mut store = Store::connect()?;
    match command {
        Command::Init {} => store.initialize(),
        Command::Versions {} => {
            let row=store.client.query_one("SELECT current_setting('server_version_num'),current_setting('fsync'),current_setting('synchronous_commit'),current_setting('full_page_writes')",&[])?;
            Ok(
                json!({"status":"versions","postgres_driver":"0.19.12","server_version_num":row.get::<_,String>(0),"fsync":row.get::<_,String>(1),"synchronous_commit":row.get::<_,String>(2),"full_page_writes":row.get::<_,String>(3)}),
            )
        }
        Command::Create {
            id,
            profile,
            granularity,
        } => store.create(&id, State::new(profile, granularity)?),
        Command::Show { id } => store.snapshot(&id),
        Command::History { id } => store.history(&id),
        Command::Save {
            id,
            expected,
            save_id,
            state,
        } => store.save(&id, expected, &save_id, &state, fault),
        Command::Step {
            id,
            expected,
            workspace,
        } => driver::step(&mut store, &id, &workspace, expected, fault),
    }
}
fn main() {
    match run() {
        Ok(value) => println!("{value}"),
        Err(error) => {
            println!("{}", json!({"status":"error","error":error.0}));
            std::process::exit(1);
        }
    }
}
