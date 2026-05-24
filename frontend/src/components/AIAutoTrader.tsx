"use client";

import { useState } from "react";

interface AutoTradeConfig {
  enabled: boolean;
  maxAmount: number;
  riskLevel: "保守" | "稳健" | "积极";
  strategy: "定投" | "信号" | "混合";
}

interface TradeSuggestion {
  fundCode: string;
  fundName: string;
  action: "买入" | "观望" | "卖出";
  amount: number;
  reason: string;
  confidence: number;
}

const MOCK_SUGGESTIONS: TradeSuggestion[] = [
  { fundCode: "000001", fundName: "华夏成长混合", action: "买入", amount: 5000, reason: "信号强度高，趋势向上，建议建仓", confidence: 85 },
  { fundCode: "110011", fundName: "易方达中小盘混合", action: "观望", amount: 0, reason: "近期波动较大，建议等待回调", confidence: 60 },
  { fundCode: "000961", fundName: "天弘沪深300ETF联接A", action: "买入", amount: 3000, reason: "指数基金适合定投，当前估值合理", confidence: 75 },
];

function getActionColor(action: string): string {
  if (action === "买入") return "var(--green)";
  if (action === "卖出") return "var(--red)";
  return "var(--gold)";
}

function getConfidenceColor(confidence: number): string {
  if (confidence >= 80) return "var(--green)";
  if (confidence >= 60) return "var(--gold)";
  return "var(--red)";
}

