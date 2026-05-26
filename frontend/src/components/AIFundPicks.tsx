"use client";

import { useState, useEffect } from "react";

interface FundRecommendation {
  code: string;
  name: string;
  type: string;
  reason: string;
  score: number;
  risk: "低" | "中" | "高";
  expectedReturn: string;
  tags: string[];
}

function getScoreColor(score: number): string {
  if (score >= 90) return "var(--green)";
  if (score >= 80) return "var(--accent)";
  if (score >= 70) return "var(--gold)";
  return "var(--text-secondary)";
}

function getRiskColor(risk: string): string {
  if (risk === "低") return "var(--green)";
  if (risk === "中") return "var(--gold)";
  return "var(--red)";
}

export default function AIFundPicks({ onSelectFund }: { onSelectFund: (code: string) => void }) {
  const [selectedType, setSelectedType] = useState<string>("全部");
  const [picks, setPicks] = useState<FundRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const types = ["全部", "混合型", "指数型", "债券型", "股票型"];

  useEffect(() => {
    fetch("/api/ai-trading/fund-picks")
      .then(r => r.json())
      .then(data => {
        setPicks(data.picks || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const filteredPicks = selectedType === "全部"
    ? picks
    : picks.filter((pick) => pick.type === selectedType);

  return (
    <div>
      {/* 筛选 */}
      <div className="picks-filter">
        <div className="picks-filter-label">AI 精选基金推荐</div>
        <div className="picks-filter-btns">
          {types.map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              className={`picks-filter-btn ${selectedType === type ? "picks-filter-btn-active" : ""}`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* 推荐说明 */}
      <div className="picks-info">
        <div className="picks-info-title">
          <span> </span> <span>AI 推荐策略</span>
        </div>
        基于历史业绩、风险控制、基金经理、费率等多维度分析，精选优质基金供您参考。评分越高表示综合表现越好。
      </div>

      {/* 基金列表 */}
      <div className="picks-list">
        {loading ? (
          <div style={{ padding: "20px", textAlign: "center", color: "var(--text-secondary)", fontSize: "var(--text-xs)" }}>加载中...</div>
        ) : filteredPicks.length === 0 ? (
          <div style={{ padding: "20px", textAlign: "center", color: "var(--text-secondary)", fontSize: "var(--text-xs)" }}>暂无推荐数据</div>
        ) : filteredPicks.map((fund) => (
          <div key={fund.code} className="picks-card" onClick={() => onSelectFund(fund.code)}>
            <div className="picks-card-header">
              <div>
                <div className="picks-fund-name">{fund.name}</div>
                <div className="picks-fund-meta">{fund.code} · {fund.type}</div>
              </div>
              <div className="picks-score">
                <div className="picks-score-value" style={{ color: getScoreColor(fund.score) }}>{fund.score}</div>
                <div className="picks-score-label">AI评分</div>
              </div>
            </div>

            <div className="picks-reason">{fund.reason}</div>

            <div className="picks-footer">
              <div className="picks-tags">
                <div className="picks-tag">
                  <span style={{ color: "var(--text-secondary)" }}>风险：</span>
                  <span style={{ color: getRiskColor(fund.risk), fontWeight: 600 }}>{fund.risk}</span>
                </div>
                <div className="picks-tag">
                  <span style={{ color: "var(--text-secondary)" }}>预期：</span>
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>{fund.expectedReturn}</span>
                </div>
              </div>
              <div className="picks-labels">
                {fund.tags.slice(0, 2).map((tag) => (
                  <span key={tag} className="picks-label">{tag}</span>
                ))}
              </div>
            </div>

            <div className="picks-cta">点击查看详细分析</div>
          </div>
        ))}
      </div>

      <div className="picks-disclaimer">
        <div>⚠ 投资有风险，入市需谨慎</div>
        <div>以上推荐仅供参考，不构成投资建议。</div>
      </div>

      <style jsx>{`
        .picks-filter {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: var(--space-4);
        }
        .picks-filter-label {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
        }
        .picks-filter-btns {
          display: flex;
          gap: 4px;
        }
        .picks-filter-btn {
          padding: 4px 8px;
          font-size: var(--text-xs);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          background: transparent;
          color: var(--text-secondary);
          cursor: pointer;
          transition: all 0.2s;
        }
        .picks-filter-btn-active {
          background: var(--accent);
          color: var(--bg-primary);
          border-color: var(--accent);
        }
        .picks-info {
          padding: 12px;
          background: rgba(0, 212, 170, 0.04);
          border-radius: var(--radius-md);
          border: 1px solid rgba(0, 212, 170, 0.15);
          margin-bottom: var(--space-4);
          font-size: var(--text-xs);
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .picks-info-title {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
          font-weight: 600;
          color: var(--accent);
        }
        .picks-list {
          display: flex;
          flex-direction: column;
          gap: var(--space-3);
        }
        .picks-card {
          padding: var(--space-4);
          background: var(--bg-elevated);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          cursor: pointer;
          transition: all 0.2s;
        }
        .picks-card:hover {
          border-color: rgba(0, 212, 170, 0.3);
          background: rgba(0, 212, 170, 0.04);
        }
        .picks-card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: var(--space-2);
        }
        .picks-fund-name {
          font-size: var(--text-base);
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 2px;
        }
        .picks-fund-meta {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .picks-score {
          text-align: right;
        }
        .picks-score-value {
          font-size: var(--text-xl);
          font-weight: 700;
        }
        .picks-score-label {
          font-size: 10px;
          color: var(--text-secondary);
        }
        .picks-reason {
          font-size: var(--text-sm);
          color: var(--text-primary);
          margin-bottom: var(--space-3);
          line-height: 1.5;
        }
        .picks-footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .picks-tags {
          display: flex;
          gap: var(--space-2);
        }
        .picks-tag {
          padding: 2px 8px;
          font-size: var(--text-xs);
          border-radius: var(--radius-sm);
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid var(--border);
        }
        .picks-labels {
          display: flex;
          gap: 4px;
        }
        .picks-label {
          padding: 2px 6px;
          font-size: 10px;
          border-radius: 3px;
          background: var(--accent-dim);
          color: var(--accent);
        }
        .picks-cta {
          margin-top: var(--space-3);
          padding: 8px;
          text-align: center;
          background: var(--accent);
          border-radius: var(--radius-sm);
          color: var(--bg-primary);
          font-size: var(--text-xs);
          font-weight: 600;
        }
        .picks-disclaimer {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          text-align: center;
          margin-top: var(--space-4);
          padding: var(--space-3);
          border-top: 1px solid var(--border);
          line-height: 1.6;
        }
      `}</style>
    </div>
  );
}
