"use client";

import { useState } from "react";

interface DripResult {
  invested: string;
  value: string;
  totalRet: string;
  annualRet: string;
  months: number;
}

interface NavPoint {
  date: string;
  nav: number;
}

function calcDrip(navSeries: NavPoint[], monthlyAmount: number): DripResult | null {
  if (!navSeries.length) return null;
  const startDate = new Date(navSeries[0].date);
  const endDate = new Date(navSeries[navSeries.length - 1].date);

  const investDates: NavPoint[] = [];
  let current = new Date(startDate.getFullYear(), startDate.getMonth(), 1);
  while (current <= endDate) {
    const year = current.getFullYear();
    const month = current.getMonth();
    const monthEnd = new Date(year, month + 1, 0);
    const available = navSeries.filter((item) => {
      const d = new Date(item.date);
      return d >= current && d <= monthEnd;
    });
    if (available.length) investDates.push(available[available.length - 1]);
    current = new Date(year, month + 1, 1);
  }

  let shares = 0;
  let invested = 0;
  for (const inv of investDates) {
    shares += monthlyAmount / inv.nav;
    invested += monthlyAmount;
  }
  const value = shares * navSeries[navSeries.length - 1].nav;
  const totalRet = (value - invested) / invested;
  const years = (endDate.getTime() - startDate.getTime()) / (365.25 * 24 * 3600 * 1000);
  const annualRet = years > 0 ? Math.pow(1 + totalRet, 1 / years) - 1 : 0;

  return {
    invested: invested.toFixed(2),
    value: value.toFixed(2),
    totalRet: (totalRet * 100).toFixed(2),
    annualRet: (annualRet * 100).toFixed(2),
    months: investDates.length,
  };
}

export default function DripSimulator() {
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState(1000);
  const [result, setResult] = useState<DripResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const simulate = async () => {
    if (!code.trim()) return;
    setError("");
    setResult(null);
    setLoading(true);
    try {
      const trimmed = code.trim();
      await fetch(`/api/fund/${trimmed}/fetch`, { method: "POST" });
      const res = await fetch(`/api/fund/${trimmed}/nav`);
      if (!res.ok) throw new Error("数据获取失败");
      const navSeries: NavPoint[] = await res.json();
      const r = calcDrip(navSeries, amount);
      if (r) setResult(r);
      else setError("无有效净值数据");
    } catch (e: any) {
      setError(e.message || "计算失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="基金代码"
          className="drip-input"
        />
        <input
          type="number"
          value={amount}
          onChange={(e) => setAmount(+e.target.value)}
          className="drip-input"
          style={{ width: 100 }}
          min={1}
        />
        <span style={{ color: "var(--text-secondary)", fontSize: 14 }}>元/月</span>
        <button className="btn btn-primary" onClick={simulate} disabled={loading}>
          {loading ? "计算中..." : "模拟定投"}
        </button>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {result && (
        <div className="drip-result">
          <div className="drip-row">
            <span className="drip-label">累计投入</span>
            <span className="drip-value">{result.invested} 元</span>
          </div>
          <div className="drip-row">
            <span className="drip-label">当前市值</span>
            <span className="drip-value">{result.value} 元</span>
          </div>
          <div className="drip-row">
            <span className="drip-label">总收益率</span>
            <span className={`drip-value ${parseFloat(result.totalRet) >= 0 ? "positive" : "negative"}`}>
              {result.totalRet}%
            </span>
          </div>
          <div className="drip-row">
            <span className="drip-label">年化收益率</span>
            <span className={`drip-value ${parseFloat(result.annualRet) >= 0 ? "positive" : "negative"}`}>
              {result.annualRet}%
            </span>
          </div>
          <div className="drip-row">
            <span className="drip-label">定投月数</span>
            <span className="drip-value">{result.months} 个月</span>
          </div>
        </div>
      )}

      <style jsx>{`
        .drip-input {
          padding: 8px 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          font-size: 14px;
          width: 140px;
          background: var(--bg-primary);
          color: var(--text-primary);
          outline: none;
        }
        .drip-input:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px var(--accent-dim);
        }
        .drip-result {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid var(--border);
          border-radius: 12px;
          padding: 20px;
        }
        .drip-row {
          display: flex;
          justify-content: space-between;
          padding: 10px 0;
          border-bottom: 1px solid var(--border);
        }
        .drip-row:last-child {
          border-bottom: none;
        }
        .drip-label {
          color: var(--text-secondary);
          font-size: 14px;
        }
        .drip-value {
          font-weight: 600;
          font-size: 16px;
        }
        .positive {
          color: var(--green);
        }
        .negative {
          color: var(--red);
        }
      `}</style>
    </div>
  );
}
