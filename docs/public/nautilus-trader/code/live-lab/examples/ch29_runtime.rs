//! Chapter 29 experiments: the global Tokio runtime.
//!
//! Each scenario runs in its own child process, because the global runtime can
//! only be created once per process.
//!
//! Run: cargo run --example ch29_runtime

use std::{process::Command, time::Duration};

use live_lab::{catch_panic, thread_summary};
use nautilus_common::live::{block_on_nautilus, block_on_nautilus_with, get_runtime, set_runtime};

// #region lazy
fn lazy() {
    println!("before get_runtime: {}", thread_summary());
    let rt = get_runtime();
    std::thread::sleep(Duration::from_millis(50)); // let the workers start and name themselves
    println!(
        "after  get_runtime: {} (num_workers = {})",
        thread_summary(),
        rt.metrics().num_workers()
    );
}
// #endregion lazy

// #region inject
fn inject() {
    let single = tokio::runtime::Builder::new_current_thread().build().unwrap();
    println!("set_runtime(current_thread) -> {}", ok(set_runtime(single).is_ok()));

    let multi = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(3)
        .enable_all()
        .build()
        .unwrap();
    println!("set_runtime(multi_thread, 3 workers) -> {}", ok(set_runtime(multi).is_ok()));
    println!("get_runtime().num_workers = {}", get_runtime().metrics().num_workers());

    let again = tokio::runtime::Builder::new_multi_thread().build().unwrap();
    println!("set_runtime again -> {}", ok(set_runtime(again).is_ok()));
}

fn late_inject() {
    let _ = get_runtime(); // the global runtime now exists
    let multi = tokio::runtime::Builder::new_multi_thread().build().unwrap();
    println!("get_runtime() first, then set_runtime -> {}", ok(set_runtime(multi).is_ok()));
}
// #endregion inject

// #region bridge
fn bridge() {
    // 1. Plain thread, no runtime context.
    println!("[main thread] block_on_nautilus -> {}", block_on_nautilus(async { 1 }));
    let r = catch_panic(|| tokio::spawn(async {}));
    println!("[main thread] tokio::spawn -> panic: {}", r.err().unwrap_or_default());
    let h = get_runtime().spawn(async { 2 });
    println!("[main thread] get_runtime().spawn -> {}", get_runtime().block_on(h).unwrap());

    // 2. Inside a task on a Nautilus worker thread.
    let out = get_runtime().block_on(get_runtime().spawn(async {
        let direct = catch_panic(|| get_runtime().block_on(async { 3 }));
        let bridged = block_on_nautilus(async { 3 });
        (direct.err().unwrap_or_default(), bridged)
    }));
    let (direct, bridged) = out.unwrap();
    println!("[nautilus worker] get_runtime().block_on -> panic: {direct}");
    println!("[nautilus worker] block_on_nautilus -> {bridged}");

    // 3. Inside some other current-thread runtime.
    let other = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
    other.block_on(async {
        let r = catch_panic(|| block_on_nautilus(async { 4 }));
        println!("[other current_thread rt] block_on_nautilus -> panic: {}", r.err().unwrap_or_default());
        let v = block_on_nautilus_with(|| async { 4 });
        println!("[other current_thread rt] block_on_nautilus_with -> {v}");
    });
}
// #endregion bridge

// #region two-runtimes
fn two_runtimes() {
    // What `#[tokio::main]` does: build a runtime and drive `main` on it.
    let main_rt = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .thread_name("main-rt-worker")
        .enable_all()
        .build()
        .unwrap();
    main_rt.block_on(async {
        let _ = get_runtime(); // an adapter touches the global runtime
        tokio::time::sleep(Duration::from_millis(50)).await;
        println!("threads: {}", thread_summary());
    });
}
// #endregion two-runtimes

fn ok(b: bool) -> &'static str {
    if b { "Ok" } else { "Err (runtime handed back)" }
}

fn run_child(scenario: &str, env: &[(&str, &str)]) {
    let exe = std::env::current_exe().unwrap();
    let mut cmd = Command::new(exe);
    cmd.arg(scenario).env_remove("NAUTILUS_WORKER_THREADS");
    for (k, v) in env {
        cmd.env(k, v);
    }
    let out = cmd.output().unwrap();
    let label = env.iter().map(|(k, v)| format!("{k}={v} ")).collect::<String>();
    println!("== {scenario} {label}");
    print!("{}", String::from_utf8_lossy(&out.stdout));
    let err = String::from_utf8_lossy(&out.stderr);
    if !err.trim().is_empty() {
        print!("(stderr) {err}");
    }
}

fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("lazy") => lazy(),
        Some("inject") => inject(),
        Some("late-inject") => late_inject(),
        Some("bridge") => bridge(),
        Some("two-runtimes") => two_runtimes(),
        _ => {
            println!("available CPUs: {}", std::thread::available_parallelism().unwrap());
            run_child("lazy", &[]);
            run_child("lazy", &[("NAUTILUS_WORKER_THREADS", "2")]);
            run_child("lazy", &[("NAUTILUS_WORKER_THREADS", "zero")]);
            run_child("inject", &[]);
            run_child("late-inject", &[]);
            run_child("bridge", &[]);
            run_child("two-runtimes", &[]);
        }
    }
}
