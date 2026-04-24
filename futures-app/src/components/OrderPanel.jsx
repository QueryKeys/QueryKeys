/**
 * OrderPanel
 * ──────────
 * Right-side panel: contract selector, hotkey guide, long/short buttons,
 * active position monitor (entry, stop, TP1, TP2, unrealised P&L, BE status).
 *
 * Hotkeys (registered globally in App.jsx):
 *   Ctrl+B → Long
 *   Ctrl+S → Short
 *   Ctrl+F → Flatten All
 */

import React from 'react';
import useStore from '../store/useStore.js';
import { TRADING_RULES, NQ_SPECS } from '../constants.js';

export default function OrderPanel() {
  const { sim, trading, ui, account, enterTrade, flattenAll, setContracts, indicators } = useStore();

  const pos       = trading.openPosition;
  const locked    = account.tradingLocked;
  const contracts = ui.contracts;

  // Live unrealised P&L for open position
  const unrealisedPnl = pos
    ? (sim.currentPrice - pos.entryPrice) * NQ_SPECS.pointValue * pos.remaining * (pos.side === 'long' ? 1 : -1)
    : 0;

  const pnlColor = unrealisedPnl >= 0 ? '#26a69a' : '#ef5350';

  return (
    <div style={styles.panel}>
      <div style={styles.header}>ORDER ENTRY</div>

      {/* Contract size */}
      <div style={styles.section}>
        <span style={styles.label}>CONTRACTS</span>
        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
          {[1, 2, 3].map(n => (
            <button
              key={n}
              style={{
                ...styles.contractBtn,
                background:  contracts === n ? '#30363d' : 'transparent',
                borderColor: contracts === n ? '#58a6ff' : '#30363d',
                color:       n === 3 ? '#f0b429' : '#e6edf3',
              }}
              onClick={() => setContracts(n)}
            >
              {n}{n === 3 ? ' A+' : ''}
            </button>
          ))}
        </div>
        <div style={{ color: '#8b949e', fontSize: 10, marginTop: 4 }}>
          Risk: ${TRADING_RULES.stopLossPoints * NQ_SPECS.pointValue * contracts} · Stop: {TRADING_RULES.stopLossPoints}pts
        </div>
      </div>

      {/* Trade buttons */}
      <div style={styles.section}>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            style={{ ...styles.tradeBtn, background: locked || pos ? '#333' : '#26a69a', flex: 1 }}
            onClick={() => enterTrade('long')}
            disabled={locked || !!pos}
          >
            ▲ LONG<br />
            <span style={{ fontSize: 10, fontWeight: 'normal' }}>Ctrl+B</span>
          </button>
          <button
            style={{ ...styles.tradeBtn, background: locked || pos ? '#333' : '#ef5350', flex: 1 }}
            onClick={() => enterTrade('short')}
            disabled={locked || !!pos}
          >
            ▼ SHORT<br />
            <span style={{ fontSize: 10, fontWeight: 'normal' }}>Ctrl+S</span>
          </button>
        </div>
        {locked && <div style={styles.lockMsg}>⛔ {account.lockReason || 'Trading locked'}</div>}
      </div>

      {/* Active position */}
      {pos && (
        <div style={styles.section}>
          <div style={styles.label}>OPEN POSITION</div>
          <div style={styles.posGrid}>
            <div style={styles.posRow}>
              <span style={{ color: pos.side === 'long' ? '#26a69a' : '#ef5350', fontWeight: 'bold' }}>
                {pos.side.toUpperCase()} {pos.contracts}x
              </span>
              <span style={{ color: pnlColor, fontWeight: 'bold', fontSize: 14 }}>
                {unrealisedPnl >= 0 ? '+' : ''}${unrealisedPnl.toFixed(2)}
              </span>
            </div>
            <div style={styles.posRow}>
              <span style={styles.posLabel}>Entry</span>
              <span style={styles.posVal}>{pos.entryPrice.toFixed(2)}</span>
            </div>
            <div style={styles.posRow}>
              <span style={styles.posLabel}>Stop {pos.beTriggered ? '(BE)' : ''}</span>
              <span style={{ ...styles.posVal, color: '#ef5350' }}>{pos.stopPrice.toFixed(2)}</span>
            </div>
            {!pos.tp1Hit && (
              <div style={styles.posRow}>
                <span style={styles.posLabel}>TP1 ({pos.tp1Qty}x)</span>
                <span style={{ ...styles.posVal, color: '#26a69a' }}>{pos.tp1Price.toFixed(2)}</span>
              </div>
            )}
            {!pos.tp2Hit && (
              <div style={styles.posRow}>
                <span style={styles.posLabel}>TP2 ({pos.tp2Qty}x)</span>
                <span style={{ ...styles.posVal, color: '#00c853' }}>{pos.tp2Price.toFixed(2)}</span>
              </div>
            )}
            {pos.tp1Hit && (
              <div style={{ color: '#26a69a', fontSize: 10, marginTop: 2 }}>✓ TP1 hit · Stop → BE</div>
            )}
            {pos.beTriggered && !pos.tp1Hit && (
              <div style={{ color: '#f0b429', fontSize: 10, marginTop: 2 }}>⚡ Break-even active</div>
            )}
          </div>
          <button style={{ ...styles.tradeBtn, background: '#444', marginTop: 8, width: '100%' }} onClick={flattenAll}>
            ✕ FLATTEN ALL (Ctrl+F)
          </button>
        </div>
      )}

      {/* Bracket reminder */}
      <div style={styles.section}>
        <div style={styles.label}>BRACKET CONFIG</div>
        <div style={styles.configGrid}>
          <BracketRow label="Stop" val={`${TRADING_RULES.stopLossPoints} pts`} />
          <BracketRow label="TP1"  val={`${TRADING_RULES.tp1Points} pts (50%)`} color="#26a69a" />
          <BracketRow label="TP2"  val={`${TRADING_RULES.tp2Points} pts (rem)`} color="#00c853" />
          <BracketRow label="BE @" val={`+${TRADING_RULES.breakEvenTriggerPoints} pts`} color="#f0b429" />
        </div>
      </div>

      {/* VWAP / RSI quick view */}
      <div style={styles.section}>
        <div style={styles.label}>MARKET CONTEXT</div>
        <div style={styles.configGrid}>
          <BracketRow label="VWAP" val={indicators.vwap?.toFixed(2) ?? '—'} />
          <BracketRow
            label="RSI"
            val={indicators.rsi?.toFixed(1) ?? '—'}
            color={(indicators.rsi != null && (indicators.rsi < 40 || indicators.rsi > 60)) ? '#ef5350' : '#26a69a'}
          />
          <BracketRow
            label="BOS"
            val={indicators.bos.bosEvents.length > 0
              ? indicators.bos.bosEvents[indicators.bos.bosEvents.length - 1].type.toUpperCase()
              : 'NONE'}
          />
        </div>
      </div>
    </div>
  );
}

