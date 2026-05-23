"use client";

interface Metrics {
  annualized_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  volatility: number;
  total_return: number;
  trading_days: number;
}

interface Props {
  metrics: Metrics;
}

function pct(v: number) {
  return (v * 100).toFixed(2) + "%";
}

export default function MetricsCard({ metrics }: Props) {
  const items = [
    { label: "年化收益率", value: pct(metrics.annualized_return), positive: metrics.annualized_return >= 0 },
    { label: "最大回撤", value: pct(metrics.max_drawdown), positive: false },
    { label: "夏普比率", value: metrics.sharpe_ratio.toFixed(4), positive: metrics.sharpe_ratio >= 0 },
    { label: "总收益率", value: pct(metrics.total_return), positive: metrics.total_return >= 0 },
    { label: "年化波动率", value: pct(metrics.volatility), positive: true },
    { label: "交易天数", value: String(metrics.trading_days), positive: true },
  ];

  return (
    <div className="metrics-grid">
      {items.map((item) => (
        <div className="metric-card" key={item.label}>
          <div className="metric-label">{item.label}</div>
          <div className={`metric-value ${item.positive ? "positive" : "negative"}`}>
            {item.value}
          </div>
        </div>
      ))}
    </div>
  );
}
