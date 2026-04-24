/**
 * BOS – Break of Structure Detection
 * ────────────────────────────────────
 * Algorithm overview:
 *
 *  1. SWING HIGH: bar[i].high is higher than the `lookback` bars on both sides.
 *  2. SWING LOW : bar[i].low  is lower  than the `lookback` bars on both sides.
 *  3. BULLISH BOS: a candle *closes* above the most recent unbroken swing high.
 *     → This signals higher-high structure (uptrend continuation / reversal).
 *  4. BEARISH BOS: a candle *closes* below the most recent unbroken swing low.
 *     → This signals lower-low structure (downtrend continuation / reversal).
 *
 * Each BOS event generates a horizontal ray drawn at the breakout price level.
 * Once a level is broken it is marked as "broken" and removed from tracking.
 *
 * The detector is incremental — call `update(bars)` after each new bar close
 * and it will only reprocess the last `lookback * 2 + 1` bars.
 *
 * Returns:
 *   {
 *     swingHighs: [{ barIndex, price, time, broken }],
 *     swingLows:  [{ barIndex, price, time, broken }],
 *     bosEvents:  [{ type: 'bullish'|'bearish', price, time, barIndex }],
 *   }
 */

/**
 * Full recompute on the entire bar array.
 * Efficient enough for typical session lengths (~80 5m bars).
 *
 * @param {object[]} bars        – 5m OHLCV bars
 * @param {number}   lookback    – bars each side to confirm swing (default 5)
 * @returns {{ swingHighs, swingLows, bosEvents }}
 */
export function detectBOS(bars, lookback = 5) {
  const swingHighs = [];
  const swingLows  = [];
  const bosEvents  = [];

  // ── Pass 1: identify all swing highs and lows ──────────────────────────────
  for (let i = lookback; i < bars.length - lookback; i++) {
    const bar = bars[i];

    // Swing high: bar[i].high is strictly greater than all neighbours
    const isSwingHigh = bars.slice(i - lookback, i).every(b => b.high < bar.high)
                     && bars.slice(i + 1, i + lookback + 1).every(b => b.high < bar.high);

    const isSwingLow  = bars.slice(i - lookback, i).every(b => b.low > bar.low)
                     && bars.slice(i + 1, i + lookback + 1).every(b => b.low > bar.low);

    if (isSwingHigh) swingHighs.push({ barIndex: i, price: bar.high, time: bar.time, broken: false });
    if (isSwingLow)  swingLows.push ({ barIndex: i, price: bar.low,  time: bar.time, broken: false });
  }

  // ── Pass 2: scan for BOS events (close beyond an unbroken swing) ───────────
  // We track the *most recent* unbroken swing high/low as the "key level".
  // A BOS occurs when a later candle's close exceeds that level.

  let lastUnbrokenHigh = null; // most recent swing high not yet broken
  let lastUnbrokenLow  = null;

  let hIdx = 0; // pointer into swingHighs
  let lIdx = 0; // pointer into swingLows

  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i];

    // Advance pointer to include swing points that have been confirmed by now
    // (swing at position j is confirmed once we reach j + lookback)
    while (hIdx < swingHighs.length && swingHighs[hIdx].barIndex + lookback <= i) {
      lastUnbrokenHigh = swingHighs[hIdx];
      hIdx++;
    }
    while (lIdx < swingLows.length && swingLows[lIdx].barIndex + lookback <= i) {
      lastUnbrokenLow = swingLows[lIdx];
      lIdx++;
    }

    // Bullish BOS: close above the most recent swing high
    if (lastUnbrokenHigh && !lastUnbrokenHigh.broken && bar.close > lastUnbrokenHigh.price) {
      bosEvents.push({
        type:     'bullish',
        price:    lastUnbrokenHigh.price,
        time:     bar.time,
        barIndex: i,
      });
      lastUnbrokenHigh.broken = true;
      lastUnbrokenHigh = null; // reset; next swing high becomes the key level
    }

    // Bearish BOS: close below the most recent swing low
    if (lastUnbrokenLow && !lastUnbrokenLow.broken && bar.close < lastUnbrokenLow.price) {
      bosEvents.push({
        type:     'bearish',
        price:    lastUnbrokenLow.price,
        time:     bar.time,
        barIndex: i,
      });
      lastUnbrokenLow.broken = true;
      lastUnbrokenLow = null;
    }
  }

  return { swingHighs, swingLows, bosEvents };
}

/**
 * Lightweight incremental wrapper.
 * Keeps previous results and only re-runs when bar count changes.
 */
export class BosDetector {
  constructor(lookback = 5) {
    this.lookback   = lookback;
    this._lastCount = 0;
    this._result    = { swingHighs: [], swingLows: [], bosEvents: [] };
  }

  update(bars) {
    // Always recompute — bars array is small enough (≤500) for full scan
    this._result    = detectBOS(bars, this.lookback);
    this._lastCount = bars.length;
    return this._result;
  }

  get result() { return this._result; }
}