function BracketRow({ label, val, color = '#e6edf3' }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0' }}>
      <span style={{ color: '#8b949e' }}>{label}</span>
      <span style={{ color }}>{val}</span>
    </div>
  );
}

const styles = {
  panel:  { display: 'flex', flexDirection: 'column', gap: 0, background: '#0d1117', height: '100%', overflow: 'auto' },
  header: { color: '#8b949e', fontSize: 10, letterSpacing: 2, padding: '8px 12px 4px', borderBottom: '1px solid #21262d' },
  section: { padding: '10px 12px', borderBottom: '1px solid #21262d' },
  label:   { color: '#8b949e', fontSize: 10, letterSpacing: 1, textTransform: 'uppercase' },
  contractBtn: {
    border: '1px solid', borderRadius: 4, background: 'transparent',
    color: '#e6edf3', fontSize: 13, fontWeight: 'bold', padding: '6px 14px', cursor: 'pointer',
  },
  tradeBtn: {
    border: 'none', borderRadius: 4, color: '#fff', fontWeight: 'bold',
    fontSize: 13, padding: '10px 0', cursor: 'pointer', textAlign: 'center',
  },
  lockMsg: { color: '#ef5350', fontSize: 11, marginTop: 6 },
  posGrid: { marginTop: 6, display: 'flex', flexDirection: 'column', gap: 2 },
  posRow:  { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  posLabel: { color: '#8b949e', fontSize: 11 },
  posVal:   { color: '#e6edf3', fontSize: 11, fontWeight: 600 },
  configGrid: { marginTop: 4 },
};
