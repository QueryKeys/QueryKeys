/**
 * DepthHeatmap – Bookmap-style Canvas renderer
 * ─────────────────────────────────────────────
 * Architecture:
 *   • Off-screen canvas holds the historical heatmap columns (scrolling left)
 *   • Each tick, a new 1-pixel-wide column is appended on the right
 *   • Colors: bid liquidity = blue gradient, ask = red gradient
 *             intensity = log-scaled by size (larger orders = brighter)
 *   • Iceberg orders (size ≥ 100) rendered as bright bubbles
 *   • VWAP overlay drawn as a yellow line
 *   • Current bid/ask depth bars rendered on the far right
 *
 * Coordinate system:
 *   • Y-axis: price (high at top, low at bottom). Range = heatmap price window.
 *   • X-axis: time (newest on right, scrolls left).
 */

import React, { useRef, useEffect, useCallback } from 'react';
import useStore from '../store/useStore.js';

// Number of time columns kept in the heatmap buffer
const HISTORY_COLS = 600;
// Price levels shown above/below current price
const PRICE_RANGE_TICKS = 80; // 80 ticks = 20 points each side
const TICK = 0.25;

export default function DepthHeatmap() {
  const canvasRef   = useRef(null);
  // Ring buffer: each entry is a column { price, bids, asks }
  const bufferRef   = useRef([]);
  const animFrameRef = useRef(null);

  const { orderBook, sim, indicators } = useStore();

  // ── Color helpers ────────────────────────────────────────────────────────

  /**
   * Map order book level size to a color channel intensity.
   * log(size+1)/log(maxSize+1) gives a 0–1 intensity.
   * Max reference size = 400 lots.
   */
  const sizeToIntensity = useCallback((size) => {
    const MAX = 400;
    return Math.min(1, Math.log(size + 1) / Math.log(MAX + 1));
  }, []);

  /** Bid level: blue spectrum. intensity 0→1 → dark blue → bright cyan */
  const bidColor = useCallback((intensity, isIceberg) => {
    if (isIceberg) return `rgba(0,230,255,0.95)`; // bright cyan for icebergs
    const b = Math.round(60  + intensity * 195); // 60-255 blue channel
    const g = Math.round(intensity * 120);
    return `rgba(0,${g},${b},${0.3 + intensity * 0.7})`;
  }, []);

  /** Ask level: red spectrum. intensity 0→1 → dark red → bright orange-red */
  const askColor = useCallback((intensity, isIceberg) => {
    if (isIceberg) return `rgba(255,80,0,0.95)`; // bright orange for icebergs
    const r = Math.round(80 + intensity * 175);
    const g = Math.round(intensity * 60);
    return `rgba(${r},${g},0,${0.3 + intensity * 0.7})`;
  }, []);

  // ── Push new column into ring buffer ─────────────────────────────────────
  useEffect(() => {
    if (!orderBook.bids.length) return;
    const col = {
      price:      sim.currentPrice,
      bids:       [...orderBook.bids],
      asks:       [...orderBook.asks],
      vwap:       indicators.vwap,
    };
    const buf = bufferRef.current;
    buf.push(col);
    if (buf.length > HISTORY_COLS) buf.shift();
  }, [orderBook, sim.currentPrice, indicators.vwap]);

  // ── Draw ─────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    animFrameRef.current = requestAnimationFrame(() => draw());
    return () => { if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current); };
  });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx    = canvas.getContext('2d');
    const W      = canvas.width;
    const H      = canvas.height;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, W, H);

    const buf         = bufferRef.current;
    if (buf.length === 0) return;

    const currentPrice = sim.currentPrice;
    const priceHigh    = currentPrice + PRICE_RANGE_TICKS * TICK;
    const priceLow     = currentPrice - PRICE_RANGE_TICKS * TICK;
    const priceRange   = priceHigh - priceLow;

    const depthBarW  = 60;  // right-side depth bar width
    const heatmapW   = W - depthBarW;
    const colW       = Math.max(1, heatmapW / HISTORY_COLS);

    // Helper: price → Y pixel
    const priceToY = (p) => H - ((p - priceLow) / priceRange) * H;
    const tickPx   = (TICK / priceRange) * H; // pixels per tick

    // ── Draw heatmap columns ───────────────────────────────────────────────
    buf.forEach((col, colIdx) => {
      const x = colIdx * colW;

      // Bids (below mid)
      for (const bid of col.bids) {
        if (bid.price < priceLow || bid.price > priceHigh) continue;
        const y  = priceToY(bid.price);
        const h  = Math.max(1, tickPx);
        const intensity = sizeToIntensity(bid.size);
        ctx.fillStyle = bidColor(intensity, bid.isIceberg);
        ctx.fillRect(x, y - h, colW, h);

        // Iceberg bubble
        if (bid.isIceberg) {
          ctx.beginPath();
          ctx.arc(x + colW / 2, y - h / 2, Math.min(colW * 2, 6), 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(0,230,255,0.9)';
          ctx.fill();
        }
      }

      // Asks (above mid)
      for (const ask of col.asks) {
        if (ask.price < priceLow || ask.price > priceHigh) continue;
        const y  = priceToY(ask.price);
        const h  = Math.max(1, tickPx);
        const intensity = sizeToIntensity(ask.size);
        ctx.fillStyle = askColor(intensity, ask.isIceberg);
        ctx.fillRect(x, y, colW, h);

        if (ask.isIceberg) {
          ctx.beginPath();
          ctx.arc(x + colW / 2, y + h / 2, Math.min(colW * 2, 6), 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255,80,0,0.9)';
          ctx.fill();
        }
      }

      // VWAP line
      if (col.vwap) {
        const vy = priceToY(col.vwap);
        ctx.fillStyle = 'rgba(240,180,41,0.8)';
        ctx.fillRect(x, vy - 1, colW, 2);
      }
    });

    // ── Current price line ────────────────────────────────────────────────
    const midY = priceToY(currentPrice);
    ctx.strokeStyle = '#e6edf3';
    ctx.lineWidth   = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(heatmapW, midY);
    ctx.stroke();
    ctx.setLineDash([]);

    // ── Right-side depth bars ─────────────────────────────────────────────
    const latestCol = buf[buf.length - 1];
    if (latestCol) {
      const maxCumSize = Math.max(
        ...(orderBook.cumulativeBids.map(l => l.cumSize) ?? [1]),
        ...(orderBook.cumulativeAsks.map(l => l.cumSize) ?? [1]),
        1,
      );

      // Background for depth section
      ctx.fillStyle = '#111';
      ctx.fillRect(heatmapW, 0, depthBarW, H);

      // Bids (blue bars, right half)
      for (const lvl of orderBook.cumulativeBids) {
        if (lvl.price < priceLow || lvl.price > priceHigh) continue;
        const y     = priceToY(lvl.price);
        const barW  = (lvl.size / maxCumSize) * (depthBarW / 2);
        ctx.fillStyle = 'rgba(0,120,255,0.7)';
        ctx.fillRect(heatmapW, y - tickPx, barW, tickPx);
      }

      // Asks (red bars, right half)
      for (const lvl of orderBook.cumulativeAsks) {
        if (lvl.price < priceLow || lvl.price > priceHigh) continue;
        const y     = priceToY(lvl.price);
        const barW  = (lvl.size / maxCumSize) * (depthBarW / 2);
        ctx.fillStyle = 'rgba(255,60,60,0.7)';
        ctx.fillRect(heatmapW + depthBarW / 2, y, barW, tickPx);
      }
    }

    // ── Price labels on left edge ─────────────────────────────────────────
    ctx.fillStyle = '#8b949e';
    ctx.font      = '10px Consolas, monospace';
    const labelStep = 5; // label every 5 points
    for (let p = Math.ceil(priceLow / labelStep) * labelStep; p <= priceHigh; p += labelStep) {
      const y = priceToY(p);
      ctx.fillText(p.toFixed(0), 2, y + 3);
    }

    // ── Axis label ────────────────────────────────────────────────────────
    ctx.fillStyle = '#8b949e';
    ctx.font      = '9px Consolas, monospace';
    ctx.fillText('DEPTH HEATMAP (Bookmap)', 40, 14);
    ctx.fillText('BID ←', heatmapW + 2, 12);
    ctx.fillText('→ ASK', heatmapW + 32, 12);
  }, [sim.currentPrice, orderBook, indicators.vwap, sizeToIntensity, bidColor, askColor]);

  return (
    <div style={styles.wrapper}>
      <canvas
        ref={canvasRef}
        style={styles.canvas}
        width={900}
        height={200}
      />
    </div>
  );
}

const styles = {
  wrapper: { background: '#0d1117', height: '100%', overflow: 'hidden', position: 'relative' },
  canvas:  { display: 'block', width: '100%', height: '100%' },
};
