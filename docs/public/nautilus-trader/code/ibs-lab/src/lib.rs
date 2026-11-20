//! A custom indicator for NautilusTrader: average Internal Bar Strength (IBS).
//!
//! IBS of one bar = (close - low) / (high - low), in [0, 1].
//! `InternalBarStrength(period)` is the mean IBS over the last `period` bars.

use std::{collections::VecDeque, fmt::Display};

use nautilus_indicators::indicator::Indicator;
use nautilus_model::data::Bar;

// #region new
#[derive(Debug)]
pub struct InternalBarStrength {
    pub period: usize,
    pub value: f64,
    pub initialized: bool,
    has_inputs: bool,
    window: VecDeque<f64>,
    sum: f64,
}

impl InternalBarStrength {
    /// Creates a new indicator.
    ///
    /// # Panics
    ///
    /// Panics if `period` is zero.
    #[must_use]
    pub fn new(period: usize) -> Self {
        assert!(period > 0, "`period` must be positive, was {period}");
        Self {
            period,
            value: 0.0,
            initialized: false,
            has_inputs: false,
            window: VecDeque::with_capacity(period),
            sum: 0.0,
        }
    }
// #endregion new

    // #region update
    /// Updates the indicator with one bar's high, low and close.
    ///
    /// Invalid bars (non-finite, `high < low`, close outside the range) and
    /// zero-range bars (`high == low`) are ignored.
    pub fn update_raw(&mut self, high: f64, low: f64, close: f64) {
        if !(high.is_finite() && low.is_finite() && close.is_finite()) {
            return;
        }
        if high < low || close < low || close > high {
            return;
        }
        let range = high - low;
        if range == 0.0 {
            return; // no range, no position within it
        }

        let ibs = (close - low) / range;
        self.has_inputs = true;

        if self.window.len() == self.period {
            if let Some(oldest) = self.window.pop_front() {
                self.sum -= oldest;
            }
        }
        self.window.push_back(ibs);
        self.sum += ibs;

        if self.window.len() == self.period {
            self.initialized = true;
        }
        if self.initialized {
            self.value = self.sum / self.period as f64;
        }
    }
    // #endregion update
}

impl Display for InternalBarStrength {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}({})", self.name(), self.period)
    }
}

// #region indicator
impl Indicator for InternalBarStrength {
    fn name(&self) -> String {
        "InternalBarStrength".to_string()
    }

    fn has_inputs(&self) -> bool {
        self.has_inputs
    }

    fn initialized(&self) -> bool {
        self.initialized
    }

    fn handle_bar(&mut self, bar: &Bar) {
        self.update_raw(bar.high.as_f64(), bar.low.as_f64(), bar.close.as_f64());
    }

    fn reset(&mut self) {
        self.window.clear();
        self.sum = 0.0;
        self.value = 0.0;
        self.has_inputs = false;
        self.initialized = false;
    }
}
// #endregion indicator

#[cfg(test)]
mod tests {
    use nautilus_indicators::{indicator::Indicator, testing::assert_approx_equal};
    use nautilus_model::{
        data::{Bar, BarType},
        types::{Price, Quantity},
    };
    use proptest::prelude::*;
    use rstest::{fixture, rstest};

    use super::InternalBarStrength;

    // #region fixture
    #[fixture]
    fn ibs3() -> InternalBarStrength {
        InternalBarStrength::new(3)
    }

    // Hand-computed IBS: (11-8)/4 = 0.75, (8.5-8)/2 = 0.25, (16-12)/8 = 0.5, (1-1)/4 = 0.0
    const BARS: [(f64, f64, f64); 4] = [
        (12.0, 8.0, 11.0),
        (10.0, 8.0, 8.5),
        (20.0, 12.0, 16.0),
        (5.0, 1.0, 1.0),
    ];
    // #endregion fixture

    #[rstest]
    fn test_new(ibs3: InternalBarStrength) {
        assert_eq!(ibs3.to_string(), "InternalBarStrength(3)");
        assert_eq!(ibs3.value, 0.0);
        assert!(!ibs3.has_inputs());
        assert!(!ibs3.initialized());
    }

    #[rstest]
    #[should_panic(expected = "`period` must be positive")]
    fn test_new_with_zero_period_panics() {
        let _ = InternalBarStrength::new(0);
    }

