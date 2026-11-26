//! Chapter 31 experiments: TaskGroup admission, generations and bounded shutdown.
//!
//! Run: cargo run --example ch31_task_group

use std::time::{Duration, Instant};

use live_lab::ms;
use nautilus_common::live::get_runtime;
use nautilus_live::task::{TaskGroup, TaskJoinOutcome, TaskSlot, finish_task};

const GRACEFUL: Duration = Duration::from_secs(1);
const FORCE: Duration = Duration::from_secs(2);

// #region shutdown
/// Spawns one task of the given kind, then shuts the group down and reports timing.
async fn shutdown_case(label: &str, kind: &str) -> TaskGroup {
    let group = TaskGroup::new();
    let cancel = group.cancellation_token();
    let task = match kind {
        // Listens for the graceful token, then spends 200 ms cleaning up.
        "cooperative" => group.spawn_named("cooperative", async move {
            cancel.cancelled().await;
            tokio::time::sleep(Duration::from_millis(200)).await;
        }),
        // Ignores the graceful token but yields at an .await point.
        "ignores-cancel" => group.spawn_named("ignores-cancel", async {
            tokio::time::sleep(Duration::from_secs(60)).await;
        }),
        // Blocks its worker thread: no .await point to drop it at.
        "blocking" => group.spawn_named("blocking", async {
            std::thread::sleep(Duration::from_secs(5));
        }),
        _ => unreachable!(),
    }
    .unwrap();

    tokio::time::sleep(Duration::from_millis(50)).await;
    let t0 = Instant::now();
    group.begin_shutdown();
    let result = group.finish_shutdown(GRACEFUL, FORCE).await;
    println!(
        "{label:<15} finish_shutdown after {:>6.0} ms -> {:?}; task finished = {}",
        ms(t0),
        result.map_err(|e| e.to_string()),
        task.is_finished()
    );
    group
}
// #endregion shutdown

async fn run() {
    // #region cases
    shutdown_case("cooperative", "cooperative").await;
    shutdown_case("ignores-cancel", "ignores-cancel").await;
    let group = shutdown_case("blocking", "blocking").await;

    // The timed-out generation stays Closing and still owns the task.
    println!("after timeout: len = {}, start_generation -> {:?}", group.len(),
        group.start_generation().map_err(|e| e.to_string()));
    tokio::time::sleep(Duration::from_secs(2)).await;
    let r = group.finish_shutdown(GRACEFUL, FORCE).await;
    println!("second finish_shutdown -> {:?}; start_generation -> {:?}",
        r.map_err(|e| e.to_string()), group.start_generation().map_err(|e| e.to_string()));
    // #endregion cases

    // #region admission
    let group = TaskGroup::new();
    println!("finish_shutdown while open -> {:?}",
        group.finish_shutdown(GRACEFUL, FORCE).await.map_err(|e| e.to_string()));

    let old_spawner = group.spawner().unwrap();
    group.begin_shutdown();
    println!("spawn after begin_shutdown -> {:?}",
        group.spawn(async {}).map_err(|e| e.to_string()));
    group.finish_shutdown(GRACEFUL, FORCE).await.unwrap();
    group.start_generation().unwrap();
    println!("new generation open = {}; old spawner.spawn -> {:?}; group.spawn -> {:?}",
        group.is_open(),
        old_spawner.spawn(async {}).map_err(|e| e.to_string()),
        group.spawn(async {}).map_err(|e| e.to_string()));
    // #endregion admission

    // #region panic
    let group = TaskGroup::new();
    group.spawn_named("reader", async { panic!("bad frame") }).unwrap();
    tokio::time::sleep(Duration::from_millis(50)).await;
    group.begin_shutdown();
    println!("panicking task -> {:?}",
        group.finish_shutdown(GRACEFUL, FORCE).await.map_err(|e| e.to_string()));
    // #endregion panic

    // #region slot
    let mut slot: TaskSlot<u64> = TaskSlot::default();
    slot.spawn(async { 42 }).unwrap();
    report("slot, returns 42", finish_task(&mut slot, GRACEFUL, FORCE).await);

    let mut slot: TaskSlot<u64> = TaskSlot::default();
    slot.spawn(async {
        tokio::time::sleep(Duration::from_secs(60)).await;
        0
    })
    .unwrap();
    let t0 = Instant::now();
    let outcome = finish_task(&mut slot, Duration::from_millis(100), Duration::from_millis(100)).await;
    print!("after {:>4.0} ms: ", ms(t0));
    report("slot, sleeps 60 s", outcome);

    let mut slot: TaskSlot<u64> = TaskSlot::default();
    slot.spawn(async {
        std::thread::sleep(Duration::from_millis(500)); // blocking, cannot be aborted
        0
    })
    .unwrap();
    let outcome = finish_task(&mut slot, Duration::from_millis(100), Duration::from_millis(100)).await;
    report("slot, blocks 500 ms", outcome);
    tokio::time::sleep(Duration::from_millis(500)).await;
    report("same slot, asked again", finish_task(&mut slot, GRACEFUL, FORCE).await);
    // #endregion slot
}

fn report(label: &str, outcome: Option<TaskJoinOutcome<u64>>) {
    let s = match outcome {
        Some(TaskJoinOutcome::Completed(v)) => format!("Completed({v})"),
        Some(other) => format!("{other:?}"),
        None => "None (slot empty)".to_string(),
    };
    println!("{label} -> {s}");
}

fn main() {
    let _ = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {})); // keep the panicking task quiet
    get_runtime().block_on(run());
}
