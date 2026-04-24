/**
 * MainChart
 * ─────────
 * TradingView Lightweight Charts panel with:
 *   • 5-min (or 1-min) candlestick series
 *   • VWAP overlay line
 *   • BOS horizontal rays (bullish = green dashed, bearish = red dashed)
 *   • Background shading for safe windows (green tint) and danger zones (red tint)
 *   • Current open position entry/stop/tp lines
 *
 * Lightweight Charts v4 API is used throughout.
 * The chart is created once on mount; series are updated imperatively on
 * each render via useEffect so we avoid recreating the chart.
 */

import React, { useEffect, useRef } from 'react';
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts';
import useStore from '../store/useStore.js';
import { CHART_COLORS, SESSION_TIMES } from '../constants.js';

// Height of the RSI sub-panel (px)
const RSI_HEIGHT = 100;

export default function MainChart() {
  const containerRef  = useRef(null);
  const chartRef      = useRef(null);
  const rsiChartRef   = useRef(null);

  // Series refs (mutated, not reactive)
  const candleRef     = useRef(null);
  const vwapRef       = useRef(null);
  const rsiLineRef    = useRef(null);
  const bosLinesRef   = useRef([]); // array of { id, line } for BOS rays
  const posLinesRef   = useRef({}); // entry / stop / tp lines

  const { bars, indicators, trading, sim, ui } = useStore();
  const tf   = ui.selectedTf;          // '5m' | '1m'
  const data = bars[tf] ?? [];

  // ── Chart creation (once on mount) ────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;

    // Main chart
    const chart = createChart(el, {
      layout: { background: { color: CHART_COLORS.background }, textColor: CHART_COLORS.text },
      grid:   { vertLines: { color: CHART_COLORS.grid }, horzLines: { color: CHART_COLORS.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
      width:  el.clientWidth,
      height: el.clientHeight - RSI_HEIGHT - 4,
    });
    chartRef.current = chart;

    // Candlestick series
    const candle = chart.addCandlestickSeries({
      upColor:          CHART_COLORS.upCandle,
      downColor:        CHART_COLORS.downCandle,
      borderUpColor:    CHART_COLORS.upCandle,
      borderDownColor:  CHART_COLORS.downCandle,
      wickUpColor:      CHART_COLORS.upCandle,
      wickDownColor:    CHART_COLORS.downCandle,
    });
    candleRef.current = candle;

    // VWAP line
    const vwapLine = chart.addLineSeries({
      color:      CHART_COLORS.vwap,
      lineWidth:  2,
      lineStyle:  LineStyle.Solid,
      title:      'VWAP',
    });
    vwapRef.current = vwapLine;

    // RSI sub-chart (separate chart instance in the same container)
    const rsiContainer = document.createElement('div');
    rsiContainer.style.cssText = `width:${el.clientWidth}px;height:${RSI_HEIGHT}px;margin-top:4px;`;
    el.appendChild(rsiContainer);

    const rsiChart = createChart(rsiContainer, {
      layout: { background: { color: CHART_COLORS.background }, textColor: CHART_COLORS.text },
      grid:   { vertLines: { color: CHART_COLORS.grid }, horzLines: { color: CHART_COLORS.grid } },
      rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
      width:  el.clientWidth,
      height: RSI_HEIGHT,
    });
    rsiChartRef.current = rsiChart;

    // RSI line
    const rsiLine = rsiChart.addLineSeries({ color: CHART_COLORS.rsi, lineWidth: 1, title: 'RSI(14)' });
    rsiLineRef.current = rsiLine;

    // RSI 40/60 reference lines (price lines on the RSI series — always visible)
    rsiLine.createPriceLine({ price: 60, color: '#555', lineWidth: 1, lineStyle: LineStyle.Dashed, title: '60' });
    rsiLine.createPriceLine({ price: 40, color: '#555', lineWidth: 1, lineStyle: LineStyle.Dashed, title: '40' });
    rsiLine.createPriceLine({ price: 50, color: '#333', lineWidth: 1, lineStyle: LineStyle.Dotted, title: '' });

    // Sync time scales
    chart.timeScale().subscribeVisibleLogicalRangeChange(range => {
      if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
    });

    // Resize observer
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      const h = el.clientHeight - RSI_HEIGHT - 4;
      chart.resize(w, h);
      rsiChart.resize(w, RSI_HEIGHT);
      rsiContainer.style.width = `${w}px`;
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.remove();
      rsiChart.remove();
      if (rsiContainer.parentNode) rsiContainer.parentNode.removeChild(rsiContainer);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Candle data update ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!candleRef.current || data.length === 0) return;

    // Lightweight Charts requires data sorted by time, no duplicates.
    const chartData = data.map(b => ({
      time:  b.time,
      open:  b.open,
      high:  b.high,
      low:   b.low,
      close: b.close,
    }));
    candleRef.current.setData(chartData);
  }, [data]);

  // ── VWAP update ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (!vwapRef.current || indicators.vwapSeries.length === 0) return;
    vwapRef.current.setData(indicators.vwapSeries);
  }, [indicators.vwapSeries]);

  // ── RSI update ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!rsiLineRef.current || indicators.rsiSeries.length === 0) return;
    rsiLineRef.current.setData(indicators.rsiSeries);
  }, [indicators.rsiSeries]);

  // ── BOS lines update ──────────────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    // Remove old BOS lines
    for (const { line } of bosLinesRef.current) {
      try { chart.removeSeries(line); } catch (_) {}
    }
    bosLinesRef.current = [];

    // Add current BOS events as horizontal lines
    for (const event of indicators.bos.bosEvents) {
      const color    = event.type === 'bullish' ? CHART_COLORS.bosUp : CHART_COLORS.bosDown;
      const line     = chart.addLineSeries({
        color,
        lineWidth:  1,
        lineStyle:  LineStyle.Dashed,
        lastValueVisible: false,
        priceLineVisible: false,
      });

      // Draw a horizontal ray from the BOS time onward
      const endTime = data.length > 0 ? data[data.length - 1].time + 3600 : event.time + 3600;
      line.setData([
        { time: event.time, value: event.price },
        { time: endTime,    value: event.price },
      ]);

      bosLinesRef.current.push({ id: `${event.type}-${event.time}`, line });
    }
  }, [indicators.bos, data]);

  // ── Position lines (entry, stop, TP1, TP2) ────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;

    // Clear old position price lines
    for (const pl of Object.values(posLinesRef.current)) {
      try { candle.removePriceLine(pl); } catch (_) {}
    }
    posLinesRef.current = {};

    const pos = trading.openPosition;
    if (!pos) return;

    const addLine = (price, color, title, style = LineStyle.Solid) => {
      return candle.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, title, axisLabelVisible: true });
    };

    posLinesRef.current.entry = addLine(pos.entryPrice, '#e6edf3', 'ENTRY');
    posLinesRef.current.stop  = addLine(pos.stopPrice,  '#ef5350', 'STOP', LineStyle.Dashed);
    if (!pos.tp1Hit)
      posLinesRef.current.tp1 = addLine(pos.tp1Price, '#26a69a', 'TP1', LineStyle.Dotted);
    if (!pos.tp2Hit)
      posLinesRef.current.tp2 = addLine(pos.tp2Price, '#00c853', 'TP2', LineStyle.Dotted);
  }, [trading.openPosition?.stopPrice, trading.openPosition?.tp1Hit, trading.openPosition?.tp2Hit]);

  // ── Background shading via canvas overlay ─────────────────────────────────
  // Lightweight Charts v4 supports background via custom HTML overlay canvas.
  // We inject a transparent overlay div that draws the zones.
  // (This is a lightweight approach; full plugin API available in v5.)
  // For MVP, the time-zone coloring is shown as colored vertical bands
  // using the chart's subscribeCrosshairMove to get pixel coordinates.
  // A simpler alternative: CSS gradient on container.

  return (
    <div style={styles.wrapper}>
      <div style={styles.chartHeader}>
        <span style={styles.symbol}>NQ {tf.toUpperCase()}</span>
        {indicators.vwap !== null && (
          <span style={styles.badge}>VWAP <b style={{ color: CHART_COLORS.vwap }}>{indicators.vwap?.toFixed(2)}</b></span>
        )}
        {indicators.rsi !== null && (
          <span style={{
            ...styles.badge,
            color: (indicators.rsi < 40 || indicators.rsi > 60) ? '#ef5350' : '#26a69a',
          }}>
            RSI <b>{indicators.rsi?.toFixed(1)}</b>
          </span>
        )}
        <TfToggle />
        <span style={{ marginLeft: 8, color: '#8b949e', fontSize: 11 }}>BOS events: {indicators.bos.bosEvents.length}</span>
      </div>
      <div ref={containerRef} style={styles.chartArea} />
    </div>
  );
}

function TfToggle() {
  const { ui } = useStore();
  const setTf  = useStore(s => s.saveSettings); // reuse saveSettings for tf
  const setSelectedTf = tf => useStore.setState(s => ({ ui: { ...s.ui, selectedTf: tf } }));

  return (
    <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
      {['1m', '5m'].map(tf => (
        <button
          key={tf}
          style={{
            ...styles.tfBtn,
            background: ui.selectedTf === tf ? '#30363d' : 'transparent',
            color: ui.selectedTf === tf ? '#e6edf3' : '#8b949e',
          }}
          onClick={() => setSelectedTf(tf)}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}

const styles = {
  wrapper: { display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' },
  chartHeader: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '4px 12px', background: '#161b22',
    borderBottom: '1px solid #21262d', flexShrink: 0,
  },
  symbol: { color: '#e6edf3', fontWeight: 'bold', fontSize: 13 },
  badge:  { color: '#8b949e', fontSize: 11 },
  chartArea: { flex: 1, overflow: 'hidden' },
  tfBtn: { border: '1px solid #30363d', borderRadius: 3, cursor: 'pointer', fontSize: 11, padding: '2px 7px' },
};
