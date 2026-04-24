/**
 * ChecklistPanel
 * ──────────────
 * Live green/red status lights for all pre-trade conditions.
 * Evaluated continuously from the store; not just on trade attempt.
 */

import React from 'react';
import useStore from '../store/useStore.js';
import { SESSION_TIMES, TRADING_RULES, NQ_SPECS, ACCOUNT_PARAMS } from '../constants.js';

export default function ChecklistPanel() {
  const { sim, indicators, account, ui } = useStore();

  const h = sim.simTime?.getHours()   ?? 0;
  const m = sim.simTime?.getMinutes() ?? 0;
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

  // Last BOS direction
  const lastBos = indicators.bos.bosEvents.at(-1);
  const hasBullishBos = indicators.bos.bosEvents.some(b => b.type === 'bullish');
  const hasBearishBos = indicators.bos.bosEvents.some(b => b.type === 'bearish');

  const price = sim.currentPrice ?? 0;
  const vwap  = indicators.vwap;
  const rsi   = indicators.rsi;

  const aboveVwap = vwap !== null ? price > vwap : null;
  const rsiOk     = rsi  !== null ? (rsi >= 40 && rsi <= 60) : null;

  const riskOk = (TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue * ui.contracts) <= TRADING_RULES.maxRiskPerTrade;
  const tradesOk = account.dayTradeCount < ACCOUNT_PARAMS.maxTradesPerDay;
  const notLocked = !account.tradingLocked;
  const consLossOk = account.consecutiveLoss < ACCOUNT_PARAMS.maxConsecutiveLosses;

  const checks = [
    { label: 'Safe Hours',         ok: inSafeHours && !inDanger,        detail: inDanger ? 'Danger zone!' : inSafeHours ? '9:30-11 or 13:30-15' : 'Outside window' },
    { label: 'BOS (Bullish)',      ok: hasBullishBos,                    detail: hasBullishBos ? `Last: ${lastBos?.price?.toFixed(2)}` : 'No bullish BOS' },
    { label: 'BOS (Bearish)',      ok: hasBearishBos,                    detail: hasBearishBos ? `Last: ${lastBos?.price?.toFixed(2)}` : 'No bearish BOS' },
    { label: 'Above VWAP (Long)',  ok: aboveVwap,                        detail: aboveVwap === null ? '—' : aboveVwap ? 'Price > VWAP' : 'Price < VWAP' },
    { label: 'Below VWAP (Short)', ok: aboveVwap === null ? null : !aboveVwap, detail: aboveVwap === null ? '—' : !aboveVwap ? 'Price < VWAP' : 'Price > VWAP' },
    { label: 'RSI 40–60',         ok: rsiOk,                             detail: rsi !== null ? `RSI ${rsi.toFixed(1)}` : 'Not enough data' },
    { label: 'Risk ≤ $200',        ok: riskOk,                            detail: `$${TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue * ui.contracts}` },
    { label: 'Trades < 3/day',     ok: tradesOk,                          detail: `${account.dayTradeCount}/3 used` },
    { label: 'No Consec. Losses',  ok: consLossOk,                        detail: `${account.consecutiveLoss} in a row` },
    { label: 'Not Locked',         ok: notLocked,                         detail: notLocked ? 'Clear' : account.lockReason },
  ];

  // Show failures from last trade attempt
  const lastFailures = useStore(s => s.ui.lastChecklistFailures ?? []);

  return (
    <div style={styles.panel}>
      <div style={styles.header}>PRE-TRADE CHECKLIST</div>

      {lastFailures.length > 0 && (
        <div style={styles.failBox}>
          {lastFailures.map((f, i) => <div key={i}>⛔ {f}</div>)}
        </div>
      )}

      <div style={styles.list}>
        {checks.map((c, i) => (
          <CheckRow key={i} {...c} />
        ))}
      </div>

      {/* Daily limit progress */}
      <div style={styles.section}>
        <div style={styles.subLabel}>DAILY P&L LIMIT</div>
        <div style={styles.progressBg}>
          <div
            style={{
              ...styles.progressFill,
              width: `${Math.min(100, (Math.abs(Math.min(0, account.dayPnl)) / 600) * 100)}%`,
              background: Math.abs(account.dayPnl) > 400 ? '#ef5350' : '#f0b429',
            }}
          />
        </div>
        <div style={{ color: '#8b949e', fontSize: 10, marginTop: 2 }}>
          ${Math.abs(Math.min(0, account.dayPnl)).toFixed(0)} / $600 daily loss used
        </div>
      </div>
    </div>
  );
}

function CheckRow({ label, ok, detail }) {
  const color = ok === null ? '#555' : ok ? '#26a69a' : '#ef5350';
  const icon  = ok === null ? '○' : ok ? '✓' : '✗';
  return (
    <div style={styles.row}>
      <span style={{ color, fontWeight: 'bold', width: 14 }}>{icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ color: ok === null ? '#555' : '#e6edf3', fontSize: 11 }}>{label}</div>
        <div style={{ color: '#8b949e', fontSize: 9 }}>{detail}</div>
      </div>
    </div>
  );
}

const styles = {
  panel:    { display: 'flex', flexDirection: 'column', background: '#0d1117', height: '100%', overflow: 'auto' },
  header:   { color: '#8b949e', fontSize: 10, letterSpacing: 2, padding: '8px 12px 4px', borderBottom: '1px solid #21262d' },
  list:     { padding: '4px 0' },
  row:      { display: 'flex', alignItems: 'flex-start', gap: 8, padding: '4px 12px', borderBottom: '1px solid #0d1117' },
  section:  { padding: '8px 12px' },
  subLabel: { color: '#8b949e', fontSize: 9, letterSpacing: 1, marginBottom: 4 },
  progressBg: { height: 6, background: '#21262d', borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 3, transition: 'width 0.3s' },
  failBox: {
    margin: '6px 12px', padding: 8, background: 'rgba(239,83,80,0.15)',
    border: '1px solid #ef5350', borderRadius: 4, color: '#ef5350', fontSize: 11, lineHeight: 1.6,
  },
};
