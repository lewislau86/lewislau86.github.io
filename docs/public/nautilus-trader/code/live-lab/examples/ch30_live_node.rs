//! Chapter 30 experiments: a LiveNode with no clients, one Actor and a timer.
//!
//! Shows which thread runs the callbacks, the one-node-per-thread rule, and how
//! long `run()` keeps going after `stop()` for different `delay_post_stop` values.
//!
//! Run: cargo run --example ch30_live_node

use std::{
    fmt::Debug,
    process::Command,
    sync::{Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};

use live_lab::thread_summary;
use nautilus_common::{
    actor::{DataActor, DataActorConfig, DataActorCore},
    live::get_runtime,
    logging::logger::LoggerConfig,
    nautilus_actor,
    timer::TimeEvent,
};
use nautilus_core::DurationNanos;
use nautilus_live::{config::LiveNodeConfig, node::LiveNode};
use nautilus_model::identifiers::ActorId;

static START: OnceLock<Instant> = OnceLock::new();
static EVENTS: Mutex<Vec<(f64, String)>> = Mutex::new(Vec::new());

fn record(what: impl Into<String>) {
    let t = START.get().unwrap().elapsed().as_secs_f64() * 1000.0;
    let name = thread::current().name().unwrap_or("?").to_string();
    EVENTS.lock().unwrap().push((t, format!("{} [thread {name}]", what.into())));
}

// #region actor
struct Probe {
    core: DataActorCore,
    ticks: u32,
}

nautilus_actor!(Probe);

impl Debug for Probe {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Probe").finish()
    }
}

impl DataActor for Probe {
    fn on_start(&mut self) -> anyhow::Result<()> {
        record("on_start");
        record(format!("threads now: {}", thread_summary()));
        self.clock().set_timer_ns(
            "tick",
            DurationNanos::new(400_000_000),
            None,
            None,
            None,
            None,
            None,
        )?;
        Ok(())
    }

    fn on_time_event(&mut self, event: &TimeEvent) -> anyhow::Result<()> {
        self.ticks += 1;
        record(format!("on_time_event #{} ({})", self.ticks, event.name));
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> {
        record(format!("on_stop, timers left = {:?}", self.clock().timer_names()));
        Ok(())
    }
}
// #endregion actor

// #region run
fn run_node(delay_post_stop: Option<Duration>) -> anyhow::Result<()> {
    START.set(Instant::now()).unwrap();
    let mut config = LiveNodeConfig {
        logging: LoggerConfig { stdout_level: log::LevelFilter::Warn, ..Default::default() },
        ..Default::default()
    };
    config.exec_engine.reconciliation = false;
    if let Some(d) = delay_post_stop {
        config.delay_post_stop = d;
    }
    println!("delay_post_stop = {:?}", config.delay_post_stop);

    let mut node = LiveNode::build("LAB".to_string(), Some(config.clone()))?;
    match LiveNode::build("LAB-2".to_string(), Some(config)) {
        Ok(_) => println!("second node on the same thread: built"),
        Err(e) => println!("second node on the same thread: {e}"),
    }

    node.add_actor(Probe {
        core: DataActorCore::new(DataActorConfig {
            actor_id: Some(ActorId::from("PROBE-001")),
            ..Default::default()
        }),
        ticks: 0,
    })?;

    let handle = node.handle();
    thread::Builder::new().name("stopper".into()).spawn(move || {
        thread::sleep(Duration::from_millis(1_000));
        record("handle.stop()");
        handle.stop();
    })?;

    record("run() called");
    get_runtime().block_on(node.run())?; // as the Python binding does
    record(format!("run() returned, state = {:?}", node.state()));

    for (t, what) in EVENTS.lock().unwrap().iter() {
        println!("  {t:>8.1} ms  {what}");
    }
    Ok(())
}
// #endregion run

fn main() -> anyhow::Result<()> {
    match std::env::args().nth(1).as_deref() {
        Some("default") => run_node(None),
        Some(ms) => run_node(Some(Duration::from_millis(ms.parse()?))),
        None => {
            for arg in ["0", "2000", "default"] {
                let out = Command::new(std::env::current_exe()?).arg(arg).output()?;
                println!("== {arg}");
                print!("{}", String::from_utf8_lossy(&out.stdout));
            }
            Ok(())
        }
    }
}
