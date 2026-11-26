//! Verify `InternalBarStrength` inside a real BacktestEngine run.
//!
//! Usage: cargo run --example backtest_ibs -- /path/to/nautilus_trader/test_data/binance/ethusdt-trades.csv

use std::{cell::RefCell, fmt::Debug, fs, rc::Rc};

use ibs_lab::InternalBarStrength;
use nautilus_backtest::{
    config::{BacktestEngineConfig, SimulatedVenueConfig},
    engine::BacktestEngine,
};
use nautilus_execution::models::fee::{FeeModelAny, MakerTakerFeeModel};
use nautilus_common::{
    actor::{DataActor, DataActorConfig, DataActorCore, DataActorNative},
    nautilus_actor,
};
use nautilus_model::{
    data::{Bar, BarType, Data, TradeTick},
    enums::{AccountType, AggressorSide, BookType, OmsType},
    identifiers::{ActorId, TradeId, Venue},
    instruments::{Instrument, InstrumentAny, stubs::currency_pair_ethusdt},
    types::Money,
};

const PERIOD: usize = 10;
const TICKS_PER_BAR: usize = 250;
const BAR_TYPE: &str = "ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL";

/// One row per bar seen by the actor.
#[derive(Clone, Debug)]
struct Row {
    high: f64,
    low: f64,
    close: f64,
    value: f64,
    initialized: bool,
}

// #region actor
struct IbsProbe {
    core: DataActorCore,
    bar_type: BarType,
    ibs: Rc<RefCell<InternalBarStrength>>,
    rows: Rc<RefCell<Vec<Row>>>,
}

nautilus_actor!(IbsProbe);

impl Debug for IbsProbe {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IbsProbe").finish()
    }
}

impl DataActor for IbsProbe {
    fn on_start(&mut self) -> anyhow::Result<()> {
        let bar_type = self.bar_type;
        let ibs = Rc::clone(&self.ibs);
        self.core_mut().register_indicator_for_bars(bar_type, ibs);
        self.subscribe_bars(bar_type, None, None);
        Ok(())
    }

    fn on_stop(&mut self) -> anyhow::Result<()> {
        let bar_type = self.bar_type;
        self.unsubscribe_bars(bar_type, None, None);
        Ok(())
    }

    fn on_bar(&mut self, bar: &Bar) -> anyhow::Result<()> {
        // The framework has already fed this bar to the indicator.
        let ibs = self.ibs.borrow();
        self.rows.borrow_mut().push(Row {
            high: bar.high.as_f64(),
            low: bar.low.as_f64(),
            close: bar.close.as_f64(),
            value: ibs.value,
            initialized: ibs.initialized,
        });
        Ok(())
    }
}
// #endregion actor

// #region load
fn load_trades(path: &str, instrument: &InstrumentAny) -> anyhow::Result<Vec<Data>> {
    let text = fs::read_to_string(path)?;
    let mut out = Vec::new();
    for line in text.lines().skip(1) {
        // timestamp,trade_id,price,quantity,buyer_maker
        let cols: Vec<&str> = line.split(',').collect();
        let ts: jiff::Timestamp = cols[0].parse()?;
        let ts = (ts.as_nanosecond() as u64).into();
        let side = if cols[4] == "True" {
            AggressorSide::Sell
        } else {
            AggressorSide::Buy
        };
        // The CSV drops trailing zeros ("423.7"), so build prices and sizes with the
        // instrument's precision instead of `Price::from(&str)`.
        out.push(Data::Trade(TradeTick::new(
            instrument.id(),
            instrument.make_price(cols[2].parse()?),
            instrument.make_qty(cols[3].parse()?, None),
            side,
            TradeId::new(cols[1]),
            ts,
            ts,
        )));
    }
    Ok(out)
}
// #endregion load

