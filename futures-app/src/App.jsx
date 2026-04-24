/**
 * App – Root component + layout
 *
 * Layout (CSS Grid):
 *
 *   ┌─────────────────────────────────────────────────────┐
 *   │                    TOP BAR (44px)                   │
 *   ├────────────────────────────┬────────────────────────┤
 *   │                            │  ORDER PANEL  (240px)  │
 *   │   MAIN CHART               ├────────────────────────┤
 *   │   (flex, fills height)     │  CHECKLIST    (fills)  │
 *   │                            │                        │
 *   ├────────────────────────────┼────────────────────────┤
 *   │   DEPTH HEATMAP (200px)    │  TRADE LOG    (200px)  │
 *   └────────────────────────────┴────────────────────────┘
 *
 * Global hotkeys:
 *   Ctrl+B  → Long entry
 *   Ctrl+S  → Short entry
 *   Ctrl+F  → Flatten all
 *   Space   → Start / Pause simulation
 */

import React, { useEffect } from 'react';
import useStore from './store/useStore.js';
import TopBar        from './components/TopBar.jsx';
import MainChart     from './components/MainChart.jsx';
import OrderPanel    from './components/OrderPanel.jsx';
import ChecklistPanel from './components/ChecklistPanel.jsx';
import DepthHeatmap  from './components/DepthHeatmap.jsx';
import TradeLog      from './components/TradeLog.jsx';

export default function App() {
  const { startSim, pauseSim, sim, enterTrade, flattenAll } = useStore();

  // ── Global hotkeys ─────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      // Ignore when typing in an input/select
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;

      if (e.ctrlKey && e.key === 'b') { e.preventDefault(); enterTrade('long'); }
      if (e.ctrlKey && e.key === 's') { e.preventDefault(); enterTrade('short'); }
      if (e.ctrlKey && e.key === 'f') { e.preventDefault(); flattenAll(); }
      if (e.code === 'Space')          { e.preventDefault(); sim.running ? pauseSim() : startSim(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sim.running, enterTrade, flattenAll, startSim, pauseSim]);

  return (
    <div style={styles.root}>
      {/* Top bar */}
      <div style={styles.topBar}>
        <TopBar />
      </div>

      {/* Main content area */}
      <div style={styles.body}>

        {/* Left: chart + heatmap stacked */}
        <div style={styles.left}>
          <div style={styles.chartArea}>
            <MainChart />
          </div>
          <div style={styles.heatmapArea}>
            <DepthHeatmap />
          </div>
        </div>

        {/* Right: order panel + checklist + trade log stacked */}
        <div style={styles.right}>
          <div style={styles.orderArea}>
            <OrderPanel />
          </div>
          <div style={styles.checklistArea}>
            <ChecklistPanel />
          </div>
          <div style={styles.logArea}>
            <TradeLog />
          </div>
        </div>
      </div>

      {/* Blown-up overlay */}
      <BlownOverlay />
    </div>
  );
}

/** Full-screen warning when account is blown */
function BlownOverlay() {
  const blown = useStore(s => s.ui.blown);
  if (!blown) return null;
  return (
    <div style={styles.blownOverlay}>
      <div style={styles.blownBox}>
        <div style={{ fontSize: 48 }}>💥</div>
        <div style={{ color: '#ef5350', fontSize: 28, fontWeight: 'bold', marginTop: 12 }}>ACCOUNT BLOWN</div>
        <div style={{ color: '#8b949e', marginTop: 8 }}>Balance reached the trailing drawdown floor.</div>
        <div style={{ color: '#8b949e', marginTop: 4, fontSize: 12 }}>Refresh the page to reset the simulation.</div>
      </div>
    </div>
  );
}

// ─── Layout styles ────────────────────────────────────────────────────────────

const styles = {
  root: {
    width: '100vw', height: '100vh',
    display: 'flex', flexDirection: 'column',
    background: '#0d1117', overflow: 'hidden',
  },
  topBar: { flexShrink: 0 },
  body: {
    flex: 1, display: 'flex', overflow: 'hidden',
    minHeight: 0,
  },

  // Left column: chart (flex) + heatmap (fixed)
  left: { flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflow: 'hidden' },
  chartArea: {
    flex: 1, minHeight: 0, borderRight: '1px solid #21262d', overflow: 'hidden',
  },
  heatmapArea: {
    height: 210, flexShrink: 0,
    borderTop: '1px solid #21262d', borderRight: '1px solid #21262d',
    overflow: 'hidden',
  },

  // Right column: order (auto) + checklist (flex) + log (fixed)
  right: {
    width: 240, flexShrink: 0,
    display: 'flex', flexDirection: 'column',
    borderLeft: '1px solid #21262d', overflow: 'hidden',
  },
  orderArea:     { flexShrink: 0, borderBottom: '1px solid #21262d' },
  checklistArea: { flex: 1, minHeight: 0, overflow: 'auto', borderBottom: '1px solid #21262d' },
  logArea:       { height: 220, flexShrink: 0, overflow: 'hidden' },

  blownOverlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.88)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 9999,
  },
  blownBox: {
    background: '#161b22', border: '2px solid #ef5350', borderRadius: 12,
    padding: '40px 60px', textAlign: 'center',
  },
};
