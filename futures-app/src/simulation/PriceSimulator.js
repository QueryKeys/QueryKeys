/**
 * PriceSimulator
 * ──────────────
 * Generates synthetic NQ futures tick data using a mean-reverting random walk
 * that mimics real intraday microstructure:
 *
 *   • Geometric Brownian Motion base with an Ornstein-Uhlenbeck drift term
 *   • Tick size enforced (0.25 pts)
 *   • Volatility is time-of-day dependent (open & close busier)
 *   • Short-term trend episodes injected randomly (momentum)
 *   • Each tick carries a simulated trade volume
 *
 * Simulation time is managed externally via `tick()`. The caller provides the
 * current simulation timestamp so the simulator stays stateless about the clock.
 */

import { NQ_SPECS } from '../constants.js';

const TICK = NQ_SPECS.tickSize; // 0.25

export class PriceSimulator {
  /**
   * @param {object} opts
   * @param {number} opts.startPrice   – starting mid price (default 20000)
   * @param {number} opts.seed         – optional deterministic seed (unused in
   *                                     this impl; extend if needed)
   */
  constructor(opts = {}) {
    this.price      = opts.startPrice ?? NQ_SPECS.startPrice;
    this.basePrice  = this.price; // long-run mean for Ornstein-Uhlenbeck

    // Trend state: direction (-1 | 0 | 1) and remaining ticks
    this._trendDir      = 0;
    this._trendTicks    = 0;

    // Listeners called on every tick: fn({ price, bid, ask, volume, time })
    this._listeners = [];
  }

  // ─── Public API ──────────────────────────────────────────────────────────

  /** Subscribe to tick events. Returns unsubscribe function. */
  subscribe(fn) {
    this._listeners.push(fn);
    return () => { this._listeners = this._listeners.filter(f => f !== fn); };
  }

  /**
   * Generate a single tick at the given simulation timestamp.
   *
   * @param {Date} simTime – current simulation time (EST)
   * @returns {{ price, bid, ask, volume, time }}
   */
  tick(simTime) {
    const vol = this._volatilityFactor(simTime);

    // ── Ornstein-Uhlenbeck mean reversion ──────────────────────────────────
    // Pulls price toward basePrice; prevents unlimited drift over long sims.
    const theta = 0.0002;  // reversion speed (gentle)
    const reversion = theta * (this.basePrice - this.price);

    // ── Trend / momentum overlay ───────────────────────────────────────────
    if (this._trendTicks <= 0) {
      // Randomly start a new trend episode (~5% chance each tick)
      if (Math.random() < 0.05) {
        this._trendDir   = Math.random() < 0.5 ? 1 : -1;
        this._trendTicks = Math.floor(20 + Math.random() * 60); // 20-80 ticks
      } else {
        this._trendDir = 0;
      }
    } else {
      this._trendTicks--;
    }
    const trendBias = this._trendDir * 0.08 * vol; // small directional nudge

    // ── GBM noise ──────────────────────────────────────────────────────────
    const sigma  = 0.4 * vol;           // base std per tick in points
    const noise  = this._randn() * sigma;

    // Combine and snap to tick grid
    const rawMove = reversion + trendBias + noise;
    const ticks   = Math.round(rawMove / TICK);
    this.price    = Math.max(1, this.price + ticks * TICK);

    // ── Bid / Ask spread (always 1 tick for NQ) ────────────────────────────
    const bid = this.price - TICK;
    const ask = this.price;

    // ── Simulated volume (log-normal, scaled by volatility) ────────────────
    const volume = Math.max(1, Math.round(Math.exp(2.5 + Math.random() * 1.5) * vol));

    const tickData = { price: this.price, bid, ask, volume, time: simTime };
    this._emit(tickData);
    return tickData;
  }

  // ─── Private helpers ─────────────────────────────────────────────────────

  /**
   * Volatility multiplier by time of day.
   * Open (9:30-10:00) and close (15:30-16:00) get 2× base vol.
   * Midday lull (12:00-13:30) gets 0.6× base vol.
   */
  _volatilityFactor(simTime) {
    const h = simTime.getHours();
    const m = simTime.getMinutes();
    const minuteOfDay = h * 60 + m;
    const open  = 9 * 60 + 30;   // 570
    const close = 15 * 60 + 30;  // 930

    if (minuteOfDay < open + 30 || minuteOfDay > close) return 2.0; // open/close surge
    if (minuteOfDay >= 12 * 60 && minuteOfDay < 13 * 60 + 30) return 0.6; // lunch lull
    return 1.0;
  }

  /** Box-Muller transform → standard normal sample */
  _randn() {
    let u = 0, v = 0;
    while (u === 0) u = Math.random();
    while (v === 0) v = Math.random();
    return Math.sqrt(-2.0 * Math.log(u)) * Math.cos(2.0 * Math.PI * v);
  }

  _emit(data) {
    for (const fn of this._listeners) fn(data);
  }
}
