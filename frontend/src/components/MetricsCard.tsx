"use client";

import { useState, useMemo } from "react";

interface Metrics {
  annualized_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  volatility: number;
  total_return: number;
  trading_days: number;
  start_date: string;
  end_date: string;
}

interface NavPoint {
  date: string;
  nav: number;
}

interface Props {
  metrics: Metrics;
  navHistory?: NavPoint[];
}

function pct(v: number) {
  return (v * 100).toFixed(2) + "%";
}

function daysBetween(a: string, b: string) {
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 86400000);
}

function computeDrawdownInfo(navHistory: NavPoint[]) {
  if (!navHistory || navHistory.length < 2) return null;

  // 当前距历史最高跌幅
  let allTimeHigh = 0;
  for (const p of navHistory) {
    if (p.nav > allTimeHigh) allTimeHigh = p.nav;
  }
  const latestNav = navHistory[navHistory.length - 1].nav;
  const currentDrawdown = (allTimeHigh - latestNav) / allTimeHigh;

  // 历史最大回撤时间段
  let peak = navHistory[0].nav;
  let peakDate = navHistory[0].date;
  let maxDD = 0;
  let ddStart = navHistory[0].date;
  let ddEnd = navHistory[0].date;

  for (let i = 1; i < navHistory.length; i++) {
    const p = navHistory[i];
    if (p.nav > peak) {
      peak = p.nav;
      peakDate = p.date;
    }
    const dd = (peak - p.nav) / peak;
    if (dd > maxDD) {
      maxDD = dd;
      ddStart = peakDate;
      ddEnd = p.date;
    }
  }

  return {
    currentDrawdown,
    allTimeHigh,
    latestNav,
    maxDDPeriod: { start: ddStart, end: ddEnd, days: daysBetween(ddStart, ddEnd) },
  };
}

