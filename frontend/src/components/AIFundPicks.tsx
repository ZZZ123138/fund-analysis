"use client";

import { useState } from "react";

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

const AI_PICKS: FundRecommendation[] = [
  { code: "000001", name: "华夏成长混合", type: "混合型", reason: "长期业绩稳定，基金经理经验丰富，适合稳健型投资者", score: 92, risk: "中", expectedReturn: "年化8-12%", tags: ["稳健", "长期", "明星基金"] },
  { code: "110011", name: "易方达中小盘混合", type: "混合型", reason: "聚焦中小盘成长股，历史收益优秀，适合追求高收益的投资者", score: 88, risk: "高", expectedReturn: "年化12-18%", tags: ["成长", "中小盘", "高收益"] },
  { code: "000961", name: "天弘沪深300ETF联接A", type: "指数型", reason: "跟踪沪深300指数，费率低，适合长期定投", score: 85, risk: "中", expectedReturn: "年化6-10%", tags: ["指数", "定投", "低费率"] },
  { code: "001632", name: "天弘创业板ETF联接A", type: "指数型", reason: "跟踪创业板指数，科技成长属性强", score: 82, risk: "高", expectedReturn: "年化10-15%", tags: ["科技", "成长", "创业板"] },
  { code: "000478", name: "建信中债1-3年国开行债券指数A", type: "债券型", reason: "低风险债券基金，收益稳定，适合保守型投资者", score: 78, risk: "低", expectedReturn: "年化3-5%", tags: ["债券", "低风险", "稳健"] },
  { code: "000831", name: "工银瑞信前沿医疗股票", type: "股票型", reason: "聚焦医疗健康行业，长期成长性好", score: 86, risk: "高", expectedReturn: "年化10-15%", tags: ["医疗", "健康", "行业主题"] },
];

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
  const types = ["全部", "混合型", "指数型", "债券型", "股票型"];

  const filteredPicks = selectedType === "全部"
    ? AI_PICKS
    : AI_PICKS.filter((pick) => pick.type === selectedType);

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
        {filteredPicks.map((fund) => (
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
