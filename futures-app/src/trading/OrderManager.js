/**
 * OrderManager
 * ────────────
 * Manages the lifecycle of simulated NQ futures bracket orders.
 *
 * Entry flow:
 *   enter(side, price, contracts, simTime)
 *     → creates Entry + Stop + TP1 + TP2 orders
 *
 * Price feed:
 *   onTick(price, simTime)
 *     → checks fills for pending orders
 *     → triggers BE move when +10 pts in favour
 *     → fires onFill / onUpdate callbacks
 *
 * Bracket anatomy (long example, entry @ 20000):
 *   Stop:  20000 - 10   = 19990  (40 ticks)
 *   TP1:   20000 + 15   = 20015  (close floor(contracts/2) lots)
 *   TP2:   20000 + 25   = 20025  (close remainder)
 *   BE trigger: price ≥ 20010 → move stop to 20000
 *
 * P&L is in USD (1 point = $20, 1 tick = $5).
 */

import { TRADING_RULES, NQ_SPECS } from '../constants.js';

let _nextId = 1;

export class OrderManager {
  constructor({ onTradeClose, onUpdate } = {}) {
    this.positions     = [];   // active bracket positions
    this.closedTrades  = [];   // completed trade records
    this.onTradeClose  = onTradeClose ?? (() => {});
    this.onUpdate      = onUpdate      ?? (() => {});
  }

  // ─── Entry ────────────────────────────────────────────────────────────────

  /**
   * Open a new bracket position.
   *
   * @param {'long'|'short'} side
   * @param {number} price       – entry fill price (market order)
   * @param {number} contracts   – total contracts (1-3)
   * @param {Date}   simTime
   * @returns {object} position
   */
  enter(side, price, contracts, simTime) {
    const dir    = side === 'long' ? 1 : -1;
    const stop   = parseFloat((price - dir * TRADING_RULES.stopLossPoints).toFixed(2));
    const tp1    = parseFloat((price + dir * TRADING_RULES.tp1Points).toFixed(2));
    const tp2    = parseFloat((price + dir * TRADING_RULES.tp2Points).toFixed(2));
    const tp1Qty = Math.floor(contracts * TRADING_RULES.tp1CloseRatio); // floor of 50%
    const tp2Qty = contracts - tp1Qty;

    const pos = {
      id:          _nextId++,
      side,
      entryPrice:  price,
      entryTime:   simTime,
      contracts,
      remaining:   contracts,
      stopPrice:   stop,
      tp1Price:    tp1,
      tp2Price:    tp2,
      tp1Qty,
      tp2Qty,
      tp1Hit:      false,
      tp2Hit:      false,
      beTriggered: false,     // has break-even been applied?
      realisedPnl: 0,
      status:      'open',    // 'open' | 'closed'
      exitParts:   [],        // partial fills record
    };

    this.positions.push(pos);
    this.onUpdate();
    return pos;
  }

  // ─── Tick Processing ──────────────────────────────────────────────────────

  /**
   * Feed the latest price to the order manager.
   * Checks all open positions for fills, BE triggers, etc.
   *
   * @param {number} price
   * @param {Date}   simTime
   */
  onTick(price, simTime) {
    let changed = false;

    for (const pos of this.positions) {
      if (pos.status !== 'open') continue;

      const dir = pos.side === 'long' ? 1 : -1;

      // ── TP1 fill ──────────────────────────────────────────────────────────
      if (!pos.tp1Hit && this._crossed(price, pos.tp1Price, pos.side)) {
        const pnl = this._pnl(pos.entryPrice, pos.tp1Price, pos.tp1Qty);
        pos.remaining   -= pos.tp1Qty;
        pos.realisedPnl += pnl;
        pos.tp1Hit       = true;
        pos.exitParts.push({ time: simTime, price: pos.tp1Price, qty: pos.tp1Qty, pnl, reason: 'TP1' });

        // Auto BE: immediately move stop to entry when TP1 fills
        pos.stopPrice   = pos.entryPrice;
        pos.beTriggered = true;
        changed = true;
      }

      // ── TP2 fill ──────────────────────────────────────────────────────────
      if (pos.tp1Hit && !pos.tp2Hit && this._crossed(price, pos.tp2Price, pos.side)) {
        const pnl = this._pnl(pos.entryPrice, pos.tp2Price, pos.tp2Qty);
        pos.remaining   -= pos.tp2Qty;
        pos.realisedPnl += pnl;
        pos.tp2Hit       = true;
        pos.status       = 'closed';
        pos.exitParts.push({ time: simTime, price: pos.tp2Price, qty: pos.tp2Qty, pnl, reason: 'TP2' });
        changed = true;
        this._closeTrade(pos, simTime);
        continue;
      }

      // ── BE trigger (if TP1 not yet hit) ───────────────────────────────────
      // When price moves +10 pts in favour, move stop to entry (BE).
      if (!pos.beTriggered && !pos.tp1Hit) {
        const profit = dir * (price - pos.entryPrice);
        if (profit >= TRADING_RULES.breakEvenTriggerPoints) {
          pos.stopPrice   = pos.entryPrice;
          pos.beTriggered = true;
          changed = true;
        }
      }

      // ── Stop fill ─────────────────────────────────────────────────────────
      if (this._crossedStop(price, pos.stopPrice, pos.side)) {
        const stopQty = pos.remaining;
        const pnl     = this._pnl(pos.entryPrice, pos.stopPrice, stopQty);
        pos.remaining   -= stopQty;
        pos.realisedPnl += pnl;
        pos.status       = 'closed';
        pos.exitParts.push({ time: simTime, price: pos.stopPrice, qty: stopQty, pnl, reason: 'STOP' });
        changed = true;
        this._closeTrade(pos, simTime);
      }
    }

    if (changed) this.onUpdate();
  }

