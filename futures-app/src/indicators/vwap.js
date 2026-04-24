/**
 * VWAP (Volume-Weighted Average Price) — session-anchored
 *
 * The BarBuilder already accumulates session PV & volume sums, so this
 * module just provides helper functions used by the chart overlay.
 *
 * For the chart we build a series of { time, value } points — one per
 * completed 5m bar — from the running session totals.
 */

/**
 * Compute a VWAP series from 5m bars.
 *
 * Each bar must have: { time, open, high, low, close, volume }
 * Typical price = (high + low + close) / 3
 *
 * @param {object[]} bars – 5m OHLCV bars since session open
 * @returns {{ time: number, value: number }[]}
 */
export function computeVwapSeries(bars) {
  let cumulPV  = 0;
  let cumulVol = 0;
  const series = [];

  for (const bar of bars) {
    const typicalPrice = (bar.high + bar.low + bar.close) / 3;
    cumulPV  += typicalPrice * bar.volume;
    cumulVol += bar.volume;
    if (cumulVol > 0) {
      series.push({ time: bar.time, value: parseFloat((cumulPV / cumulVol).toFixed(2)) });
    }
  }
  return series;
}

/**
 * Current VWAP scalar (the last value of the series).
 *
 * @param {object[]} bars
 * @returns {number | null}
 */
export function currentVwap(bars) {
  const series = computeVwapSeries(bars);
  return series.length > 0 ? series[series.length - 1].value : null;
}
