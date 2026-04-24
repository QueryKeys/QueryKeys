/**
 * RSI – Relative Strength Index (Wilder's smoothed method)
 *
 * Formula:
 *   RS  = AvgGain / AvgLoss   (Wilder EMA, period = 14)
 *   RSI = 100 - 100 / (1 + RS)
 *
 * The first value uses a simple average for the seed; subsequent values
 * use the Wilder smoothing: avgGain = (prevAvgGain × (n-1) + gain) / n
 *
 * Returns a series of { time, value } for the Lightweight Charts line series.
 */

/**
 * @param {object[]} bars     – OHLCV bars (need at least period+1)
 * @param {number}   period   – RSI period (default 14)
 * @returns {{ time: number, value: number }[]}
 */
export function computeRsiSeries(bars, period = 14) {
  if (bars.length < period + 1) return [];

  const closes = bars.map(b => b.close);
  const series = [];

  // ── Seed: simple average of first `period` up/down moves ──────────────────
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta > 0) avgGain += delta;
    else           avgLoss += Math.abs(delta);
  }
  avgGain /= period;
  avgLoss /= period;

  const rsiAt = (ag, al) => al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  series.push({ time: bars[period].time, value: parseFloat(rsiAt(avgGain, avgLoss).toFixed(2)) });

  // ── Wilder smoothing for remaining bars ────────────────────────────────────
  for (let i = period + 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain  = delta > 0 ? delta : 0;
    const loss  = delta < 0 ? Math.abs(delta) : 0;

    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;

    series.push({ time: bars[i].time, value: parseFloat(rsiAt(avgGain, avgLoss).toFixed(2)) });
  }

  return series;
}

/**
 * Current RSI scalar (last value).
 *
 * @param {object[]} bars
 * @param {number}   period
 * @returns {number | null}
 */
export function currentRsi(bars, period = 14) {
  const s = computeRsiSeries(bars, period);
  return s.length > 0 ? s[s.length - 1].value : null;
}
