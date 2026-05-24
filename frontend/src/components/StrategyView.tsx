"use client";

import { useMemo, useState } from "react";
import {
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface NavPoint {
  date: string;
  nav: number;
}

interface Props {
  navHistory: NavPoint[];
  fundCode: string;
}

interface SimDay {
  date: string;
  nav: number;
  equity: number;
  baseline: number;
  drawdown: number;
  signal: number;
  position: number;
  momentum: number;
  ma60: number;
  cash: number;
  shares: number;
  marketValue: number;
}

interface Trade {
  date: string;
  action: string;
  nav: number;
  amount: number;
  shares: number;
  cash: number;
  equity: number;
  reason: string;
}

// ========== 策略参数 ==========
const INITIAL_CAPITAL = 1000000;
const MOMENTUM_PERIOD = 21;
const ATR_PERIOD = 20;
const MA_PERIOD = 60;
const POS_FULL = 0.8;
const POS_HALF = 0.4;
const STRONG_SIGNAL = 0.05;
const STOP_SOFT = 0.03;
const STOP_HARD = 0.05;
const COOLDOWN_DAYS = 5;
// ==============================

function simulate(navHistory: NavPoint[]) {
  const minLen = Math.max(MOMENTUM_PERIOD, MA_PERIOD) + 1;
  if (navHistory.length < minLen) return null;

  const navs = navHistory.map((p) => p.nav);
  const dates = navHistory.map((p) => p.date);

  const dailyRet: number[] = [];
  for (let i = 1; i < navs.length; i++) {
    dailyRet.push((navs[i] - navs[i - 1]) / navs[i - 1]);
  }
  const trueRanges = dailyRet.map((r, i) => Math.abs(r) * navs[i + 1]);

  const result: SimDay[] = [];
  const trades: Trade[] = [];

  let cash = INITIAL_CAPITAL;
  let shares = 0;
  let position = 0;
  let cooldown = 0;
  const startIdx = Math.max(MOMENTUM_PERIOD, MA_PERIOD);

  function equity() {
    return cash + shares * navs[result.length + startIdx] || cash;
  }

  for (let i = startIdx; i < navs.length; i++) {
    const nav = navs[i];
    const momentum = navs[i] / navs[i - MOMENTUM_PERIOD] - 1;

    let atr = 0;
    if (i >= ATR_PERIOD) {
      const slice = trueRanges.slice(i - ATR_PERIOD, i);
      atr = slice.reduce((a, b) => a + b, 0) / slice.length;
    }

    const maSlice = navs.slice(i - MA_PERIOD + 1, i + 1);
    const ma60 = maSlice.reduce((a, b) => a + b, 0) / maSlice.length;
    const signal = momentum * (atr / nav);
    const baseline = INITIAL_CAPITAL * (navs[i] / navs[startIdx]);

    const currentEquity = cash + shares * nav;
    const peakEquity = result.length > 0
      ? Math.max(...result.map((d) => d.equity), currentEquity)
      : currentEquity;
    const drawdown = (peakEquity - currentEquity) / peakEquity;

    const prevPosition = position;
    let action = "";

    // ---- 阶梯止损 ----
    if (drawdown >= STOP_HARD && position > 0) {
      action = "止损清仓";
      const sellAmount = shares * nav;
      const sellShares = shares;
      cash += sellAmount;
      shares = 0;
      position = 0;
      cooldown = COOLDOWN_DAYS;
      trades.push({ date: dates[i], action, nav, amount: Math.round(sellAmount), shares: Math.round(sellShares * 10000) / 10000, cash: Math.round(cash), equity: Math.round(cash), reason: `回撤${pct(drawdown)}触及5%硬止损` });
    } else if (drawdown >= STOP_SOFT && position > POS_HALF) {
      action = "止损减仓";
      const targetValue = currentEquity * POS_HALF;
      const currentValue = shares * nav;
      const sellValue = currentValue - targetValue;
      const sellShares = sellValue / nav;
      cash += sellValue;
      shares -= sellShares;
      position = POS_HALF;
      trades.push({ date: dates[i], action, nav, amount: Math.round(sellValue), shares: Math.round(sellShares * 10000) / 10000, cash: Math.round(cash), equity: Math.round(cash + shares * nav), reason: `回撤${pct(drawdown)}触及3%软止损` });
    }

    // ---- 冷却期 ----
    if (cooldown > 0) {
      cooldown--;
    } else if (action === "") {
      // ---- 正常信号 ----
      const aboveMA = nav > ma60;
      let targetPos = 0;
      if (signal > STRONG_SIGNAL && aboveMA) targetPos = POS_FULL;
      else if (signal > 0 && aboveMA) targetPos = POS_HALF;

      if (targetPos !== position) {
        const eq = cash + shares * nav;
        const targetValue = eq * targetPos;
        const currentMV = shares * nav;
        const diff = targetValue - currentMV;

        if (diff > 0) {
          // 加仓：用现金买份额
          const buyShares = diff / nav;
          action = position === 0 ? "建仓" : "加仓";
          cash -= diff;
          shares += buyShares;
          trades.push({ date: dates[i], action, nav, amount: Math.round(diff), shares: Math.round(buyShares * 10000) / 10000, cash: Math.round(cash), equity: Math.round(cash + shares * nav), reason: `S=${signal.toFixed(4)}, ${aboveMA ? "价格>MA60" : "价格<MA60"}` });
        } else {
          // 减仓：卖出份额换现金
          const sellValue = Math.abs(diff);
          const sellShares = sellValue / nav;
          action = targetPos === 0 ? "清仓" : "减仓";
          cash += sellValue;
          shares -= sellShares;
          trades.push({ date: dates[i], action, nav, amount: Math.round(sellValue), shares: Math.round(sellShares * 10000) / 10000, cash: Math.round(cash), equity: Math.round(cash + shares * nav), reason: `S=${signal.toFixed(4)}≤0` });
        }
        position = targetPos;
      }
    }

    const marketValue = shares * nav;
    result.push({
      date: dates[i],
      nav,
      equity: Math.round((cash + marketValue) * 100) / 100,
      baseline: Math.round(baseline * 100) / 100,
      drawdown,
      signal,
      position,
      momentum,
      ma60,
      cash: Math.round(cash * 100) / 100,
      shares: Math.round(shares * 10000) / 10000,
      marketValue: Math.round(marketValue * 100) / 100,
    });
  }

  return { days: result, trades };
}

function pct(v: number) {
  return (v * 100).toFixed(2) + "%";
}

function fmt(v: number) {
  return v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function computeStats(days: SimDay[], trades: Trade[]) {
  if (days.length < 2) return null;
  const tradingDays = days.length;
  const years = tradingDays / 252;
  const totalReturn = (days[days.length - 1].equity - INITIAL_CAPITAL) / INITIAL_CAPITAL;
  const annualReturn = years > 0 ? Math.pow(1 + totalReturn, 1 / years) - 1 : 0;

  let maxDD = 0, ddStart = days[0].date, ddEnd = days[0].date, peak = INITIAL_CAPITAL, peakDate = days[0].date;
  for (const d of days) {
    if (d.equity > peak) { peak = d.equity; peakDate = d.date; }
    const dd = (peak - d.equity) / peak;
    if (dd > maxDD) { maxDD = dd; ddStart = peakDate; ddEnd = d.date; }
  }

  const dailyReturns: number[] = [];
  for (let i = 1; i < days.length; i++) {
    dailyReturns.push((days[i].equity - days[i - 1].equity) / days[i - 1].equity);
  }
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
  const variance = dailyReturns.reduce((a, r) => a + (r - mean) ** 2, 0) / (dailyReturns.length - 1);
  const stdDev = Math.sqrt(variance);
  const sharpe = stdDev > 0 ? ((annualReturn - 0.025) / (stdDev * Math.sqrt(252))) : 0;

  const roundTrips: number[] = [];
  let entryNav = 0, inTrade = false;
  for (const t of trades) {
    if ((t.action === "建仓" || t.action === "加仓") && !inTrade) { entryNav = t.nav; inTrade = true; }
    if ((t.action === "清仓" || t.action === "止损清仓") && inTrade) { roundTrips.push((t.nav - entryNav) / entryNav); inTrade = false; }
  }
  const wins = roundTrips.filter((r) => r > 0);
  const losses = roundTrips.filter((r) => r <= 0);
  const winRate = roundTrips.length > 0 ? wins.length / roundTrips.length : 0;
  const avgWin = wins.length > 0 ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
  const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length) : 0;
  const profitLossRatio = avgLoss > 0 ? avgWin / avgLoss : avgWin > 0 ? Infinity : 0;
  const baselineReturn = (days[days.length - 1].baseline - INITIAL_CAPITAL) / INITIAL_CAPITAL;

  return { totalReturn, annualReturn, maxDD, ddStart, ddEnd, sharpe, tradingDays, winRate, profitLossRatio, tradeCount: trades.length, baselineReturn };
}

export default function StrategyView({ navHistory, fundCode }: Props) {
  const sim = useMemo(() => simulate(navHistory), [navHistory]);

  if (!sim) {
    return (
      <div style={{ color: "var(--text-secondary)", textAlign: "center", padding: 40 }}>
        净值数据不足，需要至少 {Math.max(MOMENTUM_PERIOD, MA_PERIOD) + 1} 个交易日
      </div>
    );
  }

  const { days, trades } = sim;
  const latest = days[days.length - 1];
  const stats = computeStats(days, trades)!;

  const isBullish = latest.signal > 0 && latest.nav > latest.ma60;
  const stopped = latest.position === 0 && latest.drawdown >= STOP_SOFT;
  const inCooldown = latest.position === 0 && latest.signal > 0 && latest.drawdown < STOP_SOFT;

  const maxPoints = 300;
  let chartData = days;
  if (days.length > maxPoints) {
    const step = Math.ceil(days.length / maxPoints);
    chartData = days.filter((_, i) => i % step === 0);
    if (chartData[chartData.length - 1].date !== latest.date) chartData.push(latest);
  }

  let advice = "";
  if (stopped) advice = `已触发止损（回撤 ${pct(latest.drawdown)}），强制空仓。等待冷却期结束且信号转正。`;
  else if (inCooldown) advice = `冷却期中，暂不开仓。信号 S=${latest.signal.toFixed(4)}>0 但需等待确认。`;
  else if (isBullish) {
    if (latest.signal > STRONG_SIGNAL && latest.nav > latest.ma60) advice = `强信号 S=${latest.signal.toFixed(4)}>${STRONG_SIGNAL}，价格站上MA60，维持 80% 满仓。`;
    else advice = `中等信号 S=${latest.signal.toFixed(4)}，价格站上MA60，维持 40% 半仓。`;
  } else {
    if (latest.signal <= 0) advice = `信号 S=${latest.signal.toFixed(4)}≤0，空仓观望。`;
    else advice = `信号 S=${latest.signal.toFixed(4)}>0 但价格低于MA60，不满足开仓条件。`;
  }

  return (
    <div>
      {/* 标题 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>动量×波动率 · MA60趋势过滤 · 阶梯止损 · {fundCode}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: "var(--accent)" }}>策略回测仪表盘</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>最新交易日</div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{latest.date}</div>
        </div>
      </div>

      {/* ===== AI 今日决策 ===== */}
      <div className="strat-holding-card" style={{ marginBottom: 16 }}>
        <div className="strat-holding-header">
          <span className="strat-holding-tag" style={{ background: "var(--accent)", color: "white" }}>AI 今日决策</span>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{fundCode} · {latest.date}</span>
        </div>
        <div className="strat-holding-grid">
          <div>
            <div className="strat-holding-label">今日净值</div>
            <div className="strat-holding-value">{latest.nav.toFixed(4)}</div>
          </div>
          <div>
            <div className="strat-holding-label">今日收益</div>
            <div className={`strat-holding-value ${latest.nav > (days.length > 1 ? days[days.length - 2].nav : latest.nav) ? "positive" : "negative"}`}>
              {days.length > 1 ? (
                <>
                  {((latest.nav - days[days.length - 2].nav) / days[days.length - 2].nav * 100).toFixed(2)}%
                </>
              ) : "N/A"}
            </div>
          </div>
          <div>
            <div className="strat-holding-label">今日盈亏</div>
            <div className={`strat-holding-value ${latest.equity > (days.length > 1 ? days[days.length - 2].equity : latest.equity) ? "positive" : "negative"}`}>
              {days.length > 1 ? (
                <>
                  {latest.equity > days[days.length - 2].equity ? "+" : ""}
                  ¥{fmt(latest.equity - days[days.length - 2].equity)}
                </>
              ) : "N/A"}
            </div>
          </div>
          <div>
            <div className="strat-holding-label">AI 决策</div>
            <div className="strat-holding-value" style={{
              color: stopped ? "var(--red)" : inCooldown ? "var(--gold)" : isBullish ? "var(--green)" : "var(--text-secondary)",
              fontWeight: 700
            }}>
              {stopped ? "止损" : inCooldown ? "冷却" : isBullish ? "看多" : "看空"}
            </div>
          </div>
          <div>
            <div className="strat-holding-label">信号强度</div>
            <div className="strat-holding-value" style={{
              color: latest.signal > STRONG_SIGNAL ? "var(--green)" : latest.signal > 0 ? "var(--gold)" : "var(--red)"
            }}>
              {latest.signal.toFixed(4)}
            </div>
          </div>
          <div>
            <div className="strat-holding-label">建议仓位</div>
            <div className="strat-holding-value" style={{
              color: latest.position > 0 ? "var(--green)" : "var(--text-secondary)",
              fontWeight: 700
            }}>
              {pct(latest.position)}
            </div>
          </div>
        </div>
        {/* AI 决策依据 */}
        <div style={{
          marginTop: 12,
          padding: "10px 12px",
          background: "rgba(255,255,255,0.03)",
          borderRadius: 8,
          fontSize: 13,
          color: "var(--text-secondary)",
          borderLeft: `3px solid ${stopped ? "var(--red)" : inCooldown ? "var(--gold)" : isBullish ? "var(--green)" : "var(--text-secondary)"}`
        }}>
          <strong>决策依据：</strong>{advice}
        </div>
      </div>

      {/* ===== AI 当前持仓 ===== */}
      <div className="strat-holding-card">
        <div className="strat-holding-header">
          <span className="strat-holding-tag">{latest.position > 0 ? "持仓中" : "空仓"}</span>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>{fundCode}</span>
        </div>
        <div className="strat-holding-grid">
          <div>
            <div className="strat-holding-label">持有份额</div>
            <div className="strat-holding-value">{latest.shares.toFixed(4)} 份</div>
          </div>
          <div>
            <div className="strat-holding-label">当前净值</div>
            <div className="strat-holding-value">{latest.nav.toFixed(4)}</div>
          </div>
          <div>
            <div className="strat-holding-label">持仓市值</div>
            <div className="strat-holding-value" style={{ color: "var(--green)" }}>¥{fmt(latest.marketValue)}</div>
          </div>
          <div>
            <div className="strat-holding-label">现金余额</div>
            <div className="strat-holding-value">¥{fmt(latest.cash)}</div>
          </div>
          <div>
            <div className="strat-holding-label">账户总权益</div>
            <div className="strat-holding-value" style={{ color: "var(--accent)", fontSize: 18 }}>¥{fmt(latest.equity)}</div>
          </div>
          <div>
            <div className="strat-holding-label">累计收益</div>
            <div className={`strat-holding-value ${stats.totalReturn >= 0 ? "positive" : "negative"}`}>
              {stats.totalReturn >= 0 ? "+" : ""}{pct(stats.totalReturn)}
            </div>
          </div>
        </div>
      </div>

      {/* 回测统计 */}
      <div className="strat-stats-grid">
        <div className="strat-metric-card">
          <div className="strat-metric-label">策略年化</div>
          <div className={`strat-metric-value ${stats.annualReturn >= 0 ? "positive" : "negative"}`}>{stats.annualReturn >= 0 ? "+" : ""}{pct(stats.annualReturn)}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">基准年化(持有)</div>
          <div className={`strat-metric-value ${stats.baselineReturn >= 0 ? "positive" : "negative"}`}>{pct(stats.baselineReturn / (stats.tradingDays / 252))}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">最大回撤</div>
          <div className="strat-metric-value negative">-{pct(stats.maxDD)}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">夏普比率</div>
          <div className={`strat-metric-value ${stats.sharpe >= 1 ? "positive" : stats.sharpe >= 0 ? "" : "negative"}`}>{stats.sharpe.toFixed(2)}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">胜率</div>
          <div className="strat-metric-value" style={{ color: stats.winRate >= 0.5 ? "var(--green)" : "var(--gold)" }}>{pct(stats.winRate)}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">盈亏比</div>
          <div className="strat-metric-value" style={{ color: stats.profitLossRatio >= 1 ? "var(--green)" : "var(--red)" }}>{stats.profitLossRatio === Infinity ? "∞" : stats.profitLossRatio.toFixed(2)}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">交易次数</div>
          <div className="strat-metric-value" style={{ color: "var(--text-primary)" }}>{stats.tradeCount}</div>
        </div>
        <div className="strat-metric-card">
          <div className="strat-metric-label">vs 基准超额</div>
          <div className={`strat-metric-value ${stats.totalReturn > stats.baselineReturn ? "positive" : "negative"}`}>{stats.totalReturn > stats.baselineReturn ? "+" : ""}{pct(stats.totalReturn - stats.baselineReturn)}</div>
        </div>
      </div>

      {/* 信号面板 */}
      <div className="strat-signal-panel">
        <div className="strat-signal-grid">
          <div className="strat-signal-item">
            <div className="strat-metric-label">信号 S</div>
            <div className={`strat-signal-value ${latest.signal > 0 ? "positive" : "negative"}`}>{latest.signal > 0 ? "+" : ""}{latest.signal.toFixed(4)}</div>
            <div className="strat-signal-sub">{latest.signal > STRONG_SIGNAL ? "强信号" : latest.signal > 0 ? "中等信号" : "负信号"}</div>
          </div>
          <div className="strat-signal-item">
            <div className="strat-metric-label">MA60趋势</div>
            <div className={`strat-signal-value ${latest.nav > latest.ma60 ? "positive" : "negative"}`}>{latest.nav > latest.ma60 ? "上方" : "下方"}</div>
            <div className="strat-signal-sub">NAV {latest.nav.toFixed(4)} vs MA {latest.ma60.toFixed(4)}</div>
          </div>
          <div className="strat-signal-item">
            <div className="strat-metric-label">当前仓位</div>
            <div className="strat-signal-value" style={{ color: latest.position > 0 ? "var(--green)" : "var(--text-secondary)" }}>{pct(latest.position)}</div>
            <div className="strat-signal-sub">{latest.position > 0 ? `持仓 ¥${fmt(latest.marketValue)}` : "空仓"}</div>
          </div>
          <div className="strat-signal-item">
            <div className="strat-metric-label">止损状态</div>
            <div className={`strat-signal-value ${stopped ? "negative" : inCooldown ? "" : "positive"}`} style={inCooldown ? { color: "var(--gold)" } : {}}>{stopped ? "已触发" : inCooldown ? "冷却中" : "安全"}</div>
            <div className="strat-signal-sub">{stopped ? "强制清仓" : inCooldown ? "等待信号确认" : `距3%线 ${pct(STOP_SOFT - latest.drawdown)}`}</div>
          </div>
        </div>
      </div>

      {/* 明日预判 */}
      <div className={`strat-advice ${isBullish && !stopped && !inCooldown ? "strat-advice-bull" : stopped ? "strat-advice-stop" : "strat-advice-bear"}`}>
        <div className="strat-advice-title">明日预判</div>
        <div className="strat-advice-body">
          <span style={{ color: "var(--text-secondary)" }}>信号方向：</span>
          <span style={{ fontWeight: 600, color: isBullish && !stopped ? "var(--green)" : "var(--red)" }}>{stopped ? "止损中" : inCooldown ? "冷却期" : isBullish ? "偏多" : "偏空"}</span>
          <br />
          <span style={{ color: "var(--text-secondary)" }}>操作建议：</span>{advice}
          <br />
          <span style={{ color: "var(--text-secondary)" }}>回撤区间：</span>{stats.ddStart} 至 {stats.ddEnd}（最大 -{pct(stats.maxDD)}）
        </div>
      </div>

      {/* 权益曲线 */}
      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600, marginBottom: 12, borderLeft: "3px solid var(--accent)", paddingLeft: 8 }}>
          权益曲线 vs 基准（买入持有）
        </div>
        <div className="strat-chart-wrapper">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 60, left: 10, bottom: 10 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00d4aa" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#00d4aa" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6b7a99" }} tickFormatter={(v: string) => v.slice(0, 7)} interval="preserveStartEnd" />
              <YAxis yAxisId="eq" tick={{ fontSize: 11, fill: "#6b7a99" }} tickFormatter={(v: number) => (v / 10000).toFixed(0) + "万"} />
              <YAxis yAxisId="nav" orientation="right" tick={{ fontSize: 11, fill: "#6b7a99" }} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
              <Tooltip
                contentStyle={{ borderRadius: 10, fontSize: 13, background: "#0f1320", border: "1px solid rgba(255,255,255,0.1)", color: "#e8edf5" }}
                formatter={(value: number, name: string) => {
                  if (name === "equity") return ["¥" + fmt(value), "策略权益"];
                  if (name === "baseline") return ["¥" + fmt(value), "基准(持有)"];
                  return [value.toFixed(4), "净值"];
                }}
                labelFormatter={(label: string) => `日期: ${label}`}
              />
              <Legend formatter={(v: string) => v === "equity" ? "策略权益" : v === "baseline" ? "基准(持有)" : "基金净值"} />
              <Area yAxisId="eq" type="monotone" dataKey="equity" stroke="#00d4aa" strokeWidth={2} fill="url(#equityGrad)" dot={false} activeDot={{ r: 4 }} name="equity" />
              <Line yAxisId="eq" type="monotone" dataKey="baseline" stroke="#ffc048" strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} name="baseline" strokeDasharray="5 3" />
              <Line yAxisId="nav" type="monotone" dataKey="nav" stroke="#3b82f6" strokeWidth={1} dot={false} activeDot={{ r: 3 }} name="nav" opacity={0.5} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ===== 交易记录（默认展开） ===== */}
      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 13, color: "var(--accent)", fontWeight: 600, marginBottom: 12, borderLeft: "3px solid var(--accent)", paddingLeft: 8 }}>
          AI 交易记录（{trades.length} 笔）
        </div>
        {trades.length === 0 ? (
          <div style={{ color: "var(--text-secondary)", textAlign: "center", padding: 20, fontSize: 13 }}>暂无交易</div>
        ) : (
          <div className="strat-trades">
            <table className="strat-trade-table">
              <thead>
                <tr>
                  <th>日期</th>
                  <th>操作</th>
                  <th>成交净值</th>
                  <th>成交金额</th>
                  <th>成交份额</th>
                  <th>现金余额</th>
                  <th>账户权益</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice().reverse().map((t, i) => (
                  <tr key={i}>
                    <td>{t.date}</td>
                    <td>
                      <span className={`strat-trade-badge ${t.action.includes("仓") && !t.action.includes("减") && !t.action.includes("清") && !t.action.includes("止损") ? "strat-badge-buy" : t.action.includes("止损") ? "strat-badge-stop" : "strat-badge-sell"}`}>
                        {t.action}
                      </span>
                    </td>
                    <td>{t.nav.toFixed(4)}</td>
                    <td>¥{fmt(t.amount)}</td>
                    <td>{t.shares.toFixed(4)}</td>
                    <td>¥{fmt(t.cash)}</td>
                    <td>¥{fmt(t.equity)}</td>
                    <td style={{ fontSize: 12, color: "var(--text-secondary)", maxWidth: 200 }}>{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 参数说明 */}
      <div style={{ fontSize: 11, color: "var(--text-secondary)", textAlign: "center", marginTop: 16, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
        Momentum={MOMENTUM_PERIOD}D | ATR={ATR_PERIOD}D | MA{MA_PERIOD}趋势过滤 | S&gt;{STRONG_SIGNAL}→{POS_FULL * 100}% | 0&lt;S≤{STRONG_SIGNAL}→{POS_HALF * 100}% | 软止损{STOP_SOFT * 100}%减仓 | 硬止损{STOP_HARD * 100}%清仓 | 冷却{COOLDOWN_DAYS}天
      </div>
    </div>
  );
}
