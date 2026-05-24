"use client";

interface FundTypeData {
  fund_type: string;
  risk_level: string;
  description: string;
  characteristics: string[];
}

interface Props {
  data: FundTypeData;
  fundName: string;
}

const RISK_COLORS: Record<string, string> = {
  "极低": "var(--green)",
  "低": "var(--green)",
  "中": "var(--gold)",
  "中高": "var(--gold)",
  "高": "var(--red)",
};

const TYPE_ICONS: Record<string, string> = {
  "股票型": "📈",
  "混合型": "⚖",
  "债券型": "📋",
  "货币型": "💰",
  "指数型": "📊",
  "QDII型": "🌍",
};

export default function UnderlyingAnalysis({ data, fundName }: Props) {
  const riskColor = RISK_COLORS[data.risk_level] || "var(--text-secondary)";
  const typeIcon = TYPE_ICONS[data.fund_type] || "📁";

  return (
    <>
      <div className="underlying-header">
        <div className="underlying-type">
          <span className="underlying-type-icon">{typeIcon}</span>
          <div>
            <div className="underlying-type-label">基金类型</div>
            <div className="underlying-type-value">{data.fund_type}</div>
          </div>
        </div>
        <div className="underlying-risk">
          <div className="underlying-risk-label">风险等级</div>
          <div className="underlying-risk-value" style={{ color: riskColor }}>
            {data.risk_level}
          </div>
        </div>
      </div>

      <div className="underlying-desc">{data.description}</div>

      <div className="underlying-characteristics">
        <div className="underlying-char-title">基金特征</div>
        <div className="underlying-char-grid">
          {data.characteristics.map((char, i) => (
            <div key={i} className="underlying-char-tag">
              {char}
            </div>
          ))}
        </div>
      </div>

      <div className="underlying-name">
        <span className="underlying-name-label">基金名称</span>
        <span className="underlying-name-value">{fundName}</span>
      </div>

      <style jsx>{`
        .underlying-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: var(--space-4);
          padding: var(--space-4);
          background: rgba(255, 255, 255, 0.03);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .underlying-type {
          display: flex;
          align-items: center;
          gap: var(--space-3);
        }
        .underlying-type-icon {
          font-size: 28px;
        }
        .underlying-type-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .underlying-type-value {
          font-size: var(--text-lg);
          font-weight: 700;
          color: var(--accent);
        }
        .underlying-risk {
          text-align: right;
        }
        .underlying-risk-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .underlying-risk-value {
          font-size: var(--text-lg);
          font-weight: 700;
        }
        .underlying-desc {
          font-size: var(--text-sm);
          color: var(--text-secondary);
          line-height: 1.6;
          margin-bottom: 16px;
        }
        .underlying-characteristics {
          margin-bottom: var(--space-4);
        }
        .underlying-char-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          margin-bottom: var(--space-3);
          border-left: 3px solid var(--accent);
          padding-left: var(--space-2);
        }
        .underlying-char-grid {
          display: flex;
          flex-wrap: wrap;
          gap: var(--space-2);
        }
        .underlying-char-tag {
          padding: 6px 12px;
          background: rgba(0, 212, 170, 0.08);
          border: 1px solid rgba(0, 212, 170, 0.2);
          border-radius: var(--radius-full);
          font-size: var(--text-xs);
          color: var(--accent);
          font-weight: 500;
        }
        .underlying-name {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px var(--space-4);
          background: rgba(255, 255, 255, 0.02);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .underlying-name-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .underlying-name-value {
          font-size: var(--text-sm);
          font-weight: 600;
          color: var(--text-primary);
        }
      `}</style>
    </>
  );
}
