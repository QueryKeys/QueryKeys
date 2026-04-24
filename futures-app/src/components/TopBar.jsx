/**
 * TopBar – Account stats + simulation controls
 *
 * Displays:
 *   Balance | Day P&L | Floor | Distance-to-blowup | Current price | Sim clock
 *   [Start/Pause] [Speed selector] [Flatten All]
 */

import React from 'react';
import useStore from '../store/useStore.js';

const fmt = (n, decimals = 2) =>
  typeof n === 'number' ? n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : n;

const fmtPrice = p => typeof p === 'number' ? p.toFixed(2) : '—';

export default function TopBar() {
  const { sim, account, startSim, pauseSim, setSpeed, flattenAll, trading } = useStore();

  const pnlColor  = account.dayPnl >= 0 ? '#26a69a' : '#ef5350';
  const distColor = account.distanceToBlowup < 500 ? '#ef5350'
                  : account.distanceToBlowup < 1000 ? '#f0b429' : '#26a69a';

  const timeStr = sim.simTime
    ? sim.simTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '--:--:--';

  return (
    <div style={styles.bar}>
      {/* App title */}
      <div style={styles.title}>NQ FUTURES PRO</div>

      <div style={styles.divider} />

      {/* Price */}
      <div style={styles.stat}>
        <span style={styles.label}>NQ</span>
        <span style={{ ...styles.value, color: '#e6edf3', fontSize: 18, fontWeight: 'bold' }}>
          {fmtPrice(sim.currentPrice)}
        </span>
      </div>

      <div style={styles.divider} />

      {/* Account balance */}
      <div style={styles.stat}>
        <span style={styles.label}>BALANCE</span>
        <span style={styles.value}>${fmt(account.balance)}</span>
      </div>

      {/* Day P&L */}
      <div style={styles.stat}>
        <span style={styles.label}>DAY P&L</span>
        <span style={{ ...styles.value, color: pnlColor }}>
          {account.dayPnl >= 0 ? '+' : ''}${fmt(account.dayPnl)}
        </span>
      </div>

      {/* Drawdown floor */}
      <div style={styles.stat}>
        <span style={styles.label}>FLOOR {account.locked ? '🔒' : '↑'}</span>
        <span style={styles.value}>${fmt(account.floor)}</span>
      </div>

      {/* Distance to blowup */}
      <div style={styles.stat}>
        <span style={styles.label}>TO BLOWUP</span>
        <span style={{ ...styles.value, color: distColor }}>${fmt(account.distanceToBlowup)}</span>
      </div>

      <div style={styles.divider} />

      {/* Trades today */}
      <div style={styles.stat}>
        <span style={styles.label}>TRADES</span>
        <span style={styles.value}>{account.dayTradeCount}/3</span>
      </div>

      {/* Stats */}
      <div style={styles.stat}>
        <span style={styles.label}>WIN%</span>
        <span style={styles.value}>{trading.stats.winRate}%</span>
      </div>

      <div style={{ flex: 1 }} />

      {/* Sim clock */}
      <div style={styles.stat}>
        <span style={styles.label}>SIM TIME (EST)</span>
        <span style={{ ...styles.value, color: '#7c3aed' }}>{timeStr}</span>
      </div>

      <div style={styles.divider} />

      {/* Speed selector */}
      <div style={styles.stat}>
        <span style={styles.label}>SPEED</span>
        <select
          style={styles.select}
          value={sim.speed}
          onChange={e => setSpeed(Number(e.target.value))}
        >
          <option value={1}>1× (real)</option>
          <option value={10}>10×</option>
          <option value={60}>60×</option>
          <option value={300}>300×</option>
        </select>
      </div>

      {/* Flatten all */}
      {trading.openPosition && (
        <button style={{ ...styles.btn, background: '#ef5350' }} onClick={flattenAll}>
          FLATTEN
        </button>
      )}

      {/* Start / Pause */}
      <button
        style={{ ...styles.btn, background: sim.running ? '#444' : '#26a69a' }}
        onClick={sim.running ? pauseSim : startSim}
      >
        {sim.running ? '⏸ PAUSE' : '▶ START'}
      </button>

      {/* Trading lock banner */}
      {account.tradingLocked && (
        <div style={styles.lockBanner}>⛔ {account.lockReason}</div>
      )}
    </div>
  );
}

const styles = {
  bar: {
    display: 'flex', alignItems: 'center', gap: 12,
    background: '#161b22', borderBottom: '1px solid #30363d',
    padding: '0 16px', height: 44, flexShrink: 0, overflow: 'hidden',
    position: 'relative',
  },
  title: { color: '#f0b429', fontWeight: 'bold', fontSize: 13, letterSpacing: 2, whiteSpace: 'nowrap' },
  divider: { width: 1, height: 24, background: '#30363d' },
  stat: { display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0 },
  label: { color: '#8b949e', fontSize: 9, letterSpacing: 1, textTransform: 'uppercase' },
  value: { color: '#e6edf3', fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' },
  select: {
    background: '#0d1117', color: '#e6edf3', border: '1px solid #30363d',
    borderRadius: 4, fontSize: 11, padding: '1px 4px', cursor: 'pointer',
  },
  btn: {
    border: 'none', borderRadius: 4, color: '#fff', fontWeight: 'bold',
    fontSize: 11, padding: '4px 10px', cursor: 'pointer', whiteSpace: 'nowrap',
  },
  lockBanner: {
    position: 'absolute', right: 0, top: 0, bottom: 0,
    background: 'rgba(239,83,80,0.9)', color: '#fff', fontWeight: 'bold',
    fontSize: 11, padding: '0 16px', display: 'flex', alignItems: 'center',
  },
};
