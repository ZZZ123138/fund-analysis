"use client";

import { useState, useMemo } from "react";
import {
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";

interface NavPoint {
  date: string;
  nav: number;
}

interface Props {
  data: NavPoint[];
}

type TimeRange = "1M" | "3M" | "6M" | "1Y" | "ALL";

const RANGE_DAYS: Record<TimeRange, number | null> = {
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
  "ALL": null,
};

export default function FundChart({ data }: Props) {
  const [range, setRange] = useState<TimeRange>("ALL");

  const filteredData = useMemo(() => {
    const days = RANGE_DAYS[range];
    if (!days) return data;
    return data.slice(-days);
  }, [data, range]);

  if (!data.length) return null;

  // 数据过多时抽样显示
  const maxPoints = 500;
  let displayData = filteredData;
  if (filteredData.length > maxPoints) {
    const step = Math.ceil(filteredData.length / maxPoints);
    displayData = filteredData.filter((_, i) => i % step === 0);
    if (displayData[displayData.length - 1]?.date !== filteredData[filteredData.length - 1]?.date) {
      displayData.push(filteredData[filteredData.length - 1]);
    }
  }

  return (
    <>
      {/* 时间范围选择器 */}
      <div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
        {(["1M", "3M", "6M", "1Y", "ALL"] as TimeRange[]).map((r) => (
          <button
            key={r}
            onClick={() => setRange(r)}
            style={{
              padding: "4px 12px",
              fontSize: "var(--text-xs)",
              fontWeight: 600,
              border: "none",
              borderRadius: "var(--radius-full)",
              cursor: "pointer",
              background: range === r ? "var(--accent)" : "var(--bg-elevated)",
              color: range === r ? "var(--bg-primary)" : "var(--text-secondary)",
              transition: "all 0.2s",
            }}
          >
            {r}
          </button>
        ))}
      </div>

      <div className="chart-wrapper">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={displayData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
            <defs>
              <linearGradient id="navGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--accent-blue)" stopOpacity={0.2} />
                <stop offset="95%" stopColor="var(--accent-blue)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11, fill: "#6b7a99" }}
              tickFormatter={(v) => v.slice(0, 7)}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#6b7a99" }}
              domain={["auto", "auto"]}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip
              contentStyle={{
                borderRadius: 10,
                fontSize: 13,
                background: "#0f1320",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "#e8edf5",
              }}
              formatter={(value: number) => [value.toFixed(4), "单位净值"]}
              labelFormatter={(label) => `日期: ${label}`}
            />
            <Area
              type="monotone"
              dataKey="nav"
              stroke="var(--accent-blue)"
              strokeWidth={2}
              fill="url(#navGradient)"
              dot={false}
              activeDot={{ r: 4, fill: "var(--accent-blue)" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <style jsx>{`
        .chart-wrapper {
          width: 100%;
          height: 360px;
        }
        @media (max-width: 640px) {
          .chart-wrapper {
            height: 280px;
          }
        }
      `}</style>
    </>
  );
}
