//! Chapter 35 experiments: BookSync phases, the snapshot gate, and the recovery
//! retry schedule (run on Tokio's paused clock, so hours pass in milliseconds).
//!
//! Run: cargo run --example ch35_book_sync

use std::{cell::RefCell, fmt, sync::Arc};

use nautilus_common::live::dst::time::{self, Duration, Instant};
use nautilus_live::book::{BookSequenceOutcome, recovery::BookRecovery, sync::BookSync};

#[derive(Debug, Clone)]
struct LabError(String);

impl fmt::Display for LabError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for LabError {}

type Sync = BookSync<LabError, u64>;

// #region sequence
/// OKX-style check (simplified from crates/adapters/okx/src/book/sync.rs):
/// a snapshot has prevSeqId = -1, a delta's prevSeqId must equal the last seqId.
fn on_message(sync: &mut Sync, prev_seq_id: i64, seq_id: u64) -> String {
    let now = Instant::now();
    if prev_seq_id == -1 {
        let accepted = sync.accept_snapshot(seq_id, now);
        return format!("snapshot accepted = {accepted}");
    }
    let linked = sync.position().is_some_and(|last| prev_seq_id >= 0 && prev_seq_id as u64 == *last);
    if linked {
        sync.advance(seq_id, now);
        "linked, emit delta".to_string()
    } else {
        match sync.gap() {
            BookSequenceOutcome::Recover => "GAP -> gap() = Recover (nobody owns recovery)".to_string(),
            other => format!("GAP -> gap() = {other:?}"),
        }
    }
}

fn sequence() {
    let mut sync: Sync = BookSync::new(Instant::now());
    let show = |sync: &mut Sync, label: &str, prev: i64, seq: u64| {
        let what = on_message(sync, prev, seq);
        println!("{label:<20} ({prev:>3}, {seq}) -> {what:<46} phase = {:?}", sync.phase());
    };
    println!("start: phase = {:?}", sync.phase());
    show(&mut sync, "snapshot", -1, 500);
    show(&mut sync, "delta", 500, 501);
    show(&mut sync, "delta", 501, 502);
    show(&mut sync, "delta (503,504 lost)", 504, 505);
    show(&mut sync, "delta", 505, 506);

    let recovery = sync.claim();
    println!("claim() -> {}", if recovery.is_some() { "Some(recovery)" } else { "None" });
    show(&mut sync, "delta", 506, 507);
    println!("claim() again -> {}", if sync.claim().is_some() { "Some" } else { "None (one recovery at a time)" });

    // #region gate
    let recovery = recovery.unwrap();
    assert!(recovery.begin_replacement()); // attempt starts: gate closed, re-subscribe in flight
    show(&mut sync, "stale snapshot", -1, 600);
    recovery.gate.open(); // the venue confirmed the new subscription
    show(&mut sync, "fresh snapshot", -1, 610);
    println!("recovery accepted = {}", recovery.is_accepted());
    show(&mut sync, "delta", 610, 611);
    // #endregion gate
}
// #endregion sequence

// #region retry
async fn retry_schedule() {
    let mut sync: Sync = BookSync::new(Instant::now());
    sync.accept_snapshot(1, Instant::now());
    let _ = sync.gap();
    let recovery: Arc<BookRecovery<LabError>> = sync.claim().unwrap();
    let sync = RefCell::new(sync);

    let t0 = Instant::now();
    let attempts = RefCell::new(Vec::new());
    let replace = |_cancel, _gate| {
        attempts.borrow_mut().push(t0.elapsed().as_secs_f64());
        async { Err::<(), _>(LabError("subscribe rejected".into())) } // every attempt fails
    };
    let run = recovery.run(
        "ETH-USDT-SWAP.OKX",
        Duration::from_secs(10),
        replace,
        |_| true,
        LabError,
        || LabError("snapshot timeout".into()),
    );
    let driver = async {
        time::sleep(Duration::from_secs(1_500)).await;
        println!("  [t = 1500 s] network reconnected -> reset_on_reconnect()");
        sync.borrow_mut().reset_on_reconnect();
        time::sleep(Duration::from_secs(3_600)).await;
        recovery.cancellation.cancel(); // e.g. unsubscribe
    };
    tokio::join!(run, driver);

    let a = attempts.borrow();
    let mut prev = 0.0;
    for (i, t) in a.iter().enumerate() {
        println!("  attempt {:>2} at {:>7.1} s  (+{:>6.1} s)", i + 1, t, t - prev);
        prev = *t;
    }
}
// #endregion retry

fn main() {
    sequence();
    println!("-- recovery retry schedule (virtual time)");
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .start_paused(true)
        .build()
        .unwrap()
        .block_on(retry_schedule());
}
