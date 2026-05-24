"use client";

import { useState, useEffect, useCallback } from "react";

interface Holding {
  fund_code: string;
  fund_name: string;
  shares: number;
  cost: number;
  latest_nav: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
}

interface PortfolioData {
  balance: number;
  holdings: Holding[];
  total_value: number;
  total_cost: number;
  total_pnl: number;
}

interface TradeRecord {
  id: number;
  fund_code: string;
  fund_name: string;
  trade_type: string;
  shares: number;
  nav: number;
  amount: number;
  trade_date: string;
}

export default function PortfolioView() {
  const [initialized, setInitialized] = useState<boolean | null>(null);
  const [initBalance, setInitBalance] = useState(1000000);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [history, setHistory] = useState<TradeRecord[]>([]);
  const [buyCode, setBuyCode] = useState("");
  const [buyAmount, setBuyAmount] = useState(5000);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const [topUpCode, setTopUpCode] = useState<string | null>(null);
  const [topUpAmount, setTopUpAmount] = useState(5000);

  const checkAccount = useCallback(async () => {
    const res = await fetch("/api/portfolio/account");
    const data = await res.json();
    setInitialized(data.initialized);
    if (data.initialized) loadPortfolio();
  }, []);

  useEffect(() => {
    checkAccount();
  }, [checkAccount]);

  const loadPortfolio = async () => {
    const res = await fetch("/api/portfolio/holdings");
    const data = await res.json();
    setPortfolio(data);
  };

  const loadHistory = async () => {
    const res = await fetch("/api/portfolio/history");
    const data = await res.json();
    setHistory(data);
  };

  const handleInit = async () => {
    if (initBalance <= 0) return;
    setLoading(true);
    await fetch("/api/portfolio/init", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ balance: initBalance }),
    });
    setInitialized(true);
    await loadPortfolio();
    setLoading(false);
  };

  const handleBuy = async () => {
    if (!buyCode.trim() || buyAmount <= 0) return;
    setMsg("");
    setLoading(true);
    try {
      // 先拉取数据
      await fetch(`/api/fund/${buyCode.trim()}/fetch`, { method: "POST" });
      const res = await fetch("/api/portfolio/buy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fund_code: buyCode.trim(), amount: buyAmount }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "买入失败");
      setMsg(`买入成功：${data.fund_name || data.fund_code}，获得 ${data.shares} 份`);
      setBuyCode("");
      await loadPortfolio();
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSell = async (code: string) => {
    setMsg("");
    setLoading(true);
    try {
      const res = await fetch("/api/portfolio/sell", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fund_code: code }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "卖出失败");
      setMsg(`卖出成功：${code}，获得 ${data.amount} 元`);
      await loadPortfolio();
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleAddMore = async (code: string) => {
    if (topUpCode === code) {
      // 已展开，执行加仓
      if (topUpAmount <= 0) return;
      setMsg("");
      setLoading(true);
      try {
        const res = await fetch("/api/portfolio/buy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ fund_code: code, amount: topUpAmount }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "买入失败");
        setMsg(`加仓成功：${data.fund_name || code}，获得 ${data.shares} 份`);
        setTopUpCode(null);
        await loadPortfolio();
      } catch (e: any) {
        setMsg(e.message);
      } finally {
        setLoading(false);
      }
    } else {
      setTopUpCode(code);
      setTopUpAmount(5000);
    }
  };

  const fmt = (v: number) => v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const totalAssets = portfolio ? portfolio.balance + portfolio.total_value : 0;

  // 未初始化
  if (initialized === false) {
    return (
      <div className="portfolio-init">
        <p style={{ color: "var(--text-secondary)", marginBottom: 16 }}>
          设置虚拟初始资金，开始模拟交易
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ color: "var(--text-secondary)", fontSize: 14 }}>初始资金</span>
          <input
            type="number"
            value={initBalance}
            onChange={(e) => setInitBalance(+e.target.value)}
            className="portfolio-input"
            style={{ width: 160 }}
            min={1}
          />
          <span style={{ color: "var(--text-secondary)", fontSize: 14 }}>元</span>
          <button className="btn btn-primary" onClick={handleInit} disabled={loading}>
            {loading ? "初始化中..." : "开始交易"}
          </button>
        </div>
      </div>
    );
  }

  if (initialized === null) return <div className="loading">加载中...</div>;

  return (
    <div>
      {/* 资产概览 */}
      <div className="portfolio-summary">
        <div className="summary-item">
          <div className="summary-label">总资产</div>
          <div className="summary-value">{fmt(totalAssets)} 元</div>
        </div>
        <div className="summary-item">
          <div className="summary-label">现金余额</div>
          <div className="summary-value">{fmt(portfolio?.balance ?? 0)} 元</div>
        </div>
        <div className="summary-item">
          <div className="summary-label">持仓市值</div>
          <div className="summary-value">{fmt(portfolio?.total_value ?? 0)} 元</div>
        </div>
        <div className="summary-item">
          <div className="summary-label">总盈亏</div>
          <div className={`summary-value ${(portfolio?.total_pnl ?? 0) >= 0 ? "positive" : "negative"}`}>
            {(portfolio?.total_pnl ?? 0) >= 0 ? "+" : ""}{fmt(portfolio?.total_pnl ?? 0)} 元
          </div>
        </div>
      </div>

      {/* 买入 */}
      <div className="portfolio-buy">
        <h3 style={{ marginBottom: 12, color: "var(--accent)", fontSize: 15 }}>买入基金</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            value={buyCode}
            onChange={(e) => setBuyCode(e.target.value)}
            placeholder="基金代码"
            className="portfolio-input"
            maxLength={6}
          />
          <input
            type="number"
            value={buyAmount}
            onChange={(e) => setBuyAmount(+e.target.value)}
            className="portfolio-input"
            style={{ width: 120 }}
            min={1}
          />
          <span style={{ color: "var(--text-secondary)", fontSize: 14 }}>元</span>
          <button className="btn btn-primary" onClick={handleBuy} disabled={loading}>
            {loading ? "处理中..." : "买入"}
          </button>
        </div>
      </div>

      {msg && (
        <div className={msg.includes("成功") ? "success-msg" : "error-msg"}>{msg}</div>
      )}

      {/* 持仓 */}
      {portfolio && portfolio.holdings.length > 0 && (
        <div className="portfolio-holdings">
          <h3 style={{ marginBottom: 12, color: "var(--accent)", fontSize: 15 }}>当前持仓</h3>
          <div className="holdings-list">
            {portfolio.holdings.map((h) => (
              <div className="holding-row" key={h.fund_code}>
                <div className="holding-info">
                  <div className="holding-name">{h.fund_name || h.fund_code}</div>
                  <div className="holding-code">{h.fund_code}</div>
                </div>
                <div className="holding-stats">
                  <div><span className="stat-label">持有</span> {h.shares.toFixed(4)} 份</div>
                  <div><span className="stat-label">成本</span> {fmt(h.cost)} 元</div>
                  <div><span className="stat-label">净值</span> {h.latest_nav.toFixed(4)}</div>
                  <div><span className="stat-label">市值</span> {fmt(h.market_value)} 元</div>
                  <div className={h.pnl >= 0 ? "positive" : "negative"}>
                    <span className="stat-label">盈亏</span> {h.pnl >= 0 ? "+" : ""}{fmt(h.pnl)} 元 ({h.pnl_pct >= 0 ? "+" : ""}{h.pnl_pct}%)
                  </div>
                </div>
                {topUpCode === h.fund_code && (
                  <div className="topup-form">
                    <input
                      type="number"
                      value={topUpAmount}
                      onChange={(e) => setTopUpAmount(+e.target.value)}
                      className="portfolio-input"
                      style={{ width: 100 }}
                      min={1}
                      placeholder="金额"
                    />
                    <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>元</span>
                  </div>
                )}
                <div className="holding-actions">
                  <button className="btn btn-secondary" style={{ padding: "4px 12px", fontSize: 12 }} onClick={() => handleAddMore(h.fund_code)} disabled={loading}>
                    {topUpCode === h.fund_code ? "确认加仓" : "加仓"}
                  </button>
                  {topUpCode === h.fund_code && (
                    <button className="btn btn-secondary" style={{ padding: "4px 12px", fontSize: 12 }} onClick={() => setTopUpCode(null)}>取消</button>
                  )}
                  <button className="btn btn-secondary" style={{ padding: "4px 12px", fontSize: 12, color: "var(--red)" }} onClick={() => handleSell(h.fund_code)} disabled={loading}>卖出</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {portfolio && portfolio.holdings.length === 0 && (
        <div style={{ color: "var(--text-secondary)", textAlign: "center", padding: 24, fontSize: 14 }}>
          暂无持仓，输入基金代码开始买入
        </div>
      )}

      {/* 交易记录 */}
      <div style={{ marginTop: 16 }}>
        <button
          className="btn btn-secondary"
          style={{ fontSize: 13, padding: "6px 16px" }}
          onClick={() => {
            if (showHistory) {
              setShowHistory(false);
            } else {
              loadHistory();
              setShowHistory(true);
            }
          }}
        >
          {showHistory ? "隐藏交易记录" : "查看交易记录"}
        </button>
      </div>

      {showHistory && history.length > 0 && (
        <div className="trade-history">
          <table className="history-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作</th>
                <th>基金</th>
                <th>净值</th>
                <th>份额</th>
                <th>金额</th>
              </tr>
            </thead>
            <tbody>
              {history.map((t) => (
                <tr key={t.id}>
                  <td>{t.trade_date ? new Date(t.trade_date).toLocaleString("zh-CN") : "-"}</td>
                  <td className={t.trade_type === "buy" ? "positive" : "negative"}>
                    {t.trade_type === "buy" ? "买入" : "卖出"}
                  </td>
                  <td>{t.fund_name || t.fund_code}</td>
                  <td>{t.nav.toFixed(4)}</td>
                  <td>{t.shares.toFixed(4)}</td>
                  <td>{fmt(t.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
