//! Chapter 36 experiments: a Redis cache backend and Redis stream egress/ingress.
//!
//! Needs a local Redis (>= 6.2) on 127.0.0.1:6379, or set REDIS_PORT.
//! Run: cargo run --example ch36_redis   (about 15 seconds)

use std::{
    cell::RefCell,
    fmt::Debug,
    process::{Command, Stdio},
    rc::Rc,
    sync::OnceLock,
    thread,
    time::{Duration, Instant},
};

use nautilus_common::{
    actor::{DataActor, DataActorConfig, DataActorCore},
    cache::{Cache, CacheConfig, database::CacheDatabaseFactory},
    live::get_runtime,
    logging::logger::LoggerConfig,
    msgbus::{self, MessageBusConfig, switchboard},
    nautilus_actor,
    timer::TimeEvent,
};
use nautilus_core::{DurationNanos, UUID4, UnixNanos};
use nautilus_infrastructure::redis::{cache::RedisCacheConfig, msgbus::RedisMessageBusConfig};
use nautilus_live::{builder::LiveNodeBuilder, config::LiveNodeConfig};
use nautilus_model::{
    data::QuoteTick,
    enums::{OrderSide, OrderType},
    identifiers::{AccountId, ActorId, ClientId, TraderId, VenueOrderId},
    instruments::{Instrument, InstrumentAny, stubs::crypto_perpetual_ethusdt},
    orders::{Order, OrderTestBuilder, stubs::TestOrderEventStubs},
    types::{Price, Quantity},
};

fn port() -> u16 {
    std::env::var("REDIS_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(6379)
}

fn redis() -> redis::Connection {
    redis::Client::open(format!("redis://127.0.0.1:{}/", port()))
        .unwrap()
        .get_connection()
        .unwrap()
}

fn keys(con: &mut redis::Connection) -> Vec<String> {
    let mut k: Vec<String> = redis::cmd("KEYS").arg("trader-*").query(con).unwrap();
    k.sort();
    k
}

// #region cache
async fn cache_backend() {
    let trader_id = TraderId::from("LAB-001");
    let config = CacheConfig { buffer_interval_ms: Some(200), ..Default::default() };
    let backend = RedisCacheConfig { port: Some(port()), ..Default::default() };
    let adapter = backend.create(trader_id, UUID4::new(), config.clone()).await.unwrap();
    let mut cache = Cache::new(Some(config.clone()), Some(adapter));
    let mut con = redis();

    let instrument = InstrumentAny::CryptoPerpetual(crypto_perpetual_ethusdt());
    cache.add_instrument(instrument.clone()).unwrap();
    let order = OrderTestBuilder::new(OrderType::Limit)
        .instrument_id(instrument.id())
        .side(OrderSide::Buy)
        .price(Price::from("2900.00"))
        .quantity(Quantity::from("0.100"))
        .build();
    let id = order.client_order_id();
    cache.add_order(order.clone(), None, None, false).unwrap();
    println!("right after add_order: {} key(s) in Redis", keys(&mut con).len());
    thread::sleep(Duration::from_millis(300));
    for k in keys(&mut con) {
        let kind: String = redis::cmd("TYPE").arg(&k).query(&mut con).unwrap();
        println!("  {k}  ({kind})");
    }

    // Three more events: submitted, accepted, filled.
    let account = AccountId::from("BINANCE-001");
    let mut o = order;
    for event in [
        TestOrderEventStubs::submitted(&o, account),
        TestOrderEventStubs::accepted(&o, account, VenueOrderId::from("V-1")),
    ] {
        o.apply(event.clone()).unwrap();
        cache.update_order(&event).unwrap();
    }
    let filled = TestOrderEventStubs::filled(&o, &instrument, None, None, None, None, None, None, None, Some(account));
    o.apply(filled.clone()).unwrap();
    cache.update_order(&filled).unwrap();
    thread::sleep(Duration::from_millis(300));
    let order_key = format!("trader-LAB-001:orders:{id}");
    let len: usize = redis::cmd("LLEN").arg(&order_key).query(&mut con).unwrap();
    println!("after 3 more events: LLEN {order_key} = {len}");
    let open: Vec<String> = redis::cmd("SMEMBERS").arg("trader-LAB-001:index:orders_closed").query(&mut con).unwrap();
    println!("index:orders_closed = {open:?}");

    // A fresh process would do this on start: a new Cache over the same database.
    let adapter = backend.create(trader_id, UUID4::new(), config.clone()).await.unwrap();
    let mut restored = Cache::new(Some(config), Some(adapter));
    restored.cache_all().await.unwrap();
    let o = restored.order(&id).unwrap();
    println!(
        "restored: {} status={:?} filled={} events={}",
        o.client_order_id(), o.status(), o.filled_qty(), o.events().len()
    );
}
// #endregion cache

// #region producer
static START: OnceLock<Instant> = OnceLock::new();

fn ms() -> f64 {
    START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}

/// Publishes one QuoteTick every 500 ms on the normal quotes topic.
struct Publisher {
    core: DataActorCore,
    n: u32,
}

nautilus_actor!(Publisher);

impl Debug for Publisher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("Publisher") }
}

