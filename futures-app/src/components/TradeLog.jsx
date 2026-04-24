/**
 * TradeLog – Trade Journal & Statistics
 *
 * Shows a table of all closed trades with:
 *   Time | Direction | Entry | Exit(s) | P&L | BE? | Duration
 *
 * Footer metrics: win rate, average R, profit factor, consecutive losses.
 * Export as CSV button.
 */

import React from 'react';
import useStore from '../store/useStore.js';
import { TRADING_RULES, NQ_SPECS } from '../constants.js';

const MAX_RISK = TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue; // per contract

export default function TradeLog() {
  const { trading } = useStore();
  const trades = trading.closedTrades;
  const stats  = trading.stats;

  const exportCsv = () => {
    const header = 'ID,Time,Side,Contracts,Entry,Exit,P&L,R,BE,Duration(min)\n';
    const rows = trades.map(t => {
      const exitPrice = t.exitParts.at(-1)?.price ?? t.entryPrice;
      const R = (t.totalPnl / (MAX_RISK * t.contracts)).toFixed(2);
      return [
        t.id,
        t.entryTime?.toISOString() ?? '',
        t.side,
        t.contracts,
        t.entryPrice,
        exitPrice,
        t.totalPnl?.toFixed(2),
        R,
        t.beTriggered ? 'Y' : 'N',
        t.holdTimeMin ?? '',
      ].join(',');
    });
    const csv  = header + rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), { href: url, download: 'nq_trade_log.csv' });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={styles.panel}>
      {/* Header row */}
      <div style={styles.topRow}>
        <span style={styles.title}>TRADE LOG</span>
        <div style={styles.statsRow}>
          <Stat label="Trades" val={stats.total} />
          <Stat label="Win %" val={`${stats.winRate}%`} color={parseFloat(stats.winRate) >= 50 ? '#26a69a' : '#ef5350'} />
          <Stat label="Avg R" val={`${stats.avgR}R`} color={parseFloat(stats.avgR) >= 0 ? '#26a69a' : '#ef5350'} />
          <Stat label="PF" val={stats.profitFactor} color={parseFloat(stats.profitFactor) >= 1 ? '#26a69a' : '#ef5350'} />
          <Stat label="Total P&L" val={`$${stats.totalPnl}`} color={parseFloat(stats.totalPnl) >= 0 ? '#26a69a' : '#ef5350'} />
          <Stat label="Consec L" val={stats.consecutiveLoss} color={stats.consecutiveLoss >= 2 ? '#ef5350' : '#e6edf3'} />
        </div>
        {trades.length > 0 && (
          <button style={styles.exportBtn} onClick={exportCsv}>⬇ CSV</button>
        )}
      </div>

      {/* Table */}
      <div style={styles.tableWrap}>
        {trades.length === 0 ? (
          <div style={styles.empty}>No closed trades yet — start the simulation and place a trade.</div>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                {['#', 'Time', 'Side', 'Qty', 'Entry', 'Exit', 'P&L', 'R', 'BE', 'Hold'].map(h => (
                  <th key={h} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...trades].reverse().map(t => {
                const exitPrice = t.exitParts.at(-1)?.price ?? t.entryPrice;
                const R = (t.totalPnl / (MAX_RISK * t.contracts)).toFixed(2);
                const pnlColor = t.totalPnl > 0 ? '#26a69a' : '#ef5350';
                const rColor   = parseFloat(R) >= 0 ? '#26a69a' : '#ef5350';
                const timeStr  = t.entryTime instanceof Date
                  ? t.entryTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
                  : '—';

                return (
                  <tr key={t.id} style={{ borderBottom: '1px solid #21262d' }}>
                    <td style={styles.td}>{t.id}</td>
                    <td style={styles.td}>{timeStr}</td>
                    <td style={{ ...styles.td, color: t.side === 'long' ? '#26a69a' : '#ef5350', fontWeight: 'bold' }}>
                      {t.side.toUpperCase()}
                    </td>
                    <td style={styles.td}>{t.contracts}</td>
                    <td style={styles.td}>{t.entryPrice.toFixed(2)}</td>
                    <td style={styles.td}>{exitPrice.toFixed(2)}</td>
                    <td style={{ ...styles.td, color: pnlColor }}>{t.totalPnl >= 0 ? '+' : ''}${t.totalPnl?.toFixed(2)}</td>
                    <td style={{ ...styles.td, color: rColor }}>{R}R</td>
                    <td style={styles.td}>{t.beTriggered ? <span style={{ color: '#f0b429' }}>✓</span> : '—'}</td>
                    <td style={styles.td}>{t.holdTimeMin ?? '—'}m</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Stat({ label, val, color = '#e6edf3' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <span style={{ color: '#8b949e', fontSize: 9, letterSpacing: 1 }}>{label}</span>
      <span style={{ color, fontSize: 12, fontWeight: 600 }}>{val}</span>
    </div>
  );
}

const styles = {
  panel:     { display: 'flex', flexDirection: 'column', height: '100%', background: '#0d1117', overflow: 'hidden' },
  topRow:    { display: 'flex', alignItems: 'center', gap: 16, padding: '6px 12px', borderBottom: '1px solid #21262d', flexShrink: 0 },
  title:     { color: '#8b949e', fontSize: 10, letterSpacing: 2, whiteSpace: 'nowrap' },
  statsRow:  { display: 'flex', gap: 16, flex: 1 },
  exportBtn: { border: '1px solid #30363d', borderRadius: 4, background: 'transparent', color: '#8b949e', fontSize: 10, padding: '2px 8px', cursor: 'pointer' },
  tableWrap: { flex: 1, overflow: 'auto' },
  empty:     { color: '#8b949e', fontSize: 12, padding: 20, textAlign: 'center' },
  table:     { width: '100%', borderCollapse: 'collapse', fontSize: 11 },
  th:        { color: '#8b949e', fontWeight: 600, padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid #30363d', whiteSpace: 'nowrap' },
  td:        { color: '#e6edf3', padding: '3px 8px', whiteSpace: 'nowrap' },
};
