"use client";

import { useState, useEffect, useRef, lazy, Suspense } from "react";
import gsap from "gsap";
import FundSearch from "@/components/FundSearch";
import MetricsCard from "@/components/MetricsCard";
import FundChart from "@/components/FundChart";
import FundInfo from "@/components/FundInfo";
import ReturnDistribution from "@/components/ReturnDistribution";
import RiskHeatmap from "@/components/RiskHeatmap";
import AIFundPicks from "@/components/AIFundPicks";
import AIAutoTrader from "@/components/AIAutoTrader";
import CycleIndicator from "@/components/CycleIndicator";
import MacroClockView from "@/components/MacroClockView";
import UnderlyingAnalysis from "@/components/UnderlyingAnalysis";

// 懒加载非首屏组件（减少初始 bundle 大小）
const CompareView = lazy(() => import("@/components/CompareView"));
const StrategyView = lazy(() => import("@/components/StrategyView"));
const MarketMonitor = lazy(() => import("@/components/MarketMonitor"));
const AITradingBoard = lazy(() => import("@/components/AITradingBoard"));

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

interface CycleData {
  rsi: number;
  percentile: number;
  ma_deviation: number;
  status: "strong" | "weak" | "neutral";
  annual_return: number;
  show_warning: boolean;
  signals: string[];
}

interface MacroData {
  stage: string;
  stage_cn: string;
  description: string;
  advice: string;
}

interface FundTypeData {
  fund_type: string;
  risk_level: string;
  description: string;
  characteristics: string[];
}

type TabKey = "single" | "compare" | "strategy" | "monitor";