export default function AIAutoTrader({ onExecuteTrade }: { onExecuteTrade: (code: string, amount: number) => void }) {
  const [config, setConfig] = useState<AutoTradeConfig>({
    enabled: false,
    maxAmount: 10000,
    riskLevel: "稳健",
    strategy: "混合",
  });

  const [suggestions] = useState<TradeSuggestion[]>(MOCK_SUGGESTIONS);

  return (
    <div>
      {/* 标题和开关 */}
      <div className="trader-header">
        <div className="trader-title">AI 自动交易助手</div>
        <div className="trader-toggle-wrap">
          <span className="trader-toggle-label">自动交易</span>
          <div className={`trader-toggle ${config.enabled ? "trader-toggle-on" : ""}`} onClick={() => setConfig((p) => ({ ...p, enabled: !p.enabled }))}>
            <div className="trader-toggle-knob" />
          </div>
        </div>
      </div>

      {/* 配置面板 */}
      <div className="trader-config">
        <div className="trader-config-label">交易配置</div>
        <div className="trader-config-grid">
          <div>
            <div className="trader-field-label">单笔最大金额</div>
            <input
              type="number"
              value={config.maxAmount}
              onChange={(e) => setConfig((p) => ({ ...p, maxAmount: Number(e.target.value) }))}
              className="trader-input"
            />
          </div>
          <div>
            <div className="trader-field-label">风险偏好</div>
            <select value={config.riskLevel} onChange={(e) => setConfig((p) => ({ ...p, riskLevel: e.target.value as any }))} className="trader-input">
              <option value="保守">保守</option>
              <option value="稳健">稳健</option>
              <option value="积极">积极</option>
            </select>
          </div>
          <div>
            <div className="trader-field-label">交易策略</div>
            <select value={config.strategy} onChange={(e) => setConfig((p) => ({ ...p, strategy: e.target.value as any }))} className="trader-input">
              <option value="定投">定投</option>
              <option value="信号">信号</option>
              <option value="混合">混合</option>
            </select>
          </div>
        </div>
      </div>

      {/* AI 状态 */}
      <div className={`trader-status ${config.enabled ? "trader-status-on" : ""}`}>
        <div className="trader-status-title">
          <span>{config.enabled ? "  " : "  "}</span>
          <span>{config.enabled ? "AI 自动交易已开启" : "AI 自动交易已关闭"}</span>
        </div>
        <div>{config.enabled ? "AI 将根据市场信号和您的配置，自动为您推荐买入时机和金额。" : "开启自动交易后，AI 将根据市场信号为您推荐买入时机。"}</div>
      </div>

      {/* 建议列表 */}
      <div className="trader-list-label">今日交易建议</div>
      <div className="trader-list">
        {suggestions.map((s) => (
          <div key={s.fundCode} className="trader-suggestion">
            <div className="trader-suggestion-header">
              <div>
                <div className="trader-fund-name">{s.fundName}</div>
                <div className="trader-fund-code">{s.fundCode}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: "var(--text-base)", fontWeight: 700, color: getActionColor(s.action) }}>{s.action}</div>
                {s.amount > 0 && <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>¥{s.amount.toLocaleString()}</div>}
              </div>
            </div>
            <div className="trader-reason">{s.reason}</div>
            <div className="trader-suggestion-footer">
              <div>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>置信度：</span>
                <span style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: getConfidenceColor(s.confidence) }}>{s.confidence}%</span>
              </div>
              {s.action === "买入" && s.amount > 0 && (
                <button className="btn btn-primary" style={{ padding: "4px 12px", fontSize: "var(--text-xs)" }} onClick={() => onExecuteTrade(s.fundCode, s.amount)} disabled={!config.enabled}>
                  执行买入
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="trader-disclaimer">
        <div>⚠ 自动交易存在风险，请谨慎使用</div>
        <div>AI建议仅供参考，实际交易需您手动确认执行</div>
      </div>

      <style jsx>{`
        .trader-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: var(--space-4);
        }
        .trader-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
        }
        .trader-toggle-wrap {
          display: flex;
          align-items: center;
          gap: var(--space-2);
        }
        .trader-toggle-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .trader-toggle {
          width: 44px;
          height: 24px;
          border-radius: 12px;
          background: var(--border);
          cursor: pointer;
          position: relative;
          transition: background 0.2s;
        }
        .trader-toggle-on {
          background: var(--accent);
        }
        .trader-toggle-knob {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: white;
          position: absolute;
          top: 2px;
          left: 2px;
          transition: left 0.2s;
        }
        .trader-toggle-on .trader-toggle-knob {
          left: 22px;
        }
        .trader-config {
          padding: var(--space-4);
          background: rgba(255, 255, 255, 0.02);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          margin-bottom: var(--space-4);
        }
        .trader-config-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: var(--space-3);
        }
        .trader-config-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: var(--space-3);
        }
        .trader-field-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: 4px;
        }
        .trader-input {
          width: 100%;
          padding: 6px 8px;
          font-size: var(--text-sm);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          background: var(--bg-primary);
          color: var(--text-primary);
          outline: none;
        }
        .trader-input:focus {
          border-color: var(--accent);
        }
        .trader-status {
          padding: 12px;
          background: rgba(255, 255, 255, 0.02);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          margin-bottom: var(--space-4);
          font-size: var(--text-xs);
          color: var(--text-secondary);
          line-height: 1.6;
        }
        .trader-status-on {
          background: rgba(0, 212, 170, 0.04);
          border-color: rgba(0, 212, 170, 0.15);
        }
        .trader-status-title {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          margin-bottom: 4px;
          font-weight: 600;
          color: var(--text-secondary);
        }
        .trader-status-on .trader-status-title {
          color: var(--accent);
        }
        .trader-list-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: var(--space-2);
        }
        .trader-list {
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }
        .trader-suggestion {
          padding: 12px;
          background: var(--bg-elevated);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .trader-suggestion-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: var(--space-2);
        }
        .trader-fund-name {
          font-size: var(--text-sm);
          font-weight: 600;
          color: var(--text-primary);
        }
        .trader-fund-code {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .trader-reason {
          font-size: var(--text-xs);
          color: var(--text-primary);
          margin-bottom: var(--space-2);
          line-height: 1.5;
        }
        .trader-suggestion-footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .trader-disclaimer {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          text-align: center;
          margin-top: var(--space-4);
          padding: var(--space-3);
          border-top: 1px solid var(--border);
          line-height: 1.6;
        }
        @media (max-width: 640px) {
          .trader-config-grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  );
}
