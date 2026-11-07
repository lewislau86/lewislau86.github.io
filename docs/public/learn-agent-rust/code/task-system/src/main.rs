mod storage;
mod tasks;

use serde_json::{Value, json};
use std::path::Path;
use storage::{Fault, Storage, view};
use tasks::{Error, Result, Update};

fn execute(args: &[String]) -> Result<Value> {
    if args.len() < 2 {
        return Err(Error::before("usage"));
    }
    let directory = Path::new(&args[0]);
    let command = args[1].as_str();
    let initialize = command == "init" && args.len() == 2;
    let storage = Storage::open(directory, initialize)?;
    match command {
        "init" if args.len() == 2 => storage.initialize(),
        "show" if args.len() == 2 => Ok(view(&storage.load()?)),
        "apply" if args.len() == 4 || args.len() == 5 => {
            let expected = args[2]
                .parse::<u64>()
                .map_err(|_| Error::before("invalid_revision"))?;
            if args[3].len() > 4096 {
                return Err(Error::before("request_limit"));
            }
            let update: Update =
                serde_json::from_str(&args[3]).map_err(|_| Error::before("invalid_request"))?;
            let fault = match args.get(4).map(String::as_str) {
                None => Fault::None,
                Some("--fail-before-rename") => Fault::BeforeRename,
                Some("--fail-after-rename") => Fault::AfterRename,
                Some("--pause-before-rename") => Fault::PauseBeforeRename,
                Some("--pause-after-commit") => Fault::PauseAfterCommit,
                _ => return Err(Error::before("usage")),
            };
            storage.apply(expected, update, fault)
        }
        _ => Err(Error::before("usage")),
    }
}

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    match execute(&args) {
        Ok(value) => println!("{value}"),
        Err(error) => {
            println!(
                "{}",
                json!({"status":"error","error":error.code,"committed":error.committed})
            );
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests;
