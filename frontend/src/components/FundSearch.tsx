"use client";

import { useState, FormEvent } from "react";

interface Props {
  onSearch: (code: string) => void;
  loading: boolean;
}

const HOT_FUNDS = [
  { code: "110011", name: "易方达中小盘" },
  { code: "161725", name: "招商中证白酒" },
  { code: "003834", name: "华夏能源革新" },
  { code: "005827", name: "易方达蓝筹精选" },
  { code: "320007", name: "诺安成长混合" },
];

export default function FundSearch({ onSearch, loading }: Props) {
  const [code, setCode] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (trimmed) {
      onSearch(trimmed);
    }
  };

  return (
    <>
      <form className="search-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="请输入基金代码，如 110011"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={10}
        />
        <button className="btn btn-primary" type="submit" disabled={loading || !code.trim()}>
          {loading ? "查询中..." : "查询分析"}
        </button>
      </form>

      <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <span style={{ fontSize: 12, color: "#94a3b8" }}>热门：</span>
        {HOT_FUNDS.map((f) => (
          <button
            key={f.code}
            className="btn btn-secondary"
            style={{ padding: "4px 10px", fontSize: 12 }}
            onClick={() => {
              setCode(f.code);
              onSearch(f.code);
            }}
            disabled={loading}
          >
            {f.code}
          </button>
        ))}
      </div>
    </>
  );
}
