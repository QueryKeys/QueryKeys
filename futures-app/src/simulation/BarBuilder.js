/**
 * BarBuilder
 * ──────────
 * Aggregates raw ticks into OHLCV candlestick bars at multiple timeframes.
 *
 * Supported timeframes: 1-minute ("1m") and 5-minute ("5m").
 *
 * Bar anatomy:
 *   { time, open, high, low, close, volume, vwapNumerator, vwapDenominator }
 *
 * vwapNumerator / vwapDenominator accumulate across the *session* (not per bar)
 * so the session VWAP can be computed at any tick:
 *   VWAP = sum(price × vol) / sum(vol)  from session open → now
 *
 * Usage:
 *   const bb = new BarBuilder();
 *   bb.addTick({ price, volume, time });  // returns { bar1m, bar5m, sessionVwap }
 */

export class BarBuilder {
  constructor() {
    // Keyed by timeframe string ("1m", "5m")
    this._current = {};     // current open bar per TF
    this._history = {};     // completed bars per TF

    // Session VWAP accumulators (reset at session open)
    this._sessionPV  = 0; // Σ price × volume
    this._sessionVol = 0; // Σ volume
    this._sessionDate = null; // YYYY-MM-DD string of current session

    const tfs = ['1m', '5m'];
    for (const tf of tfs) {
      this._current[tf] = null;
      this._history[tf] = [];
    }
  }

  /**
   * Feed one tick into the builder.
   *
   * @param {{ price: number, volume: number, time: Date }} tick
   * @returns {{
   *   bars1m: object[],   – full history + current 1m bar
   *   bars5m: object[],   – full history + current 5m bar
   *   sessionVwap: number
   * }}
   */
  addTick({ price, volume, time }) {
    this._updateSessionVwap(price, volume, time);

    this._processTick('1m', price, volume, time, 1);
    this._processTick('5m', price, volume, time, 5);

    const sessionVwap = this._sessionVol > 0
      ? this._sessionPV / this._sessionVol
      : price;

    return {
      bars1m: this._snapshot('1m'),
      bars5m: this._snapshot('5m'),
      sessionVwap,
    };
  }

  /** Access historical + current bars for a timeframe. */
  getBars(tf) {
    return this._snapshot(tf);
  }

  /** Reset all history (e.g., new session). */
  reset() {
    for (const tf of ['1m', '5m']) {
      this._current[tf] = null;
      this._history[tf] = [];
    }
    this._sessionPV  = 0;
    this._sessionVol = 0;
    this._sessionDate = null;
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  /**
   * Session VWAP resets at 9:30 AM EST (new trading session).
   * We detect a new session by comparing the date of the tick.
   */
  _updateSessionVwap(price, volume, time) {
    // Build a date string in local (simulation) time
    const dateStr = `${time.getFullYear()}-${time.getMonth()}-${time.getDate()}`;
    const h = time.getHours(), m = time.getMinutes();
    const isSessionOpen = h === 9 && m === 30; // exactly 9:30 start

    // Reset if new day or exactly at session open
    if (dateStr !== this._sessionDate || isSessionOpen) {
      if (isSessionOpen || this._sessionDate === null) {
        this._sessionPV   = 0;
        this._sessionVol  = 0;
        this._sessionDate = dateStr;
      }
    }

    this._sessionPV  += price * volume;
    this._sessionVol += volume;
  }

  /**
   * Update the open bar for the given timeframe with one tick.
   * Completes and rotates the bar when the time bucket changes.
   *
   * @param {string} tf         – "1m" | "5m"
   * @param {number} price
   * @param {number} volume
   * @param {Date}   time
   * @param {number} minutes    – bar duration in minutes (1 or 5)
   */
  _processTick(tf, price, volume, time, minutes) {
    const bucket = this._bucket(time, minutes);

    if (!this._current[tf]) {
      // No open bar — start one
      this._current[tf] = this._newBar(price, volume, bucket);
      return;
    }

    if (this._current[tf].bucket !== bucket) {
      // Time crossed a bar boundary → close current, push to history
      this._history[tf].push(this._current[tf]);
      // Cap history to last 500 bars to avoid unbounded memory
      if (this._history[tf].length > 500) this._history[tf].shift();
      this._current[tf] = this._newBar(price, volume, bucket);
    } else {
      // Same bar — update OHLCV
      const bar = this._current[tf];
      bar.high   = Math.max(bar.high, price);
      bar.low    = Math.min(bar.low, price);
      bar.close  = price;
      bar.volume += volume;
    }
  }

  /** Create a fresh bar object. */
  _newBar(price, volume, bucket) {
    return {
      bucket,
      time:   bucket,   // Unix seconds (for Lightweight Charts)
      open:   price,
      high:   price,
      low:    price,
      close:  price,
      volume,
    };
  }

  /**
   * Compute the "bucket" timestamp (Unix seconds) that identifies which
   * bar a tick belongs to, aligned to the minute boundary.
   *
   * E.g. for 5m bars: 9:31, 9:32, 9:33, 9:34 all → 9:30 bucket.
   */
  _bucket(time, minutes) {
    const ms       = time.getTime();
    const barMs    = minutes * 60 * 1000;
    const floored  = Math.floor(ms / barMs) * barMs;
    return Math.floor(floored / 1000); // Unix seconds
  }

  /**
   * Return a combined array of [completed bars..., current bar] for a TF.
   * The current bar is included so the chart always shows the live candle.
   */
  _snapshot(tf) {
    const hist = this._history[tf];
    const cur  = this._current[tf];
    return cur ? [...hist, cur] : [...hist];
  }
}