export default function MetricsCard({ metrics, navHistory }: Props) {
  const [showMore, setShowMore] = useState(false);

  const drawdownInfo = useMemo(
    () => (navHistory ? computeDrawdownInfo(navHistory) : null),
    [navHistory]
  );

  const ddPct = drawdownInfo ? drawdownInfo.currentDrawdown : metrics.max_drawdown;
  const isOrange = ddPct > 0.15 && ddPct <= 0.3;
  const isRed = ddPct > 0.3;

  const coreItems = [
    {
      label: "年化收益率",
      value: pct(metrics.annualized_return),
      positive: metrics.annualized_return >= 0,
    },
    {
      label: "最大回撤",
      value: pct(metrics.max_drawdown),
      positive: false,
      warnOrange: metrics.max_drawdown > 0.15 && metrics.max_drawdown <= 0.3,
      warnRed: metrics.max_drawdown > 0.3,
    },
    {
      label: "总收益率",
      value: pct(metrics.total_return),
      positive: metrics.total_return >= 0,
    },
    { label: "交易天数", value: String(metrics.trading_days), positive: true },
  ];

  return (
    <>
      {/* 风险预警横幅 */}
      {isRed && (
        <div className="risk-alert risk-alert-red">
          <span className="risk-icon">⚠</span>
          风险预警：当前回撤 {pct(ddPct)}，超过 30%，请注意投资风险！
        </div>
      )}
      {!isRed && isOrange && (
        <div className="risk-alert risk-alert-orange">
          <span className="risk-icon">⚠</span>
          风险提示：当前回撤 {pct(ddPct)}，超过 15%，请关注走势变化。
        </div>
      )}

      {/* 核心指标卡片 */}
      <div className="metrics-grid">
        {coreItems.map((item) => (
          <div
            className={`metric-card ${item.warnRed ? "metric-red" : item.warnOrange ? "metric-orange" : ""}`}
            key={item.label}
          >
            <div className="metric-label">{item.label}</div>
            <div
              className={`metric-value ${
                item.warnRed
                  ? "metric-value-red"
                  : item.warnOrange
                  ? "metric-value-orange"
                  : item.positive
                  ? "positive"
                  : "negative"
              }`}
            >
              {item.value}
            </div>
          </div>
        ))}
      </div>

      {/* 风险情景分析 */}
      {drawdownInfo && (
        <div className="risk-scenario">
          <div className="risk-scenario-title">风险情景分析</div>
          <div className="risk-scenario-grid">
            <div className="risk-scenario-item">
              <span className="risk-scenario-label">当前净值</span>
              <span className="risk-scenario-value">
                {drawdownInfo.latestNav.toFixed(4)}
              </span>
            </div>
            <div className="risk-scenario-item">
              <span className="risk-scenario-label">历史最高净值</span>
              <span className="risk-scenario-value">
                {drawdownInfo.allTimeHigh.toFixed(4)}
              </span>
            </div>
            <div className="risk-scenario-item">
              <span className="risk-scenario-label">距历史最高跌幅</span>
              <span
                className={`risk-scenario-value ${
                  drawdownInfo.currentDrawdown > 0.3
                    ? "metric-value-red"
                    : drawdownInfo.currentDrawdown > 0.15
                    ? "metric-value-orange"
                    : "negative"
                }`}
              >
                {pct(drawdownInfo.currentDrawdown)}
              </span>
            </div>
            <div className="risk-scenario-item risk-scenario-item-wide">
              <span className="risk-scenario-label">历史最大回撤期间</span>
              <span className="risk-scenario-value">
                {drawdownInfo.maxDDPeriod.start} 至 {drawdownInfo.maxDDPeriod.end}
                <span className="risk-scenario-days">
                  持续 {drawdownInfo.maxDDPeriod.days} 天
                </span>
              </span>
            </div>
          </div>
        </div>
      )}

      {/* 更多指标（折叠） */}
      <div className="more-toggle" onClick={() => setShowMore(!showMore)}>
        {showMore ? "收起详细指标 ▲" : "展开详细指标（夏普比率、波动率等）▼"}
      </div>
      {showMore && (
        <div className="metrics-grid metrics-grid-secondary">
          <div className="metric-card">
            <div className="metric-label">夏普比率</div>
            <div className={`metric-value ${metrics.sharpe_ratio >= 0 ? "positive" : "negative"}`}>
              {metrics.sharpe_ratio.toFixed(4)}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">年化波动率</div>
            <div className="metric-value" style={{ color: "var(--text-secondary)" }}>
              {pct(metrics.volatility)}
            </div>
          </div>
        </div>
      )}

      <style jsx>{`
        .risk-alert {
          padding: 12px 16px;
          border-radius: var(--radius-md);
          font-size: var(--text-sm);
          margin-bottom: 16px;
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
        }
        .risk-alert-red {
          background: rgba(255, 71, 87, 0.12);
          color: var(--red);
          border: 1px solid rgba(255, 71, 87, 0.3);
        }
        .risk-alert-orange {
          background: rgba(255, 192, 72, 0.12);
          color: var(--gold);
          border: 1px solid rgba(255, 192, 72, 0.3);
        }
        .risk-icon {
          font-size: 18px;
        }
        .metric-red {
          border-color: rgba(255, 71, 87, 0.4) !important;
          background: rgba(255, 71, 87, 0.06) !important;
        }
        .metric-orange {
          border-color: rgba(255, 192, 72, 0.4) !important;
          background: rgba(255, 192, 72, 0.06) !important;
        }
        .metric-value-red {
          color: var(--red) !important;
          font-weight: 700;
        }
        .metric-value-orange {
          color: var(--gold) !important;
          font-weight: 700;
        }
        .risk-scenario {
          margin-top: 16px;
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-4);
        }
        .risk-scenario-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          margin-bottom: 12px;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
        }
        .risk-scenario-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 10px;
        }
        .risk-scenario-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 0;
        }
        .risk-scenario-item-wide {
          grid-column: 1 / -1;
        }
        .risk-scenario-label {
          font-size: var(--text-sm);
          color: var(--text-secondary);
        }
        .risk-scenario-value {
          font-size: var(--text-sm);
          font-weight: 600;
        }
        .risk-scenario-days {
          margin-left: 8px;
          font-size: var(--text-xs);
          color: var(--text-secondary);
          font-weight: 400;
        }
        .more-toggle {
          text-align: center;
          padding: var(--space-3);
          color: var(--text-secondary);
          font-size: var(--text-xs);
          cursor: pointer;
          margin-top: 12px;
          border-radius: 8px;
          transition: background 0.2s;
        }
        .more-toggle:hover {
          background: rgba(255, 255, 255, 0.03);
          color: var(--text-primary);
        }
        .metrics-grid-secondary {
          margin-top: 8px;
        }
      `}</style>
    </>
  );
}
