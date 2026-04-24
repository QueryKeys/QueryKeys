/**
 * RiskManager
 * ───────────
 * Enforces the Apex Trader Funding 50K trailing-drawdown account rules
 * and all intraday trading limits.
 *
 * ── Apex Trailing Threshold Logic ──────────────────────────────────────────
 *
 *   Starting balance:   $50,000
 *   Trailing drawdown:  $2,500 below the *peak* balance
 *   Lock level:         $52,600  (once reached, trailing stops)
 *
 *   Phase 1 (balance < $52,600):
 *     floor = peakBalance - $2,500
 *     e.g. peak = $51,000 → floor = $48,500
 *
 *   Phase 2 (balance ever reaches $52,600):
 *     floor is permanently locked at $50,100 ($52,600 - $2,500)
 *     The floor can never go back down even if balance drops.
 *
 *   Account is blown if balance ≤ floor at any point.
 *
 * ── Intraday Limits ─────────────────────────────────────────────────────────
 *   • Daily loss limit:       -$600
 *   • Max trades per day:     3
 *   • Max consecutive losses: 2 → lock for the rest of day
 */

import { ACCOUNT_PARAMS, TRADING_RULES, NQ_SPECS } from '../constants.js';

export class RiskManager {
  constructor(savedState = null) {
    if (savedState) {
      Object.assign(this, savedState);
    } else {
      this._reset();
    }
  }

  // ─── State ────────────────────────────────────────────────────────────────

  _reset() {
    this.balance         = ACCOUNT_PARAMS.startingBalance;        // current P&L-adjusted balance
    this.peakBalance     = ACCOUNT_PARAMS.startingBalance;        // highest balance seen
    this.locked          = false;   // true once peak ≥ lockLevel
    this.floor           = ACCOUNT_PARAMS.startingBalance - ACCOUNT_PARAMS.trailingDrawdown; // $47,500

    // Daily trackers (reset each session open)
    this.dayPnl          = 0;
    this.dayTradeCount   = 0;
    this.consecutiveLoss = 0;
    this.tradingLocked   = false;   // locked for the rest of the trading day
    this.lockReason      = '';

    // Session date for detecting rollover (YYYY-MM-DD string)
    this._sessionDate    = null;
  }

  // ─── Session Rollover ────────────────────────────────────────────────────

  /**
   * Call once per simulated tick; pass the current sim date string.
   * Resets daily counters at session open.
   */
  checkSessionRollover(dateStr) {
    if (dateStr !== this._sessionDate) {
      this._sessionDate    = dateStr;
      this.dayPnl          = 0;
      this.dayTradeCount   = 0;
      this.consecutiveLoss = 0;
      this.tradingLocked   = false;
      this.lockReason      = '';
    }
  }

  // ─── Balance Updates ─────────────────────────────────────────────────────

  /**
   * Record a closed trade P&L.
   * Updates balance, peak, floor, and daily/consecutive loss counters.
   *
   * @param {number} pnl – realized P&L in dollars (positive = win)
   * @returns {{ blown: boolean, locked: boolean, reason: string }}
   */
  recordTrade(pnl) {
    this.dayPnl        += pnl;
    this.dayTradeCount += 1;
    this.balance       += pnl;

    // ── Consecutive loss tracking ──────────────────────────────────────────
    if (pnl < 0) {
      this.consecutiveLoss++;
      if (this.consecutiveLoss >= ACCOUNT_PARAMS.maxConsecutiveLosses) {
        this.tradingLocked = true;
        this.lockReason    = `${ACCOUNT_PARAMS.maxConsecutiveLosses} consecutive losses — trading locked for the rest of the day.`;
      }
    } else {
      this.consecutiveLoss = 0; // reset on a win
    }

    // ── Max trades per day ────────────────────────────────────────────────
    if (this.dayTradeCount >= ACCOUNT_PARAMS.maxTradesPerDay) {
      this.tradingLocked = true;
      this.lockReason    = `Daily trade limit (${ACCOUNT_PARAMS.maxTradesPerDay}) reached.`;
    }

    // ── Daily loss limit ──────────────────────────────────────────────────
    if (this.dayPnl <= -ACCOUNT_PARAMS.dailyLossLimit) {
      this.tradingLocked = true;
      this.lockReason    = `Daily loss limit ($${ACCOUNT_PARAMS.dailyLossLimit}) hit.`;
    }

    // ── Apex trailing threshold ───────────────────────────────────────────
    this._updateApexThreshold();

    const blown = this.balance <= this.floor;
    return { blown, locked: this.tradingLocked, reason: this.lockReason };
  }

  /**
   * Adjust balance for open unrealised P&L without recording a trade.
   * Used to show live drawdown distance in the top bar.
   */
  unrealisedBalance(openPnl) {
    return this.balance + openPnl;
  }

