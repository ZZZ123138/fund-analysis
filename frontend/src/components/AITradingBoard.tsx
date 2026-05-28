"use client";

import { useState, useEffect } from "react";

interface Holding {
  fund_code: string;
  fund_name: string;
  shares: number;
  cost: number;
  market_value: number;
  latest_nav: number;
  pnl: number;
  pnl_pct: number;
}

interface Trade {
  id: number;
  fund_code: string;
  fund_name: string;
  trade_type: string;
  trade_label: string;
  amount: number;
  nav: number;
  shares: number;
  trade_date: string;
  status: string;
  confirm_date: string;
}

interface BoardData {
  initialized: boolean;
  balance: number;
  holdings_value: number;
  pending_value: number;
  total_assets: number;
  initial_balance: number;
  total_pnl: number;
  total_return_pct: number;
  trade_count: number;
  nav_date: string;
  nav_stale: boolean;
  holdings: Holding[];
  trades: Trade[];
}

const LABEL_COLORS: Record<string, { bg: string; color: string }> = {
  "定投": { bg: "rgba(59, 130, 246, 0.15)", color: "#60a5fa" },
  "补仓": { bg: "rgba(168, 85, 247, 0.15)", color: "#c084fc" },
  "建仓": { bg: "rgba(34, 197, 94, 0.15)", color: "#4ade80" },
  "手动": { bg: "rgba(156, 163, 175, 0.15)", color: "#9ca3af" },
};

