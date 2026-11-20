//! Chapter 32 experiments: AtomicTime and real-time timers.
//!
//! The main thread plays the node's core thread: it receives `TimeEventMessage`s
//! from the timer tasks and dispatches them, exactly as the event loop does.
//!
//! Run: NAUTILUS_WORKER_THREADS=1 cargo run --example ch32_live_clock

use std::{
    cell::RefCell,
    rc::Rc,
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

use live_lab::init_print_logger;
use nautilus_common::{
    clock::Clock,
    live::{LiveClock, get_runtime},
    runner::{TimeEventMessage, TimeEventSender},
    timer::{TimeEvent, TimeEventCallback},
};
use nautilus_core::{DurationNanos, UnixNanos, time::get_atomic_clock_realtime};

const MS: u64 = 1_000_000;

// #region sender
/// Forwards timer messages to the "core" thread, like the node's time-event channel.
#[derive(Debug)]
struct ChannelSender(mpsc::Sender<TimeEventMessage>);

impl TimeEventSender for ChannelSender {
    fn send(&self, message: TimeEventMessage) {
        let _ = self.0.send(message);
    }
}
// #endregion sender

/// What the callback saw: (name, ts_event, ts_init, now at callback, ran on main thread?).
type Seen = Rc<RefCell<Vec<(String, u64, u64, u64, bool)>>>;

struct Lab {
    clock: LiveClock,
    rx: mpsc::Receiver<TimeEventMessage>,
    seen: Seen,
    t0: u64,
}

impl Lab {
    fn new() -> Self {
        let (tx, rx) = mpsc::channel();
        let mut clock = LiveClock::new(Some(std::sync::Arc::new(ChannelSender(tx))));
        let seen: Seen = Rc::default();
        let main = thread::current().id();
        let sink = seen.clone();
        // A thread-local (Rc) callback, like the one Trader registers for components.
        clock.register_default_handler(TimeEventCallback::RustLocal(Rc::new(move |e: TimeEvent| {
            let now = get_atomic_clock_realtime().get_time_ns().as_u64();
            sink.borrow_mut().push((
                e.name.to_string(),
                e.ts_event.as_u64(),
                e.ts_init.as_u64(),
                now,
                thread::current().id() == main,
            ));
        })));
        let t0 = clock.timestamp_ns().as_u64();
        Self { clock, rx, seen, t0 }
    }

    /// Dispatches every queued message on this (core) thread.
    fn drain(&self) -> usize {
        let mut n = 0;
        while let Ok(msg) = self.rx.try_recv() {
            if msg.dispatch() {
                n += 1;
            }
        }
        n
    }

    /// Receives and dispatches for `dur`, like a responsive event loop.
    fn pump(&self, dur: Duration) {
        let end = Instant::now() + dur;
        while Instant::now() < end {
            if let Ok(msg) = self.rx.recv_timeout(Duration::from_millis(5)) {
                msg.dispatch();
            }
        }
    }

    fn print(&self, title: &str) {
        println!("{title}");
        for (name, ev, init, now, on_main) in self.seen.borrow_mut().drain(..) {
            println!(
                "  {name:<6} ts_event=+{:>6.1} ms  ts_init-ts_event={:>6.2} ms  callback-ts_init={:>6.2} ms  core thread={on_main}",
                (ev - self.t0) as f64 / MS as f64,
                (init - ev) as f64 / MS as f64,
                (now - init) as f64 / MS as f64,
            );
        }
    }
}

fn main() {
    init_print_logger();
    println!("tokio workers: {}", get_runtime().metrics().num_workers());

    // #region atomic
    let mut handles = Vec::new();
    for _ in 0..4 {
        handles.push(thread::spawn(|| {
            let clock = get_atomic_clock_realtime();
            (0..200_000).map(|_| clock.get_time_ns().as_u64()).collect::<Vec<_>>()
        }));
    }
    let mut all: Vec<u64> = Vec::new();
    let mut each_increasing = true;
    for h in handles {
        let v = h.join().unwrap();
        each_increasing &= v.windows(2).all(|w| w[1] > w[0]);
        all.extend(v);
    }
    let total = all.len();
    all.sort_unstable();
    all.dedup();
    println!("AtomicTime: {total} reads on 4 threads, unique = {}, strictly increasing per thread = {each_increasing}", all.len());
    // #endregion atomic

    // #region fixed
    let mut lab = Lab::new();
    let start = UnixNanos::from(lab.t0 + 100 * MS);
    lab.clock
        .set_timer_ns("tick", DurationNanos::new(100 * MS), Some(start), None, None, None, None)
        .unwrap();
    lab.pump(Duration::from_millis(560));
    lab.print("A. responsive core thread, 100 ms timer:");

    thread::sleep(Duration::from_millis(500)); // core thread busy, not draining
    let n = lab.drain();
    lab.print(&format!("B. core thread busy for 500 ms, then drained {n} queued events:"));

    // Block the only Tokio worker: the timer task itself cannot run.
    get_runtime().spawn(async { std::thread::sleep(Duration::from_millis(500)) });
    lab.pump(Duration::from_millis(560));
    lab.print("C. Tokio worker blocked for 500 ms:");
    lab.clock.cancel_timer("tick");
    lab.drain();
    lab.seen.borrow_mut().clear();
    // #endregion fixed

    // #region past
    let lab = Lab::new();
    let mut lab = lab;
    let five_min_ago = UnixNanos::from(lab.t0 - 300_000 * MS);
    let r = lab.clock.set_timer_ns("late", DurationNanos::new(1_000 * MS), Some(five_min_ago), None, None, Some(false), None);
    println!("D. start time 5 min ago, allow_past=false -> {:?}", r.map_err(|e| e.to_string()));
    let r = lab.clock.set_timer_ns("late", DurationNanos::new(1_000 * MS), Some(five_min_ago), None, None, Some(true), None);
    println!("   start time 5 min ago, allow_past=true  -> {:?}", r.map_err(|e| e.to_string()));
    lab.pump(Duration::from_millis(50));
    lab.print("   events within 50 ms:");
    lab.clock.cancel_timer("late");
    // #endregion past

    // #region alert
    let mut lab = Lab::new();
    let at = UnixNanos::from(lab.t0 + 300 * MS);
    lab.clock.set_time_alert_ns("alert", at, None, None).unwrap();
    lab.pump(Duration::from_millis(100));
    // Same name again: replaces the pending alert.
    let at2 = UnixNanos::from(lab.t0 + 500 * MS);
    lab.clock.set_time_alert_ns("alert", at2, None, None).unwrap();
    lab.pump(Duration::from_millis(600));
    lab.print("E. alert at +300 ms, replaced at +100 ms by same-name alert at +500 ms:");
    println!("   timers left: {:?}", lab.clock.timer_names());
    // #endregion alert

    // #region cancel
    let mut lab = Lab::new();
    lab.clock
        .set_timer_ns("tick", DurationNanos::new(100 * MS), None, None, None, None, None)
        .unwrap();
    thread::sleep(Duration::from_millis(150)); // one event fired and is queued
    lab.clock.cancel_timer("tick");
    let n = lab.drain();
    thread::sleep(Duration::from_millis(300));
    let later = lab.drain();
    println!("F. cancel after one fire: dispatched {n} queued event(s), {later} afterwards");
    lab.print("   callbacks:");
    // #endregion cancel
}
