//! Chapter 34 experiments: startup reconciliation and in-flight checks against a
//! scripted fake venue.
//!
//! Run: cargo run --example ch34_reconciliation   (about 50 seconds)

use std::{
    cell::RefCell,
    fmt::Debug,
    process::Command,
    rc::Rc,
    sync::{Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};

use async_trait::async_trait;
use nautilus_common::{
    actor::DataActor,
    cache::CacheView,
    clients::ExecutionClient,
    clock::Clock,
    factories::{ClientConfig, ExecutionClientFactory},
    live::{get_exec_event_sender, get_runtime},
    logging::logger::LoggerConfig,
    messages::execution::{QueryOrder, SubmitOrder},
};
use nautilus_core::{Params, UUID4, UnixNanos, time::get_atomic_clock_realtime};
use nautilus_live::{
    ExecutionEventEmitter,
    builder::LiveNodeBuilder, config::LiveNodeConfig,
    execution::submission::SubmissionRecoveryPolicy,
};
use nautilus_model::{
    accounts::{AccountAny, MarginAccount},
    enums::{AccountType, OmsType, OrderSide, OrderStatus, OrderType, PositionSide, TimeInForce},
    events::account::state::AccountState,
    identifiers::{AccountId, ClientId, InstrumentId, StrategyId, TraderId, Venue, VenueOrderId},
    instruments::{Instrument, InstrumentAny, stubs::crypto_perpetual_ethusdt},
    orders::Order,
    reports::{ExecutionMassStatus, OrderStatusReport, PositionStatusReport},
    types::{AccountBalance, Currency, MarginBalance, Money, Price, Quantity},
};
use nautilus_trading::{
    nautilus_strategy,
    strategy::{Strategy, StrategyConfig, StrategyCore},
};
use rust_decimal::Decimal;

static START: OnceLock<Instant> = OnceLock::new();
static LOG: Mutex<Vec<(f64, String)>> = Mutex::new(Vec::new());

fn record(what: impl Into<String>) {
    let t = START.get().map_or(0.0, |s| s.elapsed().as_secs_f64());
    LOG.lock().unwrap().push((t, what.into()));
}

fn instrument() -> InstrumentAny {
    InstrumentAny::CryptoPerpetual(crypto_perpetual_ethusdt())
}

fn account_id() -> AccountId {
    AccountId::from("BINANCE-001")
}

// #region venue
/// What the fake venue reports at startup.
#[derive(Clone, Debug, Default)]
struct Script {
    external_sell: bool,
    position_long: Option<&'static str>,
}

/// A venue that answers the startup mass-status request from a script, acknowledges
/// submissions locally (OrderSubmitted) and then never says anything else.
struct FakeVenue {
    script: Script,
    cache: CacheView,
    emitter: ExecutionEventEmitter,
    connected: bool,
}

#[async_trait(?Send)]
impl ExecutionClient for FakeVenue {
    fn is_connected(&self) -> bool { self.connected }
    fn client_id(&self) -> ClientId { ClientId::from("FAKE") }
    fn account_id(&self) -> AccountId { account_id() }
    fn venue(&self) -> Venue { Venue::from("BINANCE") }
    fn oms_type(&self) -> OmsType { OmsType::Netting }
    fn get_account(&self) -> Option<AccountAny> { None }
    fn generate_account_state(
        &self, _: Vec<AccountBalance>, _: Vec<MarginBalance>, _: bool, _: UnixNanos, _: Option<Params>,
    ) -> anyhow::Result<()> { Ok(()) }
    fn start(&mut self) -> anyhow::Result<()> { Ok(()) }
    fn stop(&mut self) -> anyhow::Result<()> { Ok(()) }
    async fn connect(&mut self) -> anyhow::Result<()> {
        // Like a real adapter: events go through the exec-event channel, not straight into the engine.
        self.emitter.set_sender(get_exec_event_sender());
        self.connected = true;
        Ok(())
    }
    async fn disconnect(&mut self) -> anyhow::Result<()> { self.connected = false; Ok(()) }

    fn submit_order(&self, cmd: SubmitOrder) -> anyhow::Result<()> {
        let order = self.cache.borrow().try_order_owned(&cmd.client_order_id)?;
        self.emitter.emit_order_submitted(&order);
        record(format!("venue: submit {} (then silence)", cmd.client_order_id));
        Ok(())
    }

    fn query_order(&self, cmd: QueryOrder) -> anyhow::Result<()> {
        record(format!("venue: query_order {}", cmd.client_order_id));
        Ok(())
    }

    async fn generate_mass_status(
        &self,
        _lookback_mins: Option<u64>,
    ) -> anyhow::Result<Option<ExecutionMassStatus>> {
        let id = instrument().id();
        let mut mass = ExecutionMassStatus::new(
            self.client_id(), account_id(), self.venue(), UnixNanos::default(), Some(UUID4::new()),
        );
        if self.script.external_sell {
            // An order placed on the venue's website: we have never seen it.
            let report = OrderStatusReport::new(
                account_id(), id, None, VenueOrderId::from("V-B"), Some(OrderSide::Sell), OrderType::Limit,
                TimeInForce::Gtc, OrderStatus::Accepted, Quantity::from("0.500"), Quantity::from("0.000"),
                UnixNanos::from(1), UnixNanos::from(1), UnixNanos::from(1), None,
            )
            .with_price(Price::from("3100.00"));
            mass.add_order_reports(vec![report]);
        }
        if let Some(qty) = self.script.position_long {
            mass.add_position_reports(vec![PositionStatusReport::new(
                account_id(), id, PositionSide::Long, Quantity::from(qty),
                UnixNanos::from(1), UnixNanos::from(1), None, None,
                Some(Decimal::from(3000)),
            )]);
        }
        record("venue: mass status requested");
        Ok(Some(mass))
    }
}
// #endregion venue

#[derive(Debug)]
struct FakeVenueConfig;

impl ClientConfig for FakeVenueConfig {
    fn as_any(&self) -> &dyn std::any::Any { self }
}

#[derive(Debug)]
struct FakeVenueFactory(Script);

impl Debug for FakeVenue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("FakeVenue") }
}

