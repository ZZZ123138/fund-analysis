"use client";

import {
  LineChart,
  Line,
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

export default function FundChart({ data }: Props) {
  if (!data.length) return null;

  // 数据过多时抽样显示
  const maxPoints = 500;
  let displayData = data;
  if (data.length > maxPoints) {
    const step = Math.ceil(data.length / maxPoints);
    displayData = data.filter((_, i) => i % step === 0);
    // 确保包含最后一条
    if (displayData[displayData.length - 1].date !== data[data.length - 1].date) {
      displayData.push(data[data.length - 1]);
    }
  }

  return (
    <div className="chart-wrapper">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={displayData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
          <defs>
            <linearGradient id="navGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2} />
              <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            tickFormatter={(v) => v.slice(0, 7)}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#94a3b8" }}
            domain={["auto", "auto"]}
            tickFormatter={(v) => v.toFixed(2)}
          />
          <Tooltip
            contentStyle={{ borderRadius: 8, fontSize: 13 }}
            formatter={(value: number) => [value.toFixed(4), "单位净值"]}
            labelFormatter={(label) => `日期: ${label}`}
          />
          <Area
            type="monotone"
            dataKey="nav"
            stroke="#3b82f6"
            strokeWidth={2}
            fill="url(#navGradient)"
            dot={false}
            activeDot={{ r: 4 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
