// API client + shared types. Matches app/api/routes.py shapes.
const BASE = "/api";

export type StrategyInfo = { name: string; params: Record<string, number>; timeframe: string };
export type Trade = {
  symbol: string; strategy: string; side: string;
  entry_ts: string; exit_ts: string | null;
  entry_price: number; exit_price: number | null;
  quantity: number; leverage: number; pnl: number; fees: number; exit_reason: string; source: string;
};
export type Signal = { ts: string; symbol: string; strategy: string; side: string; price: number; reason: string };
export type Metrics = Record<string, number | string>;

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch(`${BASE}/health`).then(j<{ status: string }>),
  strategies: () => fetch(`${BASE}/strategies`).then(j<StrategyInfo[]>),
  trades: (limit = 100) => fetch(`${BASE}/trades?limit=${limit}`).then(j<Trade[]>),
  signals: (limit = 50) => fetch(`${BASE}/signals?limit=${limit}`).then(j<Signal[]>),
  positions: () => fetch(`${BASE}/positions`).then(j<any>),
  balance: () => fetch(`${BASE}/balance`).then(j<{ mode: string; equity: number | null; initial_capital: number; wallets?: any }>),
  download: (timeframe: string, days: number) =>
    fetch(`${BASE}/data/download`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timeframe, days }) }).then(j<{ rows: number }>),
  backtest: (body: any) =>
    fetch(`${BASE}/backtest`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then(j<{ metrics: Metrics; report: string; num_trades: number }>),
  optimize: (body: any) =>
    fetch(`${BASE}/optimize`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then(j<any>),
  setMode: (mode: string, confirm: boolean) =>
    fetch(`${BASE}/mode`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, confirm }) }).then(j<any>),
  kill: (on = true) =>
    fetch(`${BASE}/kill`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }) }).then(j<any>),
  trade: (body: any) =>
    fetch(`${BASE}/trade`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then(j<any>),
  engine: () => fetch(`${BASE}/engine`).then(j<any>),
  quote: () => fetch(`${BASE}/quote`).then(j<any>),
  setAuto: (on: boolean) =>
    fetch(`${BASE}/auto`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }) }).then(j<any>),
  setStrategy: (name: string) =>
    fetch(`${BASE}/strategy`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }) }).then(j<any>),
};

// helper: derive a synthetic equity curve for the dashboard when /backtest not run yet.
export function fmt(n: number, d = 2): string {
  if (!isFinite(n)) return String(n);
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}