export default function AITradingBoard() {
  const [data, setData] = useState<BoardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState<number | null>(null);

  const loadData = async () => {
    try {
      const resp = await fetch("/api/ai-trading/board");
      const json = await resp.json();
      setData(json);
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 30000);
    return () => clearInterval(timer);
  }, []);

  const handleCancel = async (tradeId: number) => {
    if (!confirm("确定要撤销这笔交易吗？")) return;
    setCancelling(tradeId);
    try {
      const resp = await fetch(`/api/ai-trading/cancel/${tradeId}`, { method: "POST" });
      if (resp.ok) {
        await loadData();
      } else {
        alert("撤单失败");
      }
    } catch {
      alert("撤单失败");
    }
    setCancelling(null);
  };

  if (loading) return <div className="board-loading">加载中...</div>;
  if (!data || !data.initialized) return <div className="board-empty">AI 尚未开始交易</div>;

  const pnlColor = data.total_pnl >= 0 ? "var(--green)" : "var(--red)";
  const pendingTrades = data.trades.filter((t) => t.status === "pending");
  const confirmedTrades = data.trades.filter((t) => t.status !== "pending");

  return (
    <>
      {/* 总览 */}
      <div className="board-summary">
        <div className="board-stat">
          <div className="board-stat-label">总资产</div>
          <div className="board-stat-value">¥{data.total_assets.toLocaleString()}</div>
        </div>
        <div className="board-stat">
          <div className="board-stat-label">累计收益</div>
          <div className="board-stat-value" style={{ color: pnlColor }}>
            {data.total_pnl >= 0 ? "+" : ""}¥{data.total_pnl.toLocaleString()}
          </div>
        </div>
        <div className="board-stat">
          <div className="board-stat-label">收益率</div>
          <div className="board-stat-value" style={{ color: pnlColor }}>
            {data.total_return_pct >= 0 ? "+" : ""}
            {data.total_return_pct}%
          </div>
        </div>
        <div className="board-stat">
          <div className="board-stat-label">交易次数</div>
          <div className="board-stat-value">{data.trade_count}</div>
        </div>
      </div>

      {/* 数据时效 */}
      {data.nav_date && (
        <div className="board-nav-freshness" style={{ color: data.nav_stale ? "var(--orange, #f59e0b)" : "var(--text-tertiary)" }}>
          {data.nav_stale ? "⏳ 净值数据截至 " : "✓ 净值数据截至 "}
          {data.nav_date.replace(/-/g, "/")}
          {data.nav_stale && "（非今日，收盘后自动更新）"}
        </div>
      )}

      {/* 资金分布 */}
      <div className="board-bar-wrap">
        <div className="board-bar-label">
          <span>现金 ¥{data.balance.toLocaleString()}</span>
          <span>持仓 ¥{data.holdings_value.toLocaleString()}</span>
          {data.pending_value > 0 && <span>待确认 ¥{data.pending_value.toLocaleString()}</span>}
        </div>
        <div className="board-bar">
          <div className="board-bar-cash" style={{ width: `${(data.balance / data.total_assets) * 100}%` }} />
          <div
            className="board-bar-pending"
            style={{ width: `${(data.pending_value / data.total_assets) * 100}%` }}
          />
        </div>
      </div>

      {/* 待确认交易 */}
      {pendingTrades.length > 0 && (
        <div className="board-section">
          <div className="board-section-title" style={{ color: "var(--orange, #f59e0b)" }}>
            待确认交易（T+1后自动确认）
          </div>
          <div className="board-trades">
            {pendingTrades.map((t) => (
              <div key={t.id} className="board-trade board-trade-pending">
                <div className="board-trade-icon" style={{ color: "var(--orange, #f59e0b)" }}>
                  {t.trade_type === "buy" ? "买" : "卖"}
                </div>
                <div className="board-trade-info">
                  <div className="board-trade-name">
                    {t.fund_name}
                    <span className="board-badge-pending">待确认</span>
                    {t.trade_label && LABEL_COLORS[t.trade_label] && (
                      <span
                        className="board-badge-label"
                        style={{ background: LABEL_COLORS[t.trade_label].bg, color: LABEL_COLORS[t.trade_label].color }}
                      >
                        {t.trade_label}
                      </span>
                    )}
                  </div>
                  <div className="board-trade-time">
                    {t.trade_date} · 确认日 {t.confirm_date}
                  </div>
                </div>
                <div style={{ textAlign: "right", display: "flex", alignItems: "center", gap: 12 }}>
                  <div>
                    <div className="board-trade-amount">¥{t.amount.toLocaleString()}</div>
                    <div className="board-trade-nav">净值 {t.nav.toFixed(4)}</div>
                  </div>
                  <button
                    className="board-btn-cancel"
                    onClick={() => handleCancel(t.id)}
                    disabled={cancelling === t.id}
                  >
                    {cancelling === t.id ? "撤销中..." : "撤单"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 已确认持仓 */}
      {data.holdings.length > 0 && (
        <div className="board-section">
          <div className="board-section-title">已确认持仓</div>
          <div className="board-holdings">
            {data.holdings.map((h) => (
              <div key={h.fund_code} className="board-holding">
                <div className="board-holding-header">
                  <div>
                    <div className="board-holding-name">{h.fund_name}</div>
                    <div className="board-holding-code">{h.fund_code}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="board-holding-value">¥{h.market_value.toLocaleString()}</div>
                    <div
                      className="board-holding-pnl"
                      style={{ color: h.pnl >= 0 ? "var(--green)" : "var(--red)" }}
                    >
                      {h.pnl >= 0 ? "+" : ""}¥{h.pnl.toLocaleString()} ({h.pnl_pct >= 0 ? "+" : ""}
                      {h.pnl_pct}%)
                    </div>
                  </div>
                </div>
                <div className="board-holding-detail">
                  <span>成本 ¥{h.cost.toLocaleString()}</span>
                  <span>净值 {h.latest_nav.toFixed(4)}</span>
                  <span>份额 {h.shares.toFixed(2)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 已确认交易记录 */}
      {confirmedTrades.length > 0 && (
        <div className="board-section">
          <div className="board-section-title">交易记录</div>
          <div className="board-trades">
            {confirmedTrades.map((t) => (
              <div key={t.id} className="board-trade">
                <div
                  className="board-trade-icon"
                  style={{ color: t.trade_type === "buy" ? "var(--green)" : "var(--red)" }}
                >
                  {t.trade_type === "buy" ? "买" : "卖"}
                </div>
                <div className="board-trade-info">
                  <div className="board-trade-name">
                    {t.fund_name}
                    {t.trade_label && LABEL_COLORS[t.trade_label] && (
                      <span
                        className="board-badge-label"
                        style={{ background: LABEL_COLORS[t.trade_label].bg, color: LABEL_COLORS[t.trade_label].color }}
                      >
                        {t.trade_label}
                      </span>
                    )}
                  </div>
                  <div className="board-trade-time">{t.trade_date}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="board-trade-amount">¥{t.amount.toLocaleString()}</div>
                  <div className="board-trade-nav">净值 {t.nav.toFixed(4)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <style jsx>{`
        .board-loading,
        .board-empty {
          text-align: center;
          padding: 32px;
          font-size: var(--text-sm);
          color: var(--text-secondary);
        }
        .board-summary {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: var(--space-3);
          margin-bottom: var(--space-4);
        }
        .board-stat {
          text-align: center;
          padding: var(--space-3);
          background: rgba(255, 255, 255, 0.02);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .board-stat-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: 4px;
        }
        .board-stat-value {
          font-size: var(--text-lg);
          font-weight: 700;
          color: var(--text-primary);
        }
        .board-nav-freshness {
          font-size: var(--text-xs);
          text-align: right;
          margin-bottom: var(--space-2);
        }
        .board-bar-wrap {
          margin-bottom: var(--space-4);
        }
        .board-bar-label {
          display: flex;
          justify-content: space-between;
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: 6px;
        }
        .board-bar {
          height: 8px;
          background: var(--accent);
          border-radius: 4px;
          overflow: hidden;
          display: flex;
        }
        .board-bar-cash {
          height: 100%;
          background: var(--bg-elevated);
          transition: width 0.3s;
        }
        .board-bar-pending {
          height: 100%;
          background: var(--orange, #f59e0b);
          transition: width 0.3s;
        }
        .board-section {
          margin-bottom: var(--space-4);
        }
        .board-section-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
          margin-bottom: var(--space-3);
        }
        .board-holdings,
        .board-trades {
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }
        .board-holding,
        .board-trade {
          padding: 10px var(--space-3);
          background: var(--bg-elevated);
          border-radius: var(--radius-sm);
          border: 1px solid var(--border);
        }
        .board-trade-pending {
          border-color: var(--orange, #f59e0b);
          background: rgba(245, 158, 11, 0.05);
        }
        .board-holding-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }
        .board-holding-name,
        .board-trade-name {
          font-size: var(--text-sm);
          font-weight: 600;
          color: var(--text-primary);
        }
        .board-holding-code {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .board-holding-value {
          font-size: var(--text-base);
          font-weight: 700;
          color: var(--text-primary);
        }
        .board-holding-pnl,
        .board-trade-amount {
          font-size: var(--text-xs);
          font-weight: 600;
        }
        .board-holding-detail {
          display: flex;
          gap: var(--space-4);
          font-size: var(--text-xs);
          color: var(--text-tertiary);
        }
        .board-trade {
          display: flex;
          align-items: center;
          gap: var(--space-3);
        }
        .board-trade-icon {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: var(--text-xs);
          font-weight: 700;
          background: rgba(255, 255, 255, 0.05);
          flex-shrink: 0;
        }
        .board-trade-info {
          flex: 1;
          min-width: 0;
        }
        .board-trade-time {
          font-size: var(--text-xs);
          color: var(--text-tertiary);
        }
        .board-trade-nav {
          font-size: var(--text-xs);
          color: var(--text-tertiary);
        }
        .board-badge-pending {
          display: inline-block;
          font-size: 10px;
          padding: 1px 6px;
          margin-left: 6px;
          background: var(--orange, #f59e0b);
          color: #000;
          border-radius: 10px;
          font-weight: 600;
        }
        .board-badge-label {
          display: inline-block;
          font-size: 10px;
          padding: 1px 6px;
          margin-left: 4px;
          border-radius: 10px;
          font-weight: 600;
        }
        .board-btn-cancel {
          padding: 4px 12px;
          font-size: 11px;
          background: transparent;
          border: 1px solid var(--red, #ef4444);
          color: var(--red, #ef4444);
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.2s;
          white-space: nowrap;
        }
        .board-btn-cancel:hover:not(:disabled) {
          background: var(--red, #ef4444);
          color: #fff;
        }
        .board-btn-cancel:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        @media (max-width: 640px) {
          .board-summary {
            grid-template-columns: repeat(2, 1fr);
          }
        }
      `}</style>
    </>
  );
}
