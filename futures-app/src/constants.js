// ─── NQ E-mini Contract Specifications ───────────────────────────────────────
export const NQ_SPECS = {
  tickSize: 0.25,     // 0.25 index points per tick
  tickValue: 5,       // $5 per tick (E-mini NQ)
  pointValue: 20,     // $20 per full point
  defaultSpread: 0.25,// typical 1-tick bid/ask spread
  startPrice: 20000,  // simulation starting price
};

// ─── Apex Trader Funding – 50K Account Rules ─────────────────────────────────
export const ACCOUNT_PARAMS = {
  startingBalance: 50000,
  // Trailing threshold: always $2,500 below the peak balance.
  // Stops trailing once balance hits $52,600 (the "lock" level).
  // After lock: drawdown floor is fixed at $50,100 ($52,600 - $2,500).
  trailingDrawdown: 2500,
  trailingLockLevel: 52600,
  lockedFloor: 50100,   // 52600 - 2500
  dailyLossLimit: 600,  // hard stop: -$600/day
  maxTradesPerDay: 3,
  maxConsecutiveLosses: 2,
};

// ─── Trade Sizing & Risk Rules ────────────────────────────────────────────────
export const TRADING_RULES = {
  normalContracts: 2,          // default contracts
  aplusContracts: 3,           // A+ setup max
  stopLossPoints: 10,          // 10 pts = 40 ticks
  tp1Points: 15,               // TP1: 15 points
  tp1CloseRatio: 0.5,          // TP1 closes 50% (floor)
  tp2Points: 25,               // TP2: remaining
  breakEvenTriggerPoints: 10,  // move SL to BE when +10 pts
  maxRiskPerTrade: 200,        // $200 max risk per trade
};

// ─── EST Session Times ────────────────────────────────────────────────────────
// Hours/minutes are in EST (the simulation clock is always EST)
export const SESSION_TIMES = {
  open:  { hour: 9,  minute: 30 },
  close: { hour: 16, minute: 0  },
  // Shaded green: "safe" trading windows
  safeWindows: [
    { start: { hour: 9,  minute: 30 }, end: { hour: 11, minute: 0  } },
    { start: { hour: 13, minute: 30 }, end: { hour: 15, minute: 0  } },
  ],
  // Red danger zones (user-configurable; FOMC/news times added separately)
  dangerZones: [
    { hour: 10, minute: 0,  durationMin: 5 },  // 10:00-10:05 (typical econ release)
    { hour: 8,  minute: 30, durationMin: 5 },  // 8:30 (jobs/CPI pre-market)
  ],
};

// ─── Chart / Visual Config ────────────────────────────────────────────────────
export const CHART_COLORS = {
  background: '#0d1117',
  grid: '#161b22',
  text: '#8b949e',
  upCandle: '#26a69a',
  downCandle: '#ef5350',
  vwap: '#f0b429',
  rsi: '#7c3aed',
  bosUp: '#00e676',
  bosDown: '#ff5252',
  safeWindow: 'rgba(38,166,154,0.07)',
  dangerZone: 'rgba(239,83,80,0.15)',
};

// ─── Default User Settings (persisted to localStorage) ────────────────────────
export const DEFAULT_SETTINGS = {
  speedMultiplier: 60,   // 1 min sim time = 1 sec wall clock (for testing)
  contracts: 2,
  rsiPeriod: 14,
  bosSwingLookback: 5,   // bars each side to confirm a swing high/low
  fomcDays: [],          // array of date strings "YYYY-MM-DD"
  newsDays: [],
};
