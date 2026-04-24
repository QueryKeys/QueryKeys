/**
 * useStore – Zustand global store
 *
 * Slices:
 *   sim        – simulation clock + current tick
 *   bars       – 1m and 5m OHLCV history
 *   orderBook  – current bid/ask levels + cumulative depth
 *   indicators – VWAP, RSI, BOS results
 *   trading    – open position, closed trades, order manager state
 *   account    – risk manager state (balance, floor, limits)
 *   settings   – user preferences (speed, contracts, etc.)
 *   ui         – which panels are visible, selected TF, etc.
 */

import { create } from 'zustand';
import { PriceSimulator }   from '../simulation/PriceSimulator.js';
import { OrderBookSimulator } from '../simulation/OrderBookSimulator.js';
import { BarBuilder }        from '../simulation/BarBuilder.js';
import { BosDetector }       from '../indicators/bos.js';
import { computeVwapSeries, currentVwap } from '../indicators/vwap.js';
import { currentRsi, computeRsiSeries }  from '../indicators/rsi.js';
import { RiskManager }  from '../trading/RiskManager.js';
import { OrderManager } from '../trading/OrderManager.js';
import { SESSION_TIMES, DEFAULT_SETTINGS, ACCOUNT_PARAMS } from '../constants.js';

// ── Singleton simulation objects (not reactive; live outside Zustand) ─────────
const priceSimulator   = new PriceSimulator();
const orderBookSim     = new OrderBookSimulator();
const barBuilder       = new BarBuilder();
const bosDetector      = new BosDetector(DEFAULT_SETTINGS.bosSwingLookback);

// ── Simulation clock ──────────────────────────────────────────────────────────
// We drive a virtual EST clock. On startup it's set to 9:30 today.
function makeSessionStart() {
  const now = new Date();
  // Set to 9:30 AM (simulate EST; offset from browser locale is not applied —
  // we treat the simulated hours as "EST" for display purposes).
  now.setHours(SESSION_TIMES.open.hour, SESSION_TIMES.open.minute, 0, 0);
  return now;
}

// Real-time interval handle
let _intervalHandle = null;

// ─────────────────────────────────────────────────────────────────────────────

