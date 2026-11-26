//! Chapter 33 experiments: GCRA rate limiting, backoff, and WebSocket reconnects
//! against a local server that keeps dropping the connection.
//!
//! Run: cargo run --example ch33_network   (takes about 35 seconds)

use std::{
    num::NonZeroU32,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use futures_util::StreamExt;
use live_lab::ms;
use nautilus_common::live::get_runtime;
use nautilus_network::{
    SocketState, SocketStateSink,
    backoff::ExponentialBackoff,
    ratelimiter::{RateLimiter, quota::Quota},
    websocket::{WebSocketClient, WebSocketConfig},
};
use ustr::Ustr;

fn per_second(n: u32) -> Quota {
    Quota::per_second(NonZeroU32::new(n).unwrap()).unwrap()
}

// #region gcra
async fn gcra() {
    // 11 requests at t=0 against one key with per_second(10).
    let limiter = Arc::new(RateLimiter::new_with_quota(None, vec![(Ustr::from("k"), per_second(10))]));
    let t0 = Instant::now();
    let mut tasks = Vec::new();
    for _ in 0..12 {
        let l = limiter.clone();
        tasks.push(tokio::spawn(async move {
            l.until_key_ready(&Ustr::from("k")).await;
            ms(t0)
        }));
    }
    let mut times: Vec<f64> = Vec::new();
    for t in tasks {
        times.push(t.await.unwrap());
    }
    times.sort_by(f64::total_cmp);
    println!("per_second(10), 12 requests released at (ms): {}", fmt(&times));

    // Two keys on every request: a global 10/s and an endpoint 2/s.
    let limiter = Arc::new(RateLimiter::new_with_quota(
        None,
        vec![(Ustr::from("global"), per_second(10)), (Ustr::from("balance"), per_second(2))],
    ));
    let keys = [Ustr::from("global"), Ustr::from("balance")];
    let t0 = Instant::now();
    let mut times = Vec::new();
    for _ in 0..5 {
        limiter.await_keys_ready(Some(&keys)).await;
        times.push(ms(t0));
    }
    println!("keys [global 10/s, balance 2/s], 5 requests at (ms): {}", fmt(&times));

    // A default quota applies to each unknown key separately.
    let limiter = RateLimiter::new_with_quota(Some(per_second(2)), vec![]);
    let a = (0..3).map(|_| limiter.check_key(&Ustr::from("a")).is_ok()).collect::<Vec<_>>();
    let b = (0..3).map(|_| limiter.check_key(&Ustr::from("b")).is_ok()).collect::<Vec<_>>();
    println!("default per_second(2): key a allowed {a:?}, key b allowed {b:?}");
}
// #endregion gcra

// #region backoff
fn backoff() {
    let mut b = ExponentialBackoff::new(
        Duration::from_secs(2),
        Duration::from_secs(30),
        1.5,
        100,
        true,
    )
    .unwrap();
    let seq: Vec<f64> = (0..11).map(|_| b.next_duration().as_secs_f64()).collect();
    println!(
        "backoff (2 s, 30 s, x1.5, jitter 100 ms, immediate first): {}",
        seq.iter().map(|s| format!("{s:.2}")).collect::<Vec<_>>().join(" → ")
    );
}
// #endregion backoff

// #region server
/// Accepts WebSocket connections; connection n is held for HOLD[n] and then closed.
const HOLD_MS: [u64; 8] = [100, 100, 100, 100, 100, 11_000, 100, 60_000];

async fn server(listener: tokio::net::TcpListener, t0: Instant, log: Arc<Mutex<Vec<String>>>) {
    for (n, hold) in HOLD_MS.iter().enumerate() {
        let (stream, _) = listener.accept().await.unwrap();
        log.lock().unwrap().push(format!("{:>8.0} ms  server: accepted connection #{}", ms(t0), n + 1));
        let hold = Duration::from_millis(*hold);
        tokio::spawn(async move {
            let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
            tokio::time::sleep(hold).await;
            let _ = ws.close(None).await;
            while ws.next().await.is_some() {}
        });
    }
}
// #endregion server

// #region reconnect
async fn reconnect() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("ws://{}", listener.local_addr().unwrap());
    let t0 = Instant::now();
    let log = Arc::new(Mutex::new(Vec::new()));
    tokio::spawn(server(listener, t0, log.clone()));

    let sink_log = log.clone();
    let sink = SocketStateSink::new(move |state: SocketState| {
        sink_log.lock().unwrap().push(format!("{:>8.0} ms  client state: {state:?}", ms(t0)));
    });
    let config = WebSocketConfig::builder().url(url).build().unwrap();
    let client = WebSocketClient::builder()
        .config(config)
        .message_handler(Arc::new(|_| {}))
        .state_sink(sink)
        .connect()
        .await
        .unwrap();

    while log.lock().unwrap().iter().filter(|l| l.contains("accepted")).count() < HOLD_MS.len() {
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    tokio::time::sleep(Duration::from_millis(200)).await;
    client.disconnect().await;
    for line in log.lock().unwrap().iter() {
        println!("{line}");
    }
}
// #endregion reconnect

// #region refused
/// The venue goes away: the first connection is dropped and the port refuses
/// connections for 20 s. The client's own WARN logs show each failed attempt.
async fn refused() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let t0 = Instant::now();
    START.set(t0).ok();
    let log = Arc::new(Mutex::new(Vec::new()));
    let server_log = log.clone();
    tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        tokio::time::sleep(Duration::from_millis(100)).await;
        let _ = ws.close(None).await;
        drop(listener); // port now refuses connections
        tokio::time::sleep(Duration::from_secs(20)).await;
        let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
        server_log.lock().unwrap().push(format!("{:>8.0} ms  server: listening again", ms(t0)));
        let (stream, _) = listener.accept().await.unwrap();
        server_log.lock().unwrap().push(format!("{:>8.0} ms  server: accepted", ms(t0)));
        let _ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        tokio::time::sleep(Duration::from_secs(60)).await;
    });

    let sink_log = log.clone();
    let sink = SocketStateSink::new(move |state: SocketState| {
        sink_log.lock().unwrap().push(format!("{:>8.0} ms  client state: {state:?}", ms(t0)));
    });
    let config = WebSocketConfig::builder().url(format!("ws://{addr}")).build().unwrap();
    let client = WebSocketClient::builder()
        .config(config)
        .message_handler(Arc::new(|_| {}))
        .state_sink(sink)
        .connect()
        .await
        .unwrap();
    while log.lock().unwrap().iter().filter(|l| l.contains("Connected")).count() < 2 {
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    client.disconnect().await;
    let mut lines = log.lock().unwrap().clone();
    lines.extend(WARNS.lock().unwrap().iter().cloned());
    lines.sort_by_key(|l| l.split_whitespace().next().and_then(|t| t.parse::<u64>().ok()));
    for line in lines {
        println!("{line}");
    }
}