impl DataActor for Publisher {
    fn on_start(&mut self) -> anyhow::Result<()> {
        self.clock().set_timer_ns("pub", DurationNanos::new(500_000_000), None, None, None, None, None)
    }

    fn on_time_event(&mut self, _event: &TimeEvent) -> anyhow::Result<()> {
        self.n += 1;
        let id = crypto_perpetual_ethusdt().id();
        let bid = Price::from(format!("{}.00", 3000 + self.n).as_str());
        let quote = QuoteTick::new(
            id, bid, Price::from(format!("{}.50", 3000 + self.n).as_str()),
            Quantity::from("1.000"), Quantity::from("1.000"), UnixNanos::default(), UnixNanos::default(),
        );
        msgbus::publish_quote(switchboard::get_quotes_topic(id), &quote);
        println!("{:>6.0} ms  producer: published quote #{} (bid {bid})", ms(), self.n);
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> { Ok(()) }
}

fn node_config(trader: &str) -> LiveNodeConfig {
    let mut c = LiveNodeConfig {
        trader_id: TraderId::from(trader),
        logging: LoggerConfig {
            stdout_level: if std::env::var("LAB_DEBUG").is_ok() { log::LevelFilter::Debug } else { log::LevelFilter::Warn },
            ..Default::default()
        },
        delay_post_stop: Duration::ZERO,
        ..Default::default()
    };
    c.exec_engine.reconciliation = false;
    c
}

fn run_producer() {
    START.set(Instant::now()).unwrap();
    let msgbus = MessageBusConfig {
        use_trader_prefix: false,
        use_trader_id: false,
        use_instance_id: false,
        streams_prefix: "lab".to_string(),
        stream_per_topic: false,
        ..Default::default()
    };
    let mut node = LiveNodeBuilder::from_config(node_config("PRODUCER-001")).unwrap()
        .with_msgbus_config(msgbus)
        .with_external_msgbus_factory(Box::new(RedisMessageBusConfig { port: Some(port()), ..Default::default() }))
        .build()
        .unwrap();
    node.add_actor(Publisher {
        core: DataActorCore::new(DataActorConfig { actor_id: Some(ActorId::from("PUB-001")), ..Default::default() }),
        n: 0,
    }).unwrap();
    stop_after(&node, 5_200);
    get_runtime().block_on(node.run()).unwrap();
}
// #endregion producer

// #region consumer
/// Subscribes to quotes through a client that the data engine treats as external.
struct Listener {
    core: DataActorCore,
}

nautilus_actor!(Listener);

impl Debug for Listener {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("Listener") }
}

impl DataActor for Listener {
    fn on_start(&mut self) -> anyhow::Result<()> {
        // The subscribe command is not sent anywhere; it registers QuoteTick for inbound streaming.
        self.subscribe_quotes(crypto_perpetual_ethusdt().id(), Some(ClientId::from("LAB_EXT")), None);
        Ok(())
    }