const TABS: { key: TabKey; label: string }[] = [
  { key: "single", label: "单基金分析" },
  { key: "compare", label: "多基金对比" },
  { key: "strategy", label: "策略回测" },
  { key: "monitor", label: "市场监控" },
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabKey>("single");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [navHistory, setNavHistory] = useState<NavPoint[]>([]);
  const [cycleData, setCycleData] = useState<CycleData | null>(null);
  const [macroData, setMacroData] = useState<MacroData | null>(null);
  const [fundTypeData, setFundTypeData] = useState<FundTypeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fundCode, setFundCode] = useState("");
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    gsap.fromTo(
      ".card",
      { opacity: 0, y: 20 },
      { opacity: 1, y: 0, duration: 0.5, stagger: 0.08, ease: "power2.out" }
    );
  }, []);

  useEffect(() => {
    if (!autoRefresh || !fundCode) return;
    const interval = setInterval(() => handleSearch(fundCode), 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, fundCode]);

  useEffect(() => {
    if (!metrics || !resultsRef.current) return;
    const cards = resultsRef.current.querySelectorAll(".card");
    gsap.fromTo(
      cards,
      { opacity: 0, y: 30 },
      { opacity: 1, y: 0, duration: 0.4, stagger: 0.06, ease: "power2.out" }
    );
  }, [metrics, navHistory]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(timer);
  }, [toast]);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    setToast({ message, type });
  };

  const handleSearch = async (code: string) => {
    setError("");
    setMetrics(null);
    setNavHistory([]);
    setCycleData(null);
    setMacroData(null);
    setFundTypeData(null);
    setFundCode(code);
    setLoading(true);

    try {
      const fetchRes = await fetch(`/api/fund/${code}/fetch`, { method: "POST" });
      if (!fetchRes.ok) {
        const err = await fetchRes.json();
        throw new Error(err.detail || "拉取数据失败");
      }

      const [metricsRes, navRes, cycleRes, macroRes, holdingsRes] = await Promise.all([
        fetch(`/api/fund/${code}/metrics`),
        fetch(`/api/fund/${code}/nav`),
        fetch(`/api/fund/${code}/cycle`),
        fetch(`/api/fund/${code}/macro`),
        fetch(`/api/fund/${code}/holdings`),
      ]);

      if (!metricsRes.ok) {
        const err = await metricsRes.json();
        throw new Error(err.detail || "计算指标失败");
      }

      const metricsData = await metricsRes.json();
      const navData = navRes.ok ? await navRes.json() : [];
      const cycle = cycleRes.ok ? await cycleRes.json() : null;
      const macro = macroRes.ok ? await macroRes.json() : null;
      const holdings = holdingsRes.ok ? await holdingsRes.json() : null;

      setMetrics(metricsData);
      setNavHistory(navData);
      setCycleData(cycle);
      setMacroData(macro);
      setFundTypeData(holdings);
      setLastUpdate(new Date());
    } catch (e: any) {
      setError(e.message || "查询失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const handleExportCSV = () => {
    if (!metrics || !navHistory.length) return;

    const headers = ["日期", "净值", "累计净值", "日收益率"];
    const rows = navHistory.map((point) => [
      point.date,
      point.nav.toFixed(4),
      point.acc_nav ? point.acc_nav.toFixed(4) : "",
      point.daily_return ? (point.daily_return * 100).toFixed(4) + "%" : "",
    ]);

    const metricsRows = [
      ["基金代码", metrics.fund_code],
      ["基金名称", metrics.fund_name],
      ["年化收益率", (metrics.annualized_return * 100).toFixed(2) + "%"],
      ["最大回撤", (metrics.max_drawdown * 100).toFixed(2) + "%"],
      ["夏普比率", metrics.sharpe_ratio.toFixed(4)],
      ["波动率", (metrics.volatility * 100).toFixed(2) + "%"],
      ["总收益率", (metrics.total_return * 100).toFixed(2) + "%"],
      ["交易天数", metrics.trading_days.toString()],
      ["开始日期", metrics.start_date],
      ["结束日期", metrics.end_date],
    ];

    const csvContent = [
      "基金指标",
      ...metricsRows.map((row) => row.join(",")),
      "",
      "净值数据",
      headers.join(","),
      ...rows.map((row) => row.join(",")),
    ].join("\n");

    const blob = new Blob(["﻿" + csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.setAttribute("href", url);
    link.setAttribute("download", `基金分析_${metrics.fund_code}_${new Date().toISOString().slice(0, 10)}.csv`);
    link.style.visibility = "hidden";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast("CSV 导出成功", "success");
  };

  return (
    <>
      {/* Toast 提示 */}
      {toast && (
        <div className={`toast toast-${toast.type}`}>
          {toast.message}
        </div>
      )}

      {/* Header + 全局搜索 */}
      <header>
        <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <div>
              <h1>基金分析系统</h1>
              <p>输入基金代码，自动拉取净值、计算核心指标、风险情景分析</p>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {lastUpdate && (
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
                  {lastUpdate.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                </span>
              )}
              {fundCode && (
                <>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "6px 12px", fontSize: "var(--text-xs)" }}
                    onClick={() => handleSearch(fundCode)}
                    disabled={loading}
                  >
                    {loading ? "刷新中..." : "刷新"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "6px 12px", fontSize: "var(--text-xs)" }}
                    onClick={handleExportCSV}
                    disabled={!metrics}
                  >
                    导出CSV
                  </button>
                  <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
                    <input
                      type="checkbox"
                      checked={autoRefresh}
                      onChange={(e) => setAutoRefresh(e.target.checked)}
                      style={{ width: 14, height: 14 }}
                    />
                    自动刷新
                  </label>
                </>
              )}
            </div>
          </div>
          {/* 全局搜索栏 */}
          <div className="search-bar" style={{ width: "100%", maxWidth: "100%" }}>
            <FundSearch onSearch={handleSearch} loading={loading} />
          </div>
        </div>
      </header>

      <div className="container">
        {/* Tab 导航 */}
        <div className="tabs">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              className={`tab ${activeTab === tab.key ? "tab-active" : ""}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {error && <div className="error-msg">{error}</div>}

        {/* 骨架屏加载 */}
        {loading && (
          <div className="bento-grid">
            <div className="skeleton skeleton-metric" />
            <div className="skeleton skeleton-metric" />
            <div className="skeleton skeleton-metric" />
            <div className="skeleton skeleton-metric" />
            <div className="skeleton skeleton-chart bento-full" />
          </div>
        )}

        {/* ===== 单基金分析 ===== */}
        {activeTab === "single" && !loading && (
          <div ref={resultsRef}>
            {metrics && (
              <>
                {/* Bento 网格：核心指标 + 周期 + 宏观 + 底层 */}
                <div className="bento-grid">
                  <div className="card">
                    <h2>核心指标</h2>
                    <MetricsCard metrics={metrics} navHistory={navHistory} />
                  </div>

                  {cycleData && (
                    <div className="card">
                      <h2>强弱周期</h2>
                      <CycleIndicator data={cycleData} />
                    </div>
                  )}

                  {macroData && (
                    <div className="card">
                      <h2>经济周期</h2>
                      <MacroClockView data={macroData} />
                    </div>
                  )}

                  {fundTypeData && (
                    <div className="card">
                      <h2>底层资产</h2>
                      <UnderlyingAnalysis data={fundTypeData} fundName={metrics.fund_name} />
                    </div>
                  )}
                </div>

                {/* 净值走势（全宽） */}
                {navHistory.length > 0 && (
                  <div className="card">
                    <h2>净值走势</h2>
                    <FundChart data={navHistory} />
                  </div>
                )}

                {/* Bento 网格：收益分布 + 热力图 */}
                {navHistory.length > 0 && (
                  <div className="bento-grid">
                    <div className="card">
                      <h2>收益率分布</h2>
                      <ReturnDistribution navHistory={navHistory} />
                    </div>
                    <div className="card">
                      <h2>月度热力图</h2>
                      <RiskHeatmap navHistory={navHistory} />
                    </div>
                  </div>
                )}

                {/* 基本信息 */}
                <div className="card">
                  <h2>基本信息</h2>
                  <FundInfo metrics={metrics} />
                </div>

                {/* AI 持仓分析 */}
                <div className="card">
                  <h2>AI 持仓分析</h2>
                  <div className="holding-summary">
                    <div className="holding-main">
                      <div className="holding-label">当前净值</div>
                      <div className="holding-value" style={{ fontSize: "var(--text-2xl)", color: "var(--accent)" }}>
                        {navHistory.length > 0 ? navHistory[navHistory.length - 1].nav.toFixed(4) : "N/A"}
                      </div>
                    </div>
                    <div className="holding-main">
                      <div className="holding-label">今日收益</div>
                      <div className={`holding-value ${navHistory.length > 1 && navHistory[navHistory.length - 1].nav > navHistory[navHistory.length - 2].nav ? "positive" : "negative"}`}>
                        {navHistory.length > 1 ? (
                          <>
                            {((navHistory[navHistory.length - 1].nav - navHistory[navHistory.length - 2].nav) / navHistory[navHistory.length - 2].nav * 100).toFixed(2)}%
                          </>
                        ) : "N/A"}
                      </div>
                    </div>
                    <div className="holding-main">
                      <div className="holding-label">年化收益</div>
                      <div className={`holding-value ${metrics.annualized_return >= 0 ? "positive" : "negative"}`}>
                        {metrics.annualized_return >= 0 ? "+" : ""}{(metrics.annualized_return * 100).toFixed(2)}%
                      </div>
                    </div>
                    <div className="holding-main">
                      <div className="holding-label">最大回撤</div>
                      <div className="holding-value negative">
                        -{(metrics.max_drawdown * 100).toFixed(2)}%
                      </div>
                    </div>
                  </div>

                  <div className="holding-advice">
                    <div className="holding-advice-title">AI 投资建议</div>
                    <div className="holding-advice-content">
                      {metrics.annualized_return > 0.1 && metrics.max_drawdown < 0.2 ? (
                        <div className="advice-item advice-positive">
                          <span className="advice-icon">✓</span>
                          <span>该基金表现优秀，年化收益超过10%且回撤控制在20%以内，适合长期持有。</span>
                        </div>
                      ) : metrics.annualized_return > 0 && metrics.max_drawdown < 0.3 ? (
                        <div className="advice-item advice-neutral">
                          <span className="advice-icon">→</span>
                          <span>该基金表现中等，建议关注市场趋势，适时调整仓位。</span>
                        </div>
                      ) : (
                        <div className="advice-item advice-negative">
                          <span className="advice-icon">⚠</span>
                          <span>该基金风险较高，建议谨慎投资或考虑止损。</span>
                        </div>
                      )}

                      {metrics.sharpe_ratio > 1 ? (
                        <div className="advice-item advice-positive">
                          <span className="advice-icon">✓</span>
                          <span>夏普比率{metrics.sharpe_ratio.toFixed(2)}，风险调整后收益良好。</span>
                        </div>
                      ) : metrics.sharpe_ratio > 0 ? (
                        <div className="advice-item advice-neutral">
                          <span className="advice-icon">→</span>
                          <span>夏普比率{metrics.sharpe_ratio.toFixed(2)}，收益与风险匹配一般。</span>
                        </div>
                      ) : (
                        <div className="advice-item advice-negative">
                          <span className="advice-icon">⚠</span>
                          <span>夏普比率{metrics.sharpe_ratio.toFixed(2)}，风险大于收益，需谨慎。</span>
                        </div>
                      )}

                      {navHistory.length > 1 && (() => {
                        const todayReturn = (navHistory[navHistory.length - 1].nav - navHistory[navHistory.length - 2].nav) / navHistory[navHistory.length - 2].nav;
                        if (todayReturn > 0.02) {
                          return (
                            <div className="advice-item advice-positive">
                              <span className="advice-icon">↑</span>
                              <span>今日涨幅{(todayReturn * 100).toFixed(2)}%，表现强劲。</span>
                            </div>
                          );
                        } else if (todayReturn > 0) {
                          return (
                            <div className="advice-item advice-neutral">
                              <span className="advice-icon">→</span>
                              <span>今日小幅上涨{(todayReturn * 100).toFixed(2)}%，走势平稳。</span>
                            </div>
                          );
                        } else if (todayReturn > -0.02) {
                          return (
                            <div className="advice-item advice-neutral">
                              <span className="advice-icon">→</span>
                              <span>今日小幅下跌{(todayReturn * 100).toFixed(2)}%，属正常波动。</span>
                            </div>
                          );
                        } else {
                          return (
                            <div className="advice-item advice-negative">
                              <span className="advice-icon">↓</span>
                              <span>今日跌幅{(todayReturn * 100).toFixed(2)}%，需关注走势。</span>
                            </div>
                          );
                        }
                      })()}

                      <div className="advice-item advice-info">
                        <span className="advice-icon">ℹ</span>
                        <span>基于{metrics.trading_days}个交易日数据的分析，仅供参考。</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Bento 网格：AI 精选 + AI 交易 */}
                <div className="bento-grid">
                  <div className="card">
                    <h2>AI 精选基金</h2>
                    <AIFundPicks onSelectFund={handleSearch} />
                  </div>
                  <div className="card">
                    <h2>AI 自动交易</h2>
                    <AIAutoTrader onExecuteTrade={(code, amount) => {
                      showToast(`准备买入基金 ${code}，金额 ¥${amount.toLocaleString()}`, "info");
                    }} />
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ===== 多基金对比 ===== */}
        {activeTab === "compare" && !loading && (
          <div className="card">
            <h2>多基金对比</h2>
            <Suspense fallback={<div style={{ textAlign: "center", padding: 32, color: "var(--text-secondary)" }}>加载中...</div>}>
              <CompareView />
            </Suspense>
          </div>
        )}

        {/* ===== 策略回测 ===== */}
        {activeTab === "strategy" && !loading && (
          <>
            {navHistory.length > 0 && fundCode && (
              <div className="card">
                <h2>动量×波动率策略</h2>
                <Suspense fallback={<div style={{ textAlign: "center", padding: 32, color: "var(--text-secondary)" }}>加载中...</div>}>
                  <StrategyView navHistory={navHistory} fundCode={fundCode} />
                </Suspense>
              </div>
            )}
            {!fundCode && (
              <div className="card" style={{ textAlign: "center", padding: "48px", color: "var(--text-secondary)" }}>
                请先在上方搜索基金代码
              </div>
            )}
          </>
        )}

        {/* ===== 市场监控 ===== */}
        {activeTab === "monitor" && !loading && (
          <>
            <div className="card">
              <h2>AI 交易看板</h2>
              <Suspense fallback={<div style={{ textAlign: "center", padding: 32, color: "var(--text-secondary)" }}>加载中...</div>}>
                <AITradingBoard />
              </Suspense>
            </div>
            <div className="card">
              <h2>推送配置</h2>
              <Suspense fallback={<div style={{ textAlign: "center", padding: 32, color: "var(--text-secondary)" }}>加载中...</div>}>
                <MarketMonitor />
              </Suspense>
            </div>
          </>
        )}
      </div>
    </>
  );
}
