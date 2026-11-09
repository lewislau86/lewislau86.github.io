mod scheduler;

use chrono::{Timelike, Utc};
use scheduler::{Result, time};
use serde_json::json;
use std::path::Path;

// region cli
fn execute(args: &[String]) -> Result<serde_json::Value> {
    match args.first().map(String::as_str) {
        Some("versions") if args.len() == 1 => {
            Ok(json!({"status":"versions","sqlite":rusqlite::version(),
            "tzdb":chrono_tz::IANA_TZDB_VERSION}))
        }
        Some("init") if args.len() == 2 => scheduler::init(Path::new(&args[1])),
        Some("add") if args.len() == 8 && args[6] == "--start" => {
            // Validate timestamp before opening the database; all config stays immutable.
            time(&args[7])?;
            scheduler::add(
                &mut scheduler::open(Path::new(&args[1]))?,
                &args[2],
                &args[3],
                &args[4],
                &args[5],
                &args[7],
            )
        }
        Some("tick")
            if args.len() == 3
                || (args.len() == 4
                    && matches!(
                        args[3].as_str(),
                        "--fail-after-insert" | "--exit-after-insert" | "--exit-after-commit"
                    )) =>
        {
            time(&args[2])?;
            scheduler::tick(
                &mut scheduler::open(Path::new(&args[1]))?,
                &args[2],
                args.get(3).map_or("", String::as_str),
            )
        }
        Some("tick-now") if args.len() == 2 => {
            let now = Utc::now()
                .with_nanosecond(0)
                .ok_or("clock_error")?
                .to_rfc3339();
            scheduler::tick(&mut scheduler::open(Path::new(&args[1]))?, &now, "")
        }
        Some("run") if args.len() == 3 => {
            let count: u32 = args[2].parse().map_err(|_| "invalid_ticks")?;
            if !(1..=60).contains(&count) {
                return Err("invalid_ticks");
            }
            let mut db = scheduler::open(Path::new(&args[1]))?;
            for index in 0..count {
                let now = Utc::now()
                    .with_nanosecond(0)
                    .ok_or("clock_error")?
                    .to_rfc3339();
                scheduler::tick(&mut db, &now, "")?;
                if index + 1 < count {
                    std::thread::sleep(std::time::Duration::from_secs(1));
                }
            }
            Ok(json!({"status":"polling_stopped","ticks":count}))
        }
        Some("show") if args.len() == 2 => scheduler::show(&scheduler::open(Path::new(&args[1]))?),
        Some("resolve") if args.len() == 4 => scheduler::resolve(&args[1], &args[2], &args[3]),
        _ => Err("usage"),
    }
}
// endregion cli

fn main() {
    match execute(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(value) => println!("{}", value),
        Err(error) => {
            println!("{}", json!({"status":"error","error":error}));
            std::process::exit(1);
        }
    }
}