  // ─── Manual Close / Flatten ───────────────────────────────────────────────

  /**
   * Flatten all open positions at market (emergency close).
   */
  flattenAll(price, simTime) {
    for (const pos of this.positions) {
      if (pos.status !== 'open') continue;
      const pnl = this._pnl(pos.entryPrice, price, pos.remaining);
      pos.realisedPnl += pnl;
      pos.remaining    = 0;
      pos.status       = 'closed';
      pos.exitParts.push({ time: simTime, price, qty: pos.remaining, pnl, reason: 'MANUAL' });
      this._closeTrade(pos, simTime);
    }
    this.onUpdate();
  }

  // ─── Helpers ─────────────────────────────────────────────────────────────

  /**
   * P&L in USD for qty contracts between two prices.
   * 1 point = $20 for E-mini NQ.
   */
  _pnl(entry, exit, qty) {
    const dir = exit > entry ? 1 : -1; // actual direction from prices
    return parseFloat(((exit - entry) * NQ_SPECS.pointValue * qty).toFixed(2));
  }

  /** Long: price >= target; Short: price <= target */
  _crossed(price, target, side) {
    return side === 'long' ? price >= target : price <= target;
  }

  /** Stop: Long triggered when price <= stop; Short when price >= stop */
  _crossedStop(price, stop, side) {
    return side === 'long' ? price <= stop : price >= stop;
  }

  _closeTrade(pos, simTime) {
    pos.closeTime      = simTime;
    pos.totalPnl       = pos.realisedPnl;
    pos.holdTimeMin    = Math.round((simTime - pos.entryTime) / 60000);
    this.closedTrades.push(pos);
    this.onTradeClose(pos);
  }

  // ─── Stats ────────────────────────────────────────────────────────────────

  get openPosition() {
    return this.positions.find(p => p.status === 'open') ?? null;
  }

  get stats() {
    const trades  = this.closedTrades;
    const wins    = trades.filter(t => t.totalPnl > 0);
    const losses  = trades.filter(t => t.totalPnl <= 0);
    const totalPnl = trades.reduce((s, t) => s + t.totalPnl, 0);
    const grossWin  = wins.reduce((s, t) => s + t.totalPnl, 0);
    const grossLoss = Math.abs(losses.reduce((s, t) => s + t.totalPnl, 0));
    const avgR      = trades.length > 0
      ? (totalPnl / trades.length / (TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue)).toFixed(2)
      : 0;

    // Consecutive losses (current streak)
    let consLoss = 0;
    for (let i = trades.length - 1; i >= 0; i--) {
      if (trades[i].totalPnl < 0) consLoss++;
      else break;
    }

    return {
      total:         trades.length,
      wins:          wins.length,
      losses:        losses.length,
      winRate:       trades.length > 0 ? ((wins.length / trades.length) * 100).toFixed(1) : '0.0',
      totalPnl:      totalPnl.toFixed(2),
      profitFactor:  grossLoss > 0 ? (grossWin / grossLoss).toFixed(2) : '∞',
      avgR,
      consecutiveLoss: consLoss,
    };
  }
}
