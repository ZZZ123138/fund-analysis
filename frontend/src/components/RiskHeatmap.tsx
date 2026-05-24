"use client";

import { useMemo } from "react";

interface NavPoint {
  date: string;
  nav: number;
}

interface Props {
  navHistory: NavPoint[];
}

interface HeatmapData {
  month: string;
  year: number;
  return: number;
  color: string;
  textColor: string;
}

// 统一 4 档颜色（深红/浅红/浅绿/深绿）
function getHeatColor(val: number): { bg: string; text: string } {
  if (val > 3) return { bg: "var(--green)", text: "var(--bg-primary)" };
  if (val > 0) return { bg: "rgba(16,185,129,0.4)", text: "var(--bg-primary)" };
  if (val > -3) return { bg: "rgba(239,68,68,0.35)", text: "var(--text-primary)" };
  return { bg: "var(--red)", text: "#fff" };
}

function computeMonthlyReturns(navHistory: NavPoint[]): HeatmapData[] {
  if (navHistory.length < 2) return [];

  const monthlyData: Record<string, { start: number; end: number }> = {};
  navHistory.forEach((point) => {
    const date = new Date(point.date);
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
    if (!monthlyData[key]) {
      monthlyData[key] = { start: point.nav, end: point.nav };
    } else {
      monthlyData[key].end = point.nav;
    }
  });

  const result: HeatmapData[] = [];
  Object.entries(monthlyData)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .forEach(([key, data]) => {
      const [year, month] = key.split("-");
      const monthReturn = ((data.end - data.start) / data.start) * 100;
      const { bg, text } = getHeatColor(monthReturn);
      result.push({
        month: `${parseInt(month)}月`,
        year: parseInt(year),
        return: monthReturn,
        color: bg,
        textColor: text,
      });
    });

  return result;
}

export default function RiskHeatmap({ navHistory }: Props) {
  const heatmapData = useMemo(() => computeMonthlyReturns(navHistory), [navHistory]);

  if (heatmapData.length === 0) {
    return (
      <div style={{ color: "var(--text-secondary)", textAlign: "center", padding: 40 }}>
        净值数据不足，无法计算月度收益
      </div>
    );
  }

  const yearGroups: Record<number, HeatmapData[]> = {};
  heatmapData.forEach((item) => {
    if (!yearGroups[item.year]) yearGroups[item.year] = [];
    yearGroups[item.year].push(item);
  });
  const years = Object.keys(yearGroups).sort().map(Number);

  return (
    <>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--accent)", fontWeight: 600, marginBottom: 16, borderLeft: "3px solid var(--accent)", paddingLeft: 8 }}>
        月度收益热力图
      </div>

      {/* 图例 */}
      <div className="heat-legend">
        <div className="heat-legend-item"><div className="heat-legend-box" style={{ background: "var(--red)" }} /><span>&lt;-3%</span></div>
        <div className="heat-legend-item"><div className="heat-legend-box" style={{ background: "rgba(239,68,68,0.35)" }} /><span>-3~0%</span></div>
        <div className="heat-legend-item"><div className="heat-legend-box" style={{ background: "rgba(16,185,129,0.4)" }} /><span>0~3%</span></div>
        <div className="heat-legend-item"><div className="heat-legend-box" style={{ background: "var(--green)" }} /><span>&gt;3%</span></div>
      </div>

      {/* 热力图网格 */}
      <div style={{ overflowX: "auto" }}>
        {years.map((year) => (
          <div key={year} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: "var(--text-sm)", fontWeight: 600, color: "var(--text-primary)", marginBottom: 8 }}>
              {year}年
            </div>
            <div className="heat-grid">
              {Array.from({ length: 12 }, (_, i) => {
                const monthData = yearGroups[year]?.find((d) => d.month === `${i + 1}月`);
                return (
                  <div
                    key={i}
                    className="heat-cell"
                    style={{
                      background: monthData ? monthData.color : "var(--bg-elevated)",
                      border: monthData ? "none" : "1px solid var(--border)",
                    }}
                  >
                    <div style={{ fontSize: 10, color: monthData ? monthData.textColor : "var(--text-tertiary)", marginBottom: 2 }}>
                      {i + 1}月
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: monthData ? monthData.textColor : "var(--text-tertiary)" }}>
                      {monthData ? `${monthData.return > 0 ? "+" : ""}${monthData.return.toFixed(1)}%` : "-"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 统计摘要 */}
      <div className="heat-stats">
        <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginBottom: 8 }}>月度收益统计</div>
        <div className="heat-stats-grid">
          <div>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>最佳月份</div>
            <div style={{ fontSize: "var(--text-base)", fontWeight: 600, color: "var(--green)" }}>
              {Math.max(...heatmapData.map((d) => d.return)).toFixed(1)}%
            </div>
          </div>
          <div>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>最差月份</div>
            <div style={{ fontSize: "var(--text-base)", fontWeight: 600, color: "var(--red)" }}>
              {Math.min(...heatmapData.map((d) => d.return)).toFixed(1)}%
            </div>
          </div>
          <div>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>上涨月份</div>
            <div style={{ fontSize: "var(--text-base)", fontWeight: 600, color: "var(--text-primary)" }}>
              {heatmapData.filter((d) => d.return > 0).length}/{heatmapData.length}
            </div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .heat-legend {
          display: flex;
          justify-content: center;
          gap: 12px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }
        .heat-legend-item {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .heat-legend-box {
          width: 12px;
          height: 12px;
          border-radius: 2px;
        }
        .heat-grid {
          display: grid;
          grid-template-columns: repeat(12, 1fr);
          gap: 4px;
        }
        .heat-cell {
          padding: 8px 4px;
          border-radius: var(--radius-sm);
          text-align: center;
          min-height: 40px;
          display: flex;
          flex-direction: column;
          justify-content: center;
        }
        .heat-stats {
          margin-top: 16px;
          padding: 12px;
          background: var(--bg-elevated);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .heat-stats-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
        }
        @media (max-width: 640px) {
          .heat-grid {
            grid-template-columns: repeat(6, 1fr);
          }
        }
      `}</style>
    </>
  );
}