impl ExecutionClientFactory for FakeVenueFactory {
    fn create(
        &self, trader_id: TraderId, _name: &str, _config: &dyn ClientConfig, cache: CacheView,
        _clock: Rc<RefCell<dyn Clock>>,
    ) -> anyhow::Result<Box<dyn ExecutionClient>> {
        Ok(Box::new(FakeVenue {
            script: self.0.clone(),
            cache,
            emitter: ExecutionEventEmitter::new(
                get_atomic_clock_realtime(), trader_id, account_id(), AccountType::Margin, None,
            ),
            connected: false,
        }))
    }
    fn name(&self) -> &'static str { "fake-venue" }
    fn config_type(&self) -> &'static str { "FakeVenueConfig" }
}

// #region strategy
struct Lab {
    core: StrategyCore,
    submit: bool,
    claim_via_trait: bool,
}

nautilus_strategy!(Lab, {
    // A Rust strategy states its claims through this trait method; the default is None.
    fn external_order_instrument_ids(&self) -> Option<Vec<InstrumentId>> {
        if self.claim_via_trait {
            self.core.config.external_order_instrument_ids.clone()
        } else {
            None
        }
    }
});

impl Debug for Lab {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result { f.write_str("Lab") }
}

impl DataActor for Lab {
    fn on_start(&mut self) -> anyhow::Result<()> {
        record("strategy: on_start");
        if self.submit {
            let order = self.order().limit(
                instrument().id(), OrderSide::Buy, Quantity::from("0.100"), Price::from("2900.00"),
                None, None, None, None, None, None, None, None, None, None, None, None,
            );
            self.submit_order(order, None, None, None)?;
        }
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> {
        Ok(())
    }
}
// #endregion strategy

#[derive(Clone, Copy, PartialEq, Eq)]
enum Claim {
    None,
    ConfigOnly,
    ConfigAndTrait,
}

// #region run
fn run(script: Script, claim: Claim, submit: bool, configure: impl FnOnce(&mut LiveNodeConfig), stop_after: Duration) {
    START.set(Instant::now()).unwrap();
    let mut config = LiveNodeConfig {
        logging: LoggerConfig { stdout_level: log::LevelFilter::Warn, ..Default::default() },
        ..Default::default()
    };
    configure(&mut config);
    let e = &config.exec_engine;
    println!(
        "generate_missing_orders={} inflight: every {} ms, threshold {} ms, retries {}, policy {:?}, startup delay {} s",
        e.generate_missing_orders, e.inflight_check_interval_ms, e.inflight_check_threshold_ms,
        e.inflight_check_retries, e.submission_recovery_policy, e.reconciliation_startup_delay_secs
    );

    let mut node = LiveNodeBuilder::from_config(config).unwrap()
        .add_exec_client(Some("FAKE".to_string()), Box::new(FakeVenueFactory(script)), Box::new(FakeVenueConfig))
        .unwrap()
        .build()
        .unwrap();

    {
        let cache = node.kernel().cache();
        let mut cache = cache.borrow_mut();
        cache.add_instrument(instrument()).unwrap();
        let state = AccountState::new(
            account_id(), AccountType::Margin,
            vec![AccountBalance::new(Money::from("1000000 USDT"), Money::from("0 USDT"), Money::from("1000000 USDT"))],
            vec![], true, UUID4::new(), UnixNanos::default(), UnixNanos::default(), Some(Currency::USDT()),
        );
        cache.add_account(AccountAny::Margin(MarginAccount::new(state, true))).unwrap();
    }

    let strategy_config = StrategyConfig {
        strategy_id: Some(StrategyId::from("LAB-001")),
        external_order_instrument_ids: (claim != Claim::None).then(|| vec![instrument().id()]),
        ..Default::default()
    };
    let claim_via_trait = claim == Claim::ConfigAndTrait;
    node.add_strategy(Lab { core: StrategyCore::new(strategy_config), submit, claim_via_trait }).unwrap();

    let handle = node.handle();
    thread::spawn(move || {
        thread::sleep(stop_after);
        handle.stop();
    });

    println!("run() called at {}", get_atomic_clock_realtime().get_time_ns().to_rfc3339());
    let result = get_runtime().block_on(node.run());
    for (t, what) in LOG.lock().unwrap().iter() {
        println!("  {t:>6.2} s  {what}");
    }
    match result {
        Ok(()) => println!("run() -> Ok"),
        Err(e) => println!("run() -> Err: {e:#}"),
    }

    let cache = node.kernel().cache();
    let cache = cache.borrow();
    for o in cache.orders(None, None, None, None, None) {
        println!(
            "  order {} {:?} {} @ {:?} status={:?} strategy={} tags={:?}",
            o.client_order_id(), o.order_side(), o.quantity(), o.price().map(|p| p.to_string()),
            o.status(), o.strategy_id(), o.tags().map(|t| t.iter().map(|s| s.to_string()).collect::<Vec<_>>()),
        );
    }
    for p in cache.positions(None, None, None, None, None) {
        println!("  position {:?} {} avg_px_open={} strategy={}", p.side, p.quantity, p.avg_px_open, p.strategy_id);
    }
}
// #endregion run

fn main() {
    let scenario = std::env::args().nth(1);
    let startup = Script { external_sell: true, position_long: Some("1.000") };
    match scenario.as_deref() {
        Some("startup") => run(startup, Claim::None, false, |_| {}, Duration::from_millis(1500)),
        Some("claim-config-only") => run(startup, Claim::ConfigOnly, false, |_| {}, Duration::from_millis(1500)),
        Some("claim-trait") => run(startup, Claim::ConfigAndTrait, false, |_| {}, Duration::from_millis(1500)),
        Some("no-missing-orders") => run(startup, Claim::None, false,
            |c| c.exec_engine.generate_missing_orders = false, Duration::from_millis(1500)),
        Some("inflight-retain") => run(Script::default(), Claim::None, true,
            |c| c.exec_engine.reconciliation_startup_delay_secs = 1.0, Duration::from_secs(40)),
        Some("inflight-resolve") => run(Script::default(), Claim::None, true, |c| {
            c.exec_engine.reconciliation_startup_delay_secs = 1.0;
            c.exec_engine.submission_recovery_policy = SubmissionRecoveryPolicy::ResolveLocally;
        }, Duration::from_secs(40)),
        _ => {
            for s in ["startup", "claim-config-only", "claim-trait", "no-missing-orders", "inflight-retain", "inflight-resolve"] {
                let out = Command::new(std::env::current_exe().unwrap()).arg(s).output().unwrap();
                println!("== {s}");
                print!("{}", String::from_utf8_lossy(&out.stdout));
            }
        }
    }
}