// #region oracle
/// Independent oracle: group raw prices into 250-trade bars and average IBS naively.
fn oracle(prices: &[f64]) -> Vec<(f64, f64, f64, Option<f64>)> {
    let mut ibs_seen = Vec::new();
    let mut out = Vec::new();
    for chunk in prices.chunks_exact(TICKS_PER_BAR) {
        let high = chunk.iter().copied().fold(f64::MIN, f64::max);
        let low = chunk.iter().copied().fold(f64::MAX, f64::min);
        let close = *chunk.last().unwrap();
        if high > low {
            ibs_seen.push((close - low) / (high - low));
        }
        let value = (ibs_seen.len() >= PERIOD).then(|| {
            ibs_seen[ibs_seen.len() - PERIOD..].iter().sum::<f64>() / PERIOD as f64
        });
        out.push((high, low, close, value));
    }
    out
}
// #endregion oracle

fn main() -> anyhow::Result<()> {
    let path = std::env::args()
        .nth(1)
        .expect("pass the path to ethusdt-trades.csv");

    // #region engine
    let mut engine = BacktestEngine::new(BacktestEngineConfig::default())?;
    engine.add_venue(
        SimulatedVenueConfig::builder()
            .venue(Venue::from("BINANCE"))
            .oms_type(OmsType::Netting)
            .account_type(AccountType::Cash)
            .book_type(BookType::L1_MBP)
            .starting_balances(vec![Money::from("1000000 USDT"), Money::from("10 ETH")])
            .fee_model(FeeModelAny::MakerTaker(MakerTakerFeeModel::zero()).into())
            .build()?,
    )?;

    let instrument = InstrumentAny::CurrencyPair(currency_pair_ethusdt());
    engine.add_instrument(&instrument)?;

    let ibs = Rc::new(RefCell::new(InternalBarStrength::new(PERIOD)));
    let rows = Rc::new(RefCell::new(Vec::new()));
    engine.add_actor(IbsProbe {
        core: DataActorCore::new(DataActorConfig {
            actor_id: Some(ActorId::from("IBS-PROBE-001")),
            ..Default::default()
        }),
        bar_type: BarType::from(BAR_TYPE),
        ibs: Rc::clone(&ibs),
        rows: Rc::clone(&rows),
    })?;

    let trades = load_trades(&path, &instrument)?;
    let prices: Vec<f64> = trades
        .iter()
        .map(|d| match d {
            Data::Trade(t) => t.price.as_f64(),
            _ => unreachable!(),
        })
        .collect();
    println!("trades: {}", trades.len());
    engine.add_data(trades, None, true, true)?;
    engine.run(None, None, None, false)?;
    // #endregion engine

    // #region compare
    let rows = rows.borrow();
    let expected = oracle(&prices);
    println!("bars seen by actor: {}, oracle bars: {}", rows.len(), expected.len());
    assert_eq!(rows.len(), expected.len());

    let first_init = rows.iter().position(|r| r.initialized).unwrap();
    println!("first initialized at bar #{} (1-based)", first_init + 1);

    let mut max_err: f64 = 0.0;
    for (i, (row, &(h, l, c, v))) in rows.iter().zip(&expected).enumerate() {
        assert_eq!((row.high, row.low, row.close), (h, l, c), "OHLC differs at bar {i}");
        match v {
            Some(v) => max_err = max_err.max((row.value - v).abs()),
            None => assert!(!row.initialized && row.value == 0.0, "early value at bar {i}"),
        }
    }
    println!("max |indicator - oracle| = {max_err:e}");
    assert!(max_err < 1e-12);
    // #endregion compare

    for (i, row) in rows.iter().enumerate().skip(first_init).take(3) {
        println!(
            "bar #{:>3}: high={:.2} low={:.2} close={:.2} ibs={:.6}",
            i + 1,
            row.high,
            row.low,
            row.close,
            row.value
        );
    }
    let last = rows.last().unwrap();
    println!("last bar: ibs={:.6}", last.value);
    println!("indicator object after run: {}", ibs.borrow());
    println!("OK");
    Ok(())
}