  // ─── Pre-Trade Checks ────────────────────────────────────────────────────

  /**
   * Returns an array of failed check messages (empty = all clear).
   *
   * @param {object} context
   * @param {string} context.side         – "long" | "short"
   * @param {number} context.price        – intended entry price
   * @param {number} context.contracts    – number of contracts
   * @param {number} context.vwap         – current session VWAP
   * @param {number} context.rsi          – current RSI value
   * @param {boolean} context.hasBos      – true if BOS in trade direction
   * @param {boolean} context.inSafeHours – true if current time is in safe window
   * @param {boolean} context.inDanger    – true if current time is in danger zone
   */
  preTradeChecks(context) {
    const failures = [];
    const { side, price, contracts, vwap, rsi, hasBos, inSafeHours, inDanger } = context;

    if (this.tradingLocked) {
      failures.push(`Trading locked: ${this.lockReason}`);
      return failures; // no point checking further
    }

    // Time checks
    if (!inSafeHours) failures.push('Not in safe trading window (9:30-11:00 or 13:30-15:00).');
    if (inDanger)     failures.push('Current time is in a danger zone (news/FOMC window).');

    // BOS check
    if (!hasBos) failures.push(`No valid BOS in the ${side} direction.`);

    // VWAP filter
    if (vwap !== null) {
      if (side === 'long'  && price < vwap) failures.push('Price is below VWAP — Long not favored.');
      if (side === 'short' && price > vwap) failures.push('Price is above VWAP — Short not favored.');
    }

    // RSI filter (40–60 zone = pullback / not overextended)
    if (rsi !== null && (rsi < 40 || rsi > 60)) {
      failures.push(`RSI ${rsi.toFixed(1)} is outside the 40–60 zone.`);
    }

    // Risk per trade: stop loss is 10 pts × $20/pt × contracts
    const riskDollars = TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue * contracts;
    if (riskDollars > TRADING_RULES.maxRiskPerTrade) {
      failures.push(`Risk $${riskDollars} exceeds max $${TRADING_RULES.maxRiskPerTrade} per trade.`);
    }

    // Contract size limit
    const maxContracts = TRADING_RULES.aplusContracts;
    if (contracts > maxContracts) failures.push(`Max contracts is ${maxContracts}.`);

    // Daily trade count
    if (this.dayTradeCount >= ACCOUNT_PARAMS.maxTradesPerDay) {
      failures.push(`Daily trade limit (${ACCOUNT_PARAMS.maxTradesPerDay}) reached.`);
    }

    return failures;
  }

  // ─── Derived Metrics (for Top Bar display) ────────────────────────────────

  get distanceToBlowup() {
    return Math.max(0, this.balance - this.floor);
  }

  get drawdownFloor() {
    return this.floor;
  }

  get apexStatus() {
    return {
      balance:         this.balance,
      peakBalance:     this.peakBalance,
      floor:           this.floor,
      distanceToBlowup: this.distanceToBlowup,
      locked:          this.locked,
      dayPnl:          this.dayPnl,
      dayTradeCount:   this.dayTradeCount,
      consecutiveLoss: this.consecutiveLoss,
      tradingLocked:   this.tradingLocked,
      lockReason:      this.lockReason,
    };
  }

  // ─── Private ─────────────────────────────────────────────────────────────

  /**
   * Apex trailing threshold update.
   *
   * Phase 1: peak < lockLevel → floor = peak - trailingDrawdown  (trails up)
   * Phase 2: peak ≥ lockLevel → floor is permanently $50,100     (locked)
   */
  _updateApexThreshold() {
    if (this.balance > this.peakBalance) {
      this.peakBalance = this.balance;
    }

    if (!this.locked && this.peakBalance >= ACCOUNT_PARAMS.trailingLockLevel) {
      // Transition to Phase 2: lock the floor permanently
      this.locked = true;
      this.floor  = ACCOUNT_PARAMS.lockedFloor;
    }

    if (!this.locked) {
      // Phase 1: floor trails the peak
      this.floor = this.peakBalance - ACCOUNT_PARAMS.trailingDrawdown;
    }
    // Phase 2: floor stays at lockedFloor (already set)
  }

  // ─── Persistence ─────────────────────────────────────────────────────────

  toJSON() {
    return {
      balance: this.balance, peakBalance: this.peakBalance,
      locked: this.locked,   floor: this.floor,
      dayPnl: this.dayPnl,   dayTradeCount: this.dayTradeCount,
      consecutiveLoss: this.consecutiveLoss,
      tradingLocked: this.tradingLocked, lockReason: this.lockReason,
      _sessionDate: this._sessionDate,
    };
  }
}