static START: std::sync::OnceLock<Instant> = std::sync::OnceLock::new();
static WARNS: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// Collects the client's reconnect WARN lines with a timestamp.
struct WarnCollector;

impl log::Log for WarnCollector {
    fn enabled(&self, m: &log::Metadata) -> bool {
        m.level() <= log::Level::Warn
    }
    fn log(&self, r: &log::Record) {
        let msg = r.args().to_string();
        if let Some(t0) = START.get()
            && (msg.starts_with("Backing off") || msg.starts_with("Reconnect attempt"))
        {
            let short = msg.split(':').next().unwrap_or(&msg).to_string();
            WARNS.lock().unwrap().push(format!("{:>8.0} ms  client log: {short}", ms(*t0)));
        }
    }
    fn flush(&self) {}
}
// #endregion refused

fn fmt(v: &[f64]) -> String {
    v.iter().map(|t| format!("{t:.0}")).collect::<Vec<_>>().join(", ")
}

fn main() {
    static COLLECTOR: WarnCollector = WarnCollector;
    log::set_logger(&COLLECTOR).unwrap();
    log::set_max_level(log::LevelFilter::Warn);

    backoff();
    get_runtime().block_on(async {
        gcra().await;
        println!("-- server accepts, then drops each connection");
        reconnect().await;
        println!("-- server refuses connections for 20 s");
        refused().await;
    });
}