const useStore = create((set, get) => {
  // Instantiate managers here so they can call set() via callbacks
  const riskManager = new RiskManager();

  const orderManager = new OrderManager({
    onTradeClose: (closedTrade) => {
      const result = riskManager.recordTrade(closedTrade.totalPnl);
      set(s => ({
        account: { ...riskManager.apexStatus },
        trading: {
          ...s.trading,
          openPosition: null,
          closedTrades: [...s.trading.closedTrades, closedTrade],
          stats: orderManager.stats,
        },
        ui: result.blown ? { ...s.ui, blown: true } : s.ui,
      }));
      // Persist risk state
      localStorage.setItem('riskState', JSON.stringify(riskManager.toJSON()));
    },
    onUpdate: () => {
      set(s => ({
        trading: {
          ...s.trading,
          openPosition: orderManager.openPosition,
        },
      }));
    },
  });

  return {
    // ── Sim state ────────────────────────────────────────────────────────────
    sim: {
      running:     false,
      simTime:     makeSessionStart(),
      speed:       DEFAULT_SETTINGS.speedMultiplier, // 60 = 1 min per sec
      currentPrice: NQ_SPECS?.startPrice ?? 20000,
      lastTick:    null,
    },

    // ── Bar data ─────────────────────────────────────────────────────────────
    bars: {
      '1m': [],
      '5m': [],
    },

    // ── Order book ────────────────────────────────────────────────────────────
    orderBook: {
      bids:            [],
      asks:            [],
      cumulativeBids:  [],
      cumulativeAsks:  [],
    },

    // ── Indicators ────────────────────────────────────────────────────────────
    indicators: {
      vwapSeries: [],
      vwap:       null,
      rsiSeries:  [],
      rsi:        null,
      bos:        { swingHighs: [], swingLows: [], bosEvents: [] },
    },

    // ── Trading ───────────────────────────────────────────────────────────────
    trading: {
      openPosition: null,
      closedTrades: [],
      stats: { total: 0, wins: 0, losses: 0, winRate: '0.0', totalPnl: '0.00', profitFactor: '∞', avgR: 0, consecutiveLoss: 0 },
    },

    // ── Account ───────────────────────────────────────────────────────────────
    account: { ...riskManager.apexStatus },

    // ── Settings (persisted) ─────────────────────────────────────────────────
    settings: {
      ...DEFAULT_SETTINGS,
      ...JSON.parse(localStorage.getItem('settings') ?? '{}'),
    },

    // ── UI ───────────────────────────────────────────────────────────────────
    ui: {
      selectedTf:    '5m',
      showHeatmap:   true,
      showLog:       true,
      blown:         false,
      contracts:     2,        // selected contract size for next trade
      checklistOpen: false,
    },

    // ── Actions ───────────────────────────────────────────────────────────────

    /** Start/resume the simulation loop */
    startSim() {
      if (_intervalHandle) return;
      set(s => ({ sim: { ...s.sim, running: true } }));

      // Real-time tick interval in ms.
      // Each tick advances sim time by (speed × tickMs) ms.
      const tickMs   = 250; // fire every 250 ms of wall clock
      const simAdvMs = () => get().sim.speed * tickMs; // ms of sim time per tick

      _intervalHandle = setInterval(() => {
        const st    = get();
        const simTime = new Date(st.sim.simTime.getTime() + simAdvMs());

        // Session date for rollover detection
        const dateStr = `${simTime.getFullYear()}-${simTime.getMonth()}-${simTime.getDate()}`;
        riskManager.checkSessionRollover(dateStr);

        // Generate tick
        const tick = priceSimulator.tick(simTime);

        // Update order book
        const book = orderBookSim.update(tick.price);

        // Feed tick to order manager (check fills)
        orderManager.onTick(tick.price, simTime);

        // Build bars
        const { bars1m, bars5m, sessionVwap } = barBuilder.addTick(tick);

        // Compute indicators on 5m bars
        const vwapSeries = computeVwapSeries(bars5m);
        const vwap       = currentVwap(bars5m);
        const rsiSeries  = computeRsiSeries(bars5m, st.settings.rsiPeriod);
        const rsi        = currentRsi(bars5m, st.settings.rsiPeriod);
        const bos        = bosDetector.update(bars5m);

        set({
          sim: { ...st.sim, simTime, running: true, currentPrice: tick.price, lastTick: tick },
          bars: { '1m': bars1m, '5m': bars5m },
          orderBook: book,
          indicators: { vwapSeries, vwap, rsiSeries, rsi, bos },
          // account is updated by onTradeClose; update open unrealised here
          account: {
            ...riskManager.apexStatus,
          },
        });
      }, tickMs);
    },

    /** Pause the simulation */
    pauseSim() {
      if (_intervalHandle) { clearInterval(_intervalHandle); _intervalHandle = null; }
      set(s => ({ sim: { ...s.sim, running: false } }));
    },

    /** Change simulation speed (1 = real-time, 60 = fast test mode) */
    setSpeed(speed) {
      set(s => ({ sim: { ...s.sim, speed }, settings: { ...s.settings, speedMultiplier: speed } }));
    },

    /** Place a new bracket trade */
    enterTrade(side) {
      const st       = get();
      const price    = st.sim.currentPrice;
      const contracts = st.ui.contracts;
      const simTime  = st.sim.simTime;
      const { vwap, rsi, bos } = st.indicators;

      // Determine if there's a BOS in the trade direction
      const hasBos = bos.bosEvents.some(b =>
        (side === 'long'  && b.type === 'bullish') ||
        (side === 'short' && b.type === 'bearish')
      );

      // Time checks
      const h = simTime.getHours(), m = simTime.getMinutes();
      const minOfDay = h * 60 + m;
      const inSafeHours = SESSION_TIMES.safeWindows.some(w => {
        const s = w.start.hour * 60 + w.start.minute;
        const e = w.end.hour   * 60 + w.end.minute;
        return minOfDay >= s && minOfDay < e;
      });
      const inDanger = SESSION_TIMES.dangerZones.some(z => {
        const zStart = z.hour * 60 + z.minute;
        return minOfDay >= zStart && minOfDay < zStart + z.durationMin;
      });

      const failures = riskManager.preTradeChecks({
        side, price, contracts, vwap, rsi, hasBos, inSafeHours, inDanger,
      });

      if (failures.length > 0) {
        // Surface checklist failures to UI
        set(s => ({ ui: { ...s.ui, lastChecklistFailures: failures, checklistOpen: true } }));
        return { ok: false, failures };
      }

      const pos = orderManager.enter(side, price, contracts, simTime);
      set(s => ({
        trading: { ...s.trading, openPosition: pos },
        ui: { ...s.ui, lastChecklistFailures: [], checklistOpen: false },
      }));
      return { ok: true, position: pos };
    },

    /** Flatten all open positions at market */
    flattenAll() {
      const st = get();
      orderManager.flattenAll(st.sim.currentPrice, st.sim.simTime);
    },

    /** Change selected contract size */
    setContracts(n) {
      set(s => ({ ui: { ...s.ui, contracts: n } }));
    },

    /** Save settings to localStorage */
    saveSettings(patch) {
      set(s => {
        const next = { ...s.settings, ...patch };
        localStorage.setItem('settings', JSON.stringify(next));
        return { settings: next };
      });
    },

    // Expose managers for direct access (used by components)
    _orderManager: orderManager,
    _riskManager:  riskManager,
  };
});


export default useStore;
