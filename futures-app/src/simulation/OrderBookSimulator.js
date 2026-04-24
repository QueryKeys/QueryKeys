/**
 * OrderBookSimulator
 * ──────────────────
 * Generates a realistic Level-2 (Depth of Market) order book for NQ futures.
 *
 * Design:
 *   • 20 bid levels and 20 ask levels, each spaced 1 tick (0.25 pts) apart
 *   • Size at each level drawn from a power-law distribution:
 *       deeper levels → larger resting size (institutional layering)
 *   • Random refreshes: ~30% of levels change each tick (partial book update)
 *   • "Iceberg" large orders placed randomly at round-number price levels
 *     (e.g., 20000, 20025, etc.) and flagged for heatmap highlighting
 *   • Cumulative bid/ask depth arrays exposed for the ladder/depth chart
 */

import { NQ_SPECS } from '../constants.js';

const TICK   = NQ_SPECS.tickSize;
const LEVELS = 20; // depth levels each side

export class OrderBookSimulator {
  constructor() {
    this.bids = []; // [{ price, size, isIceberg }]  index 0 = best bid
    this.asks = []; // [{ price, size, isIceberg }]  index 0 = best ask
    this._lastMid = NQ_SPECS.startPrice;
  }

  /**
   * Update the book around a new mid price.
   * Called once per simulated tick.
   *
   * @param {number} midPrice – current trade price
   * @returns {{ bids, asks, cumulativeBids, cumulativeAsks }}
   */
  update(midPrice) {
    const bestBid = midPrice - TICK;
    const bestAsk = midPrice;

    // Full rebuild only when mid price shifts; otherwise partial update.
    const priceShifted = Math.abs(midPrice - this._lastMid) >= TICK;
    this._lastMid = midPrice;

    if (priceShifted || this.bids.length === 0) {
      this._rebuild(bestBid, bestAsk);
    } else {
      this._partialUpdate(bestBid, bestAsk);
    }

    return {
      bids: this.bids,
      asks: this.asks,
      cumulativeBids: this._cumulative(this.bids),
      cumulativeAsks: this._cumulative(this.asks),
    };
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  /** Full book rebuild from current best bid/ask. */
  _rebuild(bestBid, bestAsk) {
    this.bids = [];
    this.asks = [];
    for (let i = 0; i < LEVELS; i++) {
      const bidPrice = parseFloat((bestBid - i * TICK).toFixed(2));
      const askPrice = parseFloat((bestAsk + i * TICK).toFixed(2));
      this.bids.push({ price: bidPrice, size: this._sampleSize(i), isIceberg: this._isRound(bidPrice) && Math.random() < 0.15 });
      this.asks.push({ price: askPrice, size: this._sampleSize(i), isIceberg: this._isRound(askPrice) && Math.random() < 0.15 });
    }
  }

  /**
   * Partial update: slide the book to new best prices, then randomly
   * refresh ~30% of levels to simulate market participants adding/removing.
   */
  _partialUpdate(bestBid, bestAsk) {
    // Slide bid side
    for (let i = 0; i < LEVELS; i++) {
      this.bids[i].price = parseFloat((bestBid - i * TICK).toFixed(2));
      if (Math.random() < 0.30) {
        this.bids[i].size = this._sampleSize(i);
        this.bids[i].isIceberg = this._isRound(this.bids[i].price) && Math.random() < 0.12;
      }
    }
    // Slide ask side
    for (let i = 0; i < LEVELS; i++) {
      this.asks[i].price = parseFloat((bestAsk + i * TICK).toFixed(2));
      if (Math.random() < 0.30) {
        this.asks[i].size = this._sampleSize(i);
        this.asks[i].isIceberg = this._isRound(this.asks[i].price) && Math.random() < 0.12;
      }
    }
  }

  /**
   * Level-size distribution: power-law with random noise.
   * Deeper levels (higher index) tend to be larger.
   * Icebergs can be 150-400 contracts.
   *
   * @param {number} levelIndex – 0 = best bid/ask
   */
  _sampleSize(levelIndex) {
    const base = 10 + levelIndex * 8;          // scales from ~10 to ~162
    const noise = (Math.random() - 0.5) * base; // ±50% noise
    const size  = Math.max(1, Math.round(base + noise));
    // Occasionally inject an iceberg (100-400 lots) at deeper levels
    if (levelIndex >= 3 && Math.random() < 0.04) {
      return Math.floor(100 + Math.random() * 300);
    }
    return size;
  }

  /** Round price levels (multiples of 25 pts) attract institutional orders. */
  _isRound(price) {
    return Math.round(price) % 25 === 0;
  }

  /** Convert [{ price, size }] to cumulative depth array. */
  _cumulative(levels) {
    const result = [];
    let cum = 0;
    for (const lvl of levels) {
      cum += lvl.size;
      result.push({ price: lvl.price, size: lvl.size, cumSize: cum });
    }
    return result;
  }
}