    // #region values
    #[rstest]
    fn test_value_is_zero_until_initialized(mut ibs3: InternalBarStrength) {
        let (h, l, c) = BARS[0];
        ibs3.update_raw(h, l, c);
        let (h, l, c) = BARS[1];
        ibs3.update_raw(h, l, c);
        assert!(ibs3.has_inputs());
        assert!(!ibs3.initialized());
        assert_eq!(ibs3.value, 0.0);
    }

    #[rstest]
    #[case(3, 0.5)] // (0.75 + 0.25 + 0.5) / 3
    #[case(4, 0.25)] // window slides: (0.25 + 0.5 + 0.0) / 3
    fn test_hand_computed_values(
        mut ibs3: InternalBarStrength,
        #[case] n_bars: usize,
        #[case] expected: f64,
    ) {
        for &(h, l, c) in &BARS[..n_bars] {
            ibs3.update_raw(h, l, c);
        }
        assert!(ibs3.initialized());
        assert_approx_equal(ibs3.value, expected);
    }

    #[rstest]
    fn test_zero_range_bar_is_skipped(mut ibs3: InternalBarStrength) {
        for &(h, l, c) in &BARS[..3] {
            ibs3.update_raw(h, l, c);
        }
        ibs3.update_raw(7.0, 7.0, 7.0);
        assert_approx_equal(ibs3.value, 0.5);
        assert_eq!(ibs3.window.len(), 3);
    }
    // #endregion values

    // #region invalid
    #[rstest]
    #[case(f64::NAN, 1.0, 1.0)]
    #[case(2.0, f64::INFINITY, 1.0)]
    #[case(1.0, 2.0, 1.5)] // high < low
    #[case(2.0, 1.0, 3.0)] // close above high
    fn test_invalid_input_is_ignored(
        mut ibs3: InternalBarStrength,
        #[case] high: f64,
        #[case] low: f64,
        #[case] close: f64,
    ) {
        ibs3.update_raw(high, low, close);
        assert!(!ibs3.has_inputs());
        assert!(ibs3.window.is_empty());
    }
    // #endregion invalid

    // #region handle-bar
    #[rstest]
    fn test_handle_bar(mut ibs3: InternalBarStrength) {
        let bar_type = BarType::from("ETHUSDT.BINANCE-250-TICK-LAST-INTERNAL");
        let bar = Bar::new(
            bar_type,
            Price::from("10.00"),
            Price::from("12.00"),
            Price::from("8.00"),
            Price::from("11.00"),
            Quantity::from("1.00000"),
            0.into(),
            0.into(),
        );
        for _ in 0..3 {
            ibs3.handle_bar(&bar);
        }
        assert!(ibs3.initialized());
        assert_eq!(ibs3.value, 0.75);
    }
    // #endregion handle-bar

    #[rstest]
    fn test_reset_then_replay_gives_same_value(mut ibs3: InternalBarStrength) {
        for &(h, l, c) in &BARS {
            ibs3.update_raw(h, l, c);
        }
        let first = ibs3.value;

        ibs3.reset();
        assert_eq!(ibs3.value, 0.0);
        assert!(!ibs3.has_inputs());
        assert!(!ibs3.initialized());

        for &(h, l, c) in &BARS {
            ibs3.update_raw(h, l, c);
        }
        assert_eq!(ibs3.value, first);
    }

    // #region proptest
    fn valid_bar() -> impl Strategy<Value = (f64, f64, f64)> {
        (1.0..1000.0f64, 0.01..50.0f64, 0.0..=1.0f64)
            .prop_map(|(low, range, pos)| (low + range, low, low + range * pos))
    }

    proptest! {
        #[test]
        fn prop_matches_naive_mean_of_last_period(
            period in 1usize..20,
            bars in prop::collection::vec(valid_bar(), 0..200),
        ) {
            let mut ind = InternalBarStrength::new(period);
            let mut all = Vec::new();
            for &(h, l, c) in &bars {
                ind.update_raw(h, l, c);
                if h > l {
                    all.push((c - l) / (h - l));
                }
            }
            prop_assert_eq!(ind.initialized, all.len() >= period);
            if all.len() >= period {
                let tail = &all[all.len() - period..];
                let naive = tail.iter().sum::<f64>() / period as f64;
                prop_assert!((ind.value - naive).abs() < 1e-9);
                prop_assert!((0.0..=1.0).contains(&ind.value));
            } else {
                prop_assert_eq!(ind.value, 0.0);
            }
        }
    }
    // #endregion proptest
}
