mod controller;
mod fixture;
mod goal;
#[cfg(test)]
mod tests;

use std::{env, fs, path::Path};

fn main() {
    let args: Vec<_> = env::args().collect();
    let result = (|| {
        if args.len() != 3 {
            return Err("usage: learn-agent-p05 SCENARIO NEW_WORKSPACE".to_string());
        }
        let fixture = fixture::Fixture::new(&args[1]).ok_or("unknown_scenario")?;
        let root = Path::new(&args[2]);
        // Refuse reuse: each run owns a newly created directory, never an existing workspace.
        fs::create_dir(root).map_err(|_| "workspace_must_be_new")?;
        fixture
            .prepare(root)
            .map_err(|_| "fixture_prepare_failed")?;
        let report = controller::run(root, fixture);
        fs::write(
            root.join("result.json"),
            serde_json::to_vec_pretty(&report).unwrap(),
        )
        .map_err(|_| "result_save_failed")?;
        Ok(report)
    })();
    match result {
        Ok(value) => println!("{}", serde_json::to_string(&value).unwrap()),
        Err(error) => {
            println!("{}", serde_json::json!({"error": error}));
            std::process::exit(2);
        }
    }
}
