"use client";

import { useState } from "react";
import FundSearch from "@/components/FundSearch";
import MetricsCard from "@/components/MetricsCard";
import FundChart from "@/components/FundChart";
import FundInfo from "@/components/FundInfo";
import ReportActions from "@/components/ReportActions";

interface Metrics {
  fund_code: string;
  fund_name: string;
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
  acc_nav: number | null;
  daily_return: number | null;
}

export default function Home() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [navHistory, setNavHistory] = useState<NavPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fundCode, setFundCode] = useState("");

  const handleSearch = async (code: string) => {
    setError("");
    setMetrics(null);
    setNavHistory([]);
    setFundCode(code);
    setLoading(true);

    try {
      // 1. 拉取数据
      const fetchRes = await fetch(`/api/fund/${code}/fetch`, { method: "POST" });
      if (!fetchRes.ok) {
        const err = await fetchRes.json();
        throw new Error(err.detail || "拉取数据失败");
      }

      // 2. 获取指标和净值历史（并行）
      const [metricsRes, navRes] = await Promise.all([
        fetch(`/api/fund/${code}/metrics`),
        fetch(`/api/fund/${code}/nav`),
      ]);

      if (!metricsRes.ok) {
        const err = await metricsRes.json();
        throw new Error(err.detail || "计算指标失败");
      }

      const metricsData = await metricsRes.json();
      const navData = navRes.ok ? await navRes.json() : [];

      setMetrics(metricsData);
      setNavHistory(navData);
    } catch (e: any) {
      setError(e.message || "查询失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <header>
        <h1>基金分析系统</h1>
        <p>输入基金代码，自动拉取净值、计算核心指标、生成分析报告</p>
      </header>

      <div className="container">
        <div className="card">
          <h2>基金查询</h2>
          <FundSearch onSearch={handleSearch} loading={loading} />
        </div>

        {error && <div className="error-msg">{error}</div>}

        {loading && (
          <div className="card loading">正在拉取数据并计算指标，请稍候...</div>
        )}

        {metrics && (
          <>
            <div className="card">
              <h2>核心指标</h2>
              <MetricsCard metrics={metrics} />
            </div>

            {navHistory.length > 0 && (
              <div className="card">
                <h2>净值走势</h2>
                <FundChart data={navHistory} />
              </div>
            )}

            <div className="card">
              <h2>基本信息</h2>
              <FundInfo metrics={metrics} />
            </div>

            <div className="card">
              <h2>报告</h2>
              <ReportActions fundCode={fundCode} />
            </div>
          </>
        )}
      </div>
    </>
  );
}
