"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

const COLORS = ["#3b82f6", "#00d4aa", "#ffc048", "#ff4757", "#a855f7"];

interface NavPoint {
  date: string;
  nav: number;
}

export default function CompareView() {
  const [codes, setCodes] = useState<string[]>(["", ""]);
  const [data, setData] = useState<Record<string, any>[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchNav = async (code: string): Promise<NavPoint[]> => {
    const trimmed = code.trim();
    // 先拉取数据
    await fetch(`/api/fund/${trimmed}/fetch`, { method: "POST" });
    const res = await fetch(`/api/fund/${trimmed}/nav`);
    if (!res.ok) throw new Error(`基金 ${trimmed} 数据获取失败`);
    return res.json();
  };

  const handleCompare = async () => {
    const validCodes = codes.filter((c) => c.trim());
    if (validCodes.length < 2) {
      setError("请至少输入两个基金代码");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const navs = await Promise.all(validCodes.map(fetchNav));
      const dateMap = new Map<string, Record<string, any>>();
      validCodes.forEach((code, idx) => {
        navs[idx].forEach((item) => {
          const key = item.date;
          if (!dateMap.has(key)) dateMap.set(key, { date: key });
          dateMap.get(key)![code.trim()] = item.nav;
        });
      });
      const merged = Array.from(dateMap.values()).sort(
        (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
      );
      setData(merged);
    } catch (e: any) {
      setError(e.message || "对比失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        {codes.map((code, idx) => (
          <input
            key={idx}
            value={code}
            onChange={(e) =>
              setCodes(codes.map((c, i) => (i === idx ? e.target.value : c)))
            }
            placeholder={`基金代码 ${idx + 1}`}
            className="compare-input"
          />
        ))}
        <button
          className="btn btn-secondary"
          style={{ padding: "8px 14px" }}
          onClick={() => setCodes([...codes, ""])}
        >
          + 添加
        </button>
        <button
          className="btn btn-primary"
          onClick={handleCompare}
          disabled={loading}
        >
          {loading ? "加载中..." : "开始对比"}
        </button>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {data && data.length > 0 && (
        <div className="chart-wrapper">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "#6b7a99" }}
                tickFormatter={(v: string) => v.slice(0, 7)}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6b7a99" }}
                domain={["auto", "auto"]}
                tickFormatter={(v: number) => v.toFixed(2)}
              />
              <Tooltip
                contentStyle={{ borderRadius: 10, fontSize: 13, background: "#0f1320", border: "1px solid rgba(255,255,255,0.1)", color: "#e8edf5" }}
                labelFormatter={(label: string) => `日期: ${label}`}
              />
              <Legend />
              {codes
                .filter((c) => c.trim())
                .map((code, idx) => (
                  <Line
                    key={code}
                    type="monotone"
                    dataKey={code.trim()}
                    stroke={COLORS[idx % COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                    name={code.trim()}
                  />
                ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <style jsx>{`
        .compare-input {
          padding: 8px 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          font-size: 14px;
          width: 130px;
          background: var(--bg-primary);
          color: var(--text-primary);
          outline: none;
        }
        .compare-input:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 3px var(--accent-dim);
        }
      `}</style>
    </div>
  );
}
