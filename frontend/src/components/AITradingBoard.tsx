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
  fund_code: string;
  fund_name: string;
  trade_type: string;
  amount: number;
  nav: number;
  shares: number;
  trade_date: string;
}

interface BoardData {
  initialized: boolean;
  balance: number;
  holdings_value: number;
  total_assets: number;
  initial_balance: number;
  total_pnl: number;
  total_return_pct: number;
  trade_count: number;
  holdings: Holding[];
  trades: Trade[];
}

export default function AITradingBoard() {
  const [data, setData] = useState<BoardData | null>(null);
  const [loading, setLoading] = useState(true);

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
    const timer = setInterval(loadData, 60000);
    return () => clearInterval(timer);
  }, []);

  if (loading) {
    return <div className="board-loading">加载中...</div>;
  }

  if (!data || !data.initialized) {
    return <div className="board-empty">AI 尚未开始交易，明天开盘后自动运行</div>;
  }

  const pnlColor = data.total_pnl >= 0 ? "var(--green)" : "var(--red)";

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
            {data.total_return_pct >= 0 ? "+" : ""}{data.total_return_pct}%
          </div>
        </div>
        <div className="board-stat">
          <div className="board-stat-label">交易次数</div>
          <div className="board-stat-value">{data.trade_count}</div>
        </div>
      </div>

      {/* 资金分布 */}
      <div className="board-bar-wrap">
        <div className="board-bar-label">
          <span>现金 ¥{data.balance.toLocaleString()}</span>
          <span>持仓 ¥{data.holdings_value.toLocaleString()}</span>
        </div>
        <div className="board-bar">
          <div
            className="board-bar-cash"
            style={{ width: `${(data.balance / data.total_assets) * 100}%` }}
          />
        </div>
      </div>

      {/* 当前持仓 */}
      {data.holdings.length > 0 && (
        <div className="board-section">
          <div className="board-section-title">当前持仓</div>
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
                    <div className="board-holding-pnl" style={{ color: h.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                      {h.pnl >= 0 ? "+" : ""}¥{h.pnl.toLocaleString()} ({h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct}%)
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

      {/* 交易记录 */}
      {data.trades.length > 0 && (
        <div className="board-section">
          <div className="board-section-title">交易记录</div>
          <div className="board-trades">
            {data.trades.map((t, i) => (
              <div key={i} className="board-trade">
                <div className="board-trade-icon" style={{ color: t.trade_type === "buy" ? "var(--green)" : "var(--red)" }}>
                  {t.trade_type === "buy" ? "买" : "卖"}
                </div>
                <div className="board-trade-info">
                  <div className="board-trade-name">{t.fund_name}</div>
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
        .board-loading, .board-empty {
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
          background: rgba(255,255,255,0.02);
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
        }
        .board-bar-cash {
          height: 100%;
          background: var(--bg-elevated);
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
        .board-holdings, .board-trades {
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }
        .board-holding, .board-trade {
          padding: 10px var(--space-3);
          background: var(--bg-elevated);
          border-radius: var(--radius-sm);
          border: 1px solid var(--border);
        }
        .board-holding-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }
        .board-holding-name, .board-trade-name {
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
        .board-holding-pnl, .board-trade-amount {
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
          background: rgba(255,255,255,0.05);
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
        @media (max-width: 640px) {
          .board-summary { grid-template-columns: repeat(2, 1fr); }
        }
      `}</style>
    </>
  );
}
