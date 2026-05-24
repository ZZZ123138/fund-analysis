"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface NavPoint {
  date: string;
  nav: number;
}

interface Props {
  navHistory: NavPoint[];
}

interface DistributionData {
  range: string;
  count: number;
  color: string;
}

const BINS = [
  { min: -Infinity, max: -2, label: "<-2%", color: "var(--red)" },
  { min: -2, max: -1, label: "-2~-1%", color: "rgba(239,68,68,0.6)" },
  { min: -1, max: 0, label: "-1~0%", color: "rgba(239,68,68,0.35)" },
  { min: 0, max: 1, label: "0~1%", color: "rgba(16,185,129,0.35)" },
  { min: 1, max: 2, label: "1~2%", color: "rgba(16,185,129,0.6)" },
  { min: 2, max: Infinity, label: ">2%", color: "var(--green)" },
];

function computeDistribution(navHistory: NavPoint[]): DistributionData[] {
  if (navHistory.length < 2) return [];

  const returns: number[] = [];
  for (let i = 1; i < navHistory.length; i++) {
    const dailyReturn = (navHistory[i].nav - navHistory[i - 1].nav) / navHistory[i - 1].nav;
    returns.push(dailyReturn * 100);
  }

  return BINS.map((bin) => ({
    range: bin.label,
    count: returns.filter((r) => r >= bin.min && r < bin.max).length,
    color: bin.color,
  }));
}

export default function ReturnDistribution({ navHistory }: Props) {
  const distribution = useMemo(() => computeDistribution(navHistory), [navHistory]);

  if (distribution.length === 0) {
    return (
      <div style={{ color: "var(--text-secondary)", textAlign: "center", padding: 40 }}>
        净值数据不足，无法计算收益分布
      </div>
    );
  }

  const totalDays = distribution.reduce((sum, d) => sum + d.count, 0);
  const positiveDays = distribution.filter((d) => !d.range.startsWith("-")).reduce((sum, d) => sum + d.count, 0);
  const negativeDays = totalDays - positiveDays;

  return (
    <>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontSize: "var(--text-sm)", color: "var(--accent)", fontWeight: 600, borderLeft: "3px solid var(--accent)", paddingLeft: 8 }}>
          收益率分布分析
        </div>
        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
          共 {totalDays} 个交易日
        </div>
      </div>

      {/* 统计摘要 */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <div className="dist-stat dist-stat-up">
          <div className="dist-stat-label">上涨天数</div>
          <div className="dist-stat-value positive">
            {positiveDays} <span style={{ fontSize: "var(--text-xs)", fontWeight: 400 }}>({((positiveDays / totalDays) * 100).toFixed(1)}%)</span>
          </div>
        </div>
        <div className="dist-stat dist-stat-down">
          <div className="dist-stat-label">下跌天数</div>
          <div className="dist-stat-value negative">
            {negativeDays} <span style={{ fontSize: "var(--text-xs)", fontWeight: 400 }}>({((negativeDays / totalDays) * 100).toFixed(1)}%)</span>
          </div>
        </div>
        <div className="dist-stat">
          <div className="dist-stat-label">涨跌比</div>
          <div className="dist-stat-value" style={{ color: positiveDays > negativeDays ? "var(--green)" : "var(--red)" }}>
            {(positiveDays / Math.max(negativeDays, 1)).toFixed(2)}
          </div>
        </div>
      </div>

      {/* 分布图表 */}
      <div style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={distribution} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey="range" tick={{ fontSize: 11, fill: "#6b7a99" }} interval={0} />
            <YAxis tick={{ fontSize: 11, fill: "#6b7a99" }} />
            <Tooltip
              contentStyle={{
                borderRadius: 10,
                fontSize: 13,
                background: "#0f1320",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "#e8edf5",
              }}
              formatter={(value: number) => [`${value} 天`, "交易日数"]}
              labelFormatter={(label: string) => `收益率区间: ${label}`}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {distribution.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <style jsx>{`
        .dist-stat {
          flex: 1;
          padding: 12px;
          background: var(--bg-elevated);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .dist-stat-up {
          background: rgba(16, 185, 129, 0.04);
          border-color: rgba(16, 185, 129, 0.15);
        }
        .dist-stat-down {
          background: rgba(239, 68, 68, 0.04);
          border-color: rgba(239, 68, 68, 0.15);
        }
        .dist-stat-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: var(--space-1);
        }
        .dist-stat-value {
          font-size: var(--text-lg);
          font-weight: 700;
        }
      `}</style>
    </>
  );
}
