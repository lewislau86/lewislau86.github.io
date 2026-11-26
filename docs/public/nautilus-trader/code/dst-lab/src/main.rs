//! Chapter 37 experiment: the same async program under real Tokio and under madsim.
//!
//!   cargo run --features sim                          # feature only: still real Tokio
//!   RUSTFLAGS="--cfg madsim" cargo run --features sim # deterministic simulation
//!
//! Each run is a fresh child process, so nothing is shared between runs.

use std::{
    process::Command,
    sync::{Arc, Mutex},
    time::Instant,
};

use ahash::AHashMap;
use nautilus_common::live::dst::{task, time};
use nautilus_core::{UUID4, time::nanos_since_unix_epoch};

// #region scenario
/// Five tasks interleave at yield points; then everyone sleeps 3 s.
async fn scenario() -> String {
    let wall_before = nanos_since_unix_epoch();
    let order = Arc::new(Mutex::new(Vec::new()));
    let mut handles = Vec::new();
    for id in 0..5 {
        let order = order.clone();
        handles.push(task::spawn(async move {
            for step in 0..2 {
                task::yield_now().await;
                order.lock().unwrap().push(format!("{id}{}", ["a", "b"][step]));
            }
        }));
    }
    for h in handles {
        h.await.unwrap();
    }
    time::sleep(time::Duration::from_secs(3)).await;
    let wall_elapsed = (nanos_since_unix_epoch() - wall_before) as f64 / 1e9;

    let map: AHashMap<&str, u8> = ["ETH", "BTC", "SOL", "XRP", "DOGE", "ADA"].into_iter().zip(0..).collect();
    let keys: Vec<&str> = map.keys().copied().collect();
    let uuid = UUID4::new().to_string();
    format!(
        "interleaving {}\n    uuid {}  ahash order {:?}  wall clock advanced {wall_elapsed:.3} s",
        order.lock().unwrap().join(" "),
        &uuid[..8],
        keys
    )
}
// #endregion scenario

// #region runtime
fn run(seed: u64) {
    let real = Instant::now();
    #[cfg(madsim)]
    let out = {
        let rt = madsim::runtime::Runtime::with_seed_and_config(seed, madsim::Config::default());
        rt.block_on(scenario())
    };
    #[cfg(not(madsim))]
    let out = {
        let _ = seed; // no seed in a real runtime
        tokio::runtime::Builder::new_multi_thread().enable_all().build().unwrap().block_on(scenario())
    };
    println!("    {out}\n    real time {:.3} s", real.elapsed().as_secs_f64());
}
// #endregion runtime

fn main() {
    if let Some(seed) = std::env::args().nth(1) {
        run(seed.parse().unwrap());
        return;
    }
    println!(
        "build: feature sim = {}, cfg(madsim) = {}",
        cfg!(feature = "sim"),
        cfg!(madsim)
    );
    for seed in [1, 1, 2] {
        let out = Command::new(std::env::current_exe().unwrap()).arg(seed.to_string()).output().unwrap();
        println!("seed {seed}:");
        print!("{}", String::from_utf8_lossy(&out.stdout));
        let err = String::from_utf8_lossy(&out.stderr);
        if !err.trim().is_empty() {
            println!("    (stderr) {}", err.trim());
        }
    }
}