    fn on_quote(&mut self, quote: &QuoteTick) -> anyhow::Result<()> {
        println!("{:>6.0} ms  consumer: on_quote (bid {})", ms(), quote.bid_price);
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> { Ok(()) }
}

fn run_consumer(with_subscription: bool) {
    START.set(Instant::now()).unwrap();
    let msgbus = MessageBusConfig { external_streams: Some(vec!["lab".to_string()]), ..Default::default() };
    let mut config = node_config("CONSUMER-001");
    config.data_engine.external_clients = Some(vec![ClientId::from("LAB_EXT")]);
    let mut node = LiveNodeBuilder::from_config(config).unwrap()
        .with_msgbus_config(msgbus)
        .with_external_msgbus_factory(Box::new(RedisMessageBusConfig { port: Some(port()), ..Default::default() }))
        .build()
        .unwrap();
    node.kernel().cache().borrow_mut()
        .add_instrument(InstrumentAny::CryptoPerpetual(crypto_perpetual_ethusdt())).unwrap();
    if with_subscription {
        node.add_actor(Listener {
            core: DataActorCore::new(DataActorConfig { actor_id: Some(ActorId::from("LISTEN-001")), ..Default::default() }),
        }).unwrap();
    }
    let seen = Rc::new(RefCell::new(0));
    let counter = seen.clone();
    node.add_stream_processor(move |_message| *counter.borrow_mut() += 1);
    stop_after(&node, 2_000);
    get_runtime().block_on(node.run()).unwrap();
    println!("stream processor was called {} time(s)", seen.borrow());
}
// #endregion consumer

fn stop_after(node: &nautilus_live::node::LiveNode, millis: u64) {
    let handle = node.handle();
    thread::spawn(move || {
        thread::sleep(Duration::from_millis(millis));
        handle.stop();
    });
}

fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("producer") => run_producer(),
        Some("consumer") => run_consumer(true),
        Some("consumer-unsubscribed") => run_consumer(false),
        _ => {
            let _: () = redis::cmd("FLUSHALL").query(&mut redis()).unwrap();
            println!("-- cache backend");
            get_runtime().block_on(cache_backend());

            // #region driver
            println!("-- message bus: producer starts now; consumers join 0.5 s and 2.5 s later");
            let exe = std::env::current_exe().unwrap();
            let spawn = |arg: &str| Command::new(&exe).arg(arg).stdout(Stdio::piped()).spawn().unwrap();
            let producer = spawn("producer");
            thread::sleep(Duration::from_millis(500));
            let plain = spawn("consumer-unsubscribed");
            thread::sleep(Duration::from_millis(2_000));
            let consumer = spawn("consumer");
            for (label, child) in [
                ("producer", producer),
                ("consumer without subscription, clock starts at 0.5 s", plain),
                ("consumer with subscription, clock starts at 2.5 s", consumer),
            ] {
                let out = child.wait_with_output().unwrap();
                println!("[{label}]\n{}", String::from_utf8_lossy(&out.stdout).trim_end());
            }
            // #endregion driver

            let mut con = redis();
            let len: usize = redis::cmd("XLEN").arg("lab").query(&mut con).unwrap();
            println!("XLEN lab = {len}");
            let first: redis::Value = redis::cmd("XRANGE").arg("lab").arg("-").arg("+").arg("COUNT").arg(1).query(&mut con).unwrap();
            println!("first entry: {}", field_names(&first).join(", "));
        }
    }
}

/// Fields of the first XRANGE entry; the payload is binary, so only its size is shown.
fn field_names(v: &redis::Value) -> Vec<String> {
    let mut out = Vec::new();
    if let redis::Value::Array(entries) = v
        && let Some(redis::Value::Array(entry)) = entries.first()
        && let Some(redis::Value::Array(fields)) = entry.get(1)
    {
        for pair in fields.chunks(2) {
            if let (redis::Value::BulkString(name), redis::Value::BulkString(value)) = (&pair[0], &pair[1]) {
                let name = String::from_utf8_lossy(name).to_string();
                if name == "payload" {
                    out.push(format!("payload=<{} bytes>", value.len()));
                } else {
                    out.push(format!("{name}={}", String::from_utf8_lossy(value)));
                }
            }
        }
    }
    out
}
