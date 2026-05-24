"use client";

interface CycleData {
  rsi: number;
  percentile: number;
  ma_deviation: number;
  status: "strong" | "weak" | "neutral";
  annual_return: number;
  show_warning: boolean;
  signals: string[];
}

interface Props {
  data: CycleData;
}

function pct(v: number) {
  return v.toFixed(2) + "%";
}

const STATUS_MAP = {
  strong: { label: "强周期", color: "var(--red)", icon: "🔴", desc: "价格处于高位区间，追高需谨慎" },
  neutral: { label: "中性周期", color: "var(--gold)", icon: "🟡", desc: "价格处于正常波动区间" },
  weak: { label: "弱周期", color: "var(--green)", icon: "🟢", desc: "价格处于低位区间，可能存在机会" },
};

export default function CycleIndicator({ data }: Props) {
  const statusInfo = STATUS_MAP[data.status];

  return (
    <>
      {/* 涨幅警示 */}
      {data.show_warning && (
        <div className="cycle-warning-banner">
          <span className="cycle-warning-icon">⚠</span>
          <div>
            <div className="cycle-warning-title">涨幅警示</div>
            <div className="cycle-warning-text">
              过去一年涨幅达 {pct(data.annual_return)}，但过去涨不代表未来涨，请理性投资。
            </div>
          </div>
        </div>
      )}

      {/* 红绿灯状态 */}
      <div className="cycle-status-bar">
        <div className="cycle-light-group">
          <div className={`cycle-light ${data.status === "weak" ? "cycle-light-active cycle-light-green" : ""}`} />
          <div className={`cycle-light ${data.status === "neutral" ? "cycle-light-active cycle-light-yellow" : ""}`} />
          <div className={`cycle-light ${data.status === "strong" ? "cycle-light-active cycle-light-red" : ""}`} />
        </div>
        <div className="cycle-status-info">
          <span className="cycle-status-label" style={{ color: statusInfo.color }}>
            {statusInfo.icon} {statusInfo.label}
          </span>
          <span className="cycle-status-desc">{statusInfo.desc}</span>
        </div>
      </div>

      {/* 核心指标 */}
      <div className="cycle-metrics-grid">
        <div className="cycle-metric-card">
          <div className="cycle-metric-label">RSI (14)</div>
          <div className="cycle-rsi-gauge">
            <div className="cycle-rsi-bar">
              <div
                className="cycle-rsi-fill"
                style={{
                  width: `${data.rsi}%`,
                  background: data.rsi > 70 ? "var(--red)" : data.rsi < 30 ? "var(--green)" : "var(--accent)",
                }}
              />
              <div className="cycle-rsi-marker" style={{ left: `${data.rsi}%` }} />
            </div>
            <div className="cycle-rsi-labels">
              <span>0</span>
              <span className="cycle-rsi-zone" style={{ color: "var(--green)" }}>超卖 &lt;30</span>
              <span className="cycle-rsi-zone" style={{ color: "var(--red)" }}>超买 &gt;70</span>
              <span>100</span>
            </div>
          </div>
          <div className="cycle-metric-value" style={{
            color: data.rsi > 70 ? "var(--red)" : data.rsi < 30 ? "var(--green)" : "var(--text-primary)"
          }}>
            {data.rsi}
          </div>
        </div>

        <div className="cycle-metric-card">
          <div className="cycle-metric-label">历史百分位</div>
          <div className="cycle-percentile-bar">
            <div
              className="cycle-percentile-fill"
              style={{
                width: `${data.percentile}%`,
                background: data.percentile > 80 ? "var(--red)" : data.percentile < 20 ? "var(--green)" : "var(--accent)",
              }}
            />
          </div>
          <div className="cycle-percentile-labels">
            <span>0%</span>
            <span>100%</span>
          </div>
          <div className="cycle-metric-value" style={{
            color: data.percentile > 80 ? "var(--red)" : data.percentile < 20 ? "var(--green)" : "var(--text-primary)"
          }}>
            {data.percentile}%
          </div>
        </div>

        <div className="cycle-metric-card">
          <div className="cycle-metric-label">均线乖离率 (20日)</div>
          <div className="cycle-metric-value" style={{
            color: data.ma_deviation > 5 ? "var(--red)" : data.ma_deviation < -5 ? "var(--green)" : "var(--text-primary)"
          }}>
            {data.ma_deviation > 0 ? "+" : ""}{data.ma_deviation}%
          </div>
          <div className="cycle-deviation-hint">
            {data.ma_deviation > 5 ? "偏高，存在回归风险" : data.ma_deviation < -5 ? "偏低，可能存在反弹" : "正常区间"}
          </div>
        </div>

        <div className="cycle-metric-card">
          <div className="cycle-metric-label">过去一年涨幅</div>
          <div className={`cycle-metric-value ${data.annual_return >= 0 ? "positive" : "negative"}`}>
            {data.annual_return > 0 ? "+" : ""}{data.annual_return}%
          </div>
          {data.show_warning && (
            <div className="cycle-return-warn">涨幅较大，请注意风险</div>
          )}
        </div>
      </div>

      {/* 信号列表 */}
      <div className="cycle-signals">
        <div className="cycle-signals-title">分析信号</div>
        {data.signals.map((signal, i) => (
          <div key={i} className="cycle-signal-item">
            <span className="cycle-signal-dot">•</span>
            <span>{signal}</span>
          </div>
        ))}
      </div>

      <style jsx>{`
        .cycle-warning-banner {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: var(--space-4) var(--space-4);
          background: rgba(255, 192, 72, 0.1);
          border: 1px solid rgba(255, 192, 72, 0.3);
          border-radius: var(--radius-md);
          margin-bottom: 16px;
        }
        .cycle-warning-icon {
          font-size: 24px;
          flex-shrink: 0;
        }
        .cycle-warning-title {
          font-size: var(--text-sm);
          font-weight: 700;
          color: var(--gold);
          margin-bottom: 2px;
        }
        .cycle-warning-text {
          font-size: var(--text-sm);
          color: var(--text-secondary);
          line-height: 1.5;
        }
        .cycle-status-bar {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: var(--space-4);
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          margin-bottom: 16px;
        }
        .cycle-light-group {
          display: flex;
          gap: 8px;
          flex-shrink: 0;
        }
        .cycle-light {
          width: 20px;
          height: 20px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.08);
          border: 2px solid rgba(255, 255, 255, 0.1);
          transition: all 0.3s;
        }
        .cycle-light-active {
          box-shadow: 0 0 8px currentColor;
        }
        .cycle-light-green {
          background: var(--green);
          border-color: var(--green);
          box-shadow: 0 0 10px rgba(0, 212, 170, 0.5);
        }
        .cycle-light-yellow {
          background: var(--gold);
          border-color: var(--gold);
          box-shadow: 0 0 10px rgba(255, 192, 72, 0.5);
        }
        .cycle-light-red {
          background: var(--red);
          border-color: var(--red);
          box-shadow: 0 0 10px rgba(255, 71, 87, 0.5);
        }
        .cycle-status-info {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .cycle-status-label {
          font-size: var(--text-lg);
          font-weight: 700;
        }
        .cycle-status-desc {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .cycle-metrics-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 12px;
          margin-bottom: 16px;
        }
        .cycle-metric-card {
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-4);
        }
        .cycle-metric-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: 10px;
        }
        .cycle-metric-value {
          font-size: var(--text-xl);
          font-weight: 700;
          text-align: center;
          margin-top: var(--space-2);
        }
        .cycle-rsi-gauge {
          margin-bottom: 4px;
        }
        .cycle-rsi-bar {
          width: 100%;
          height: 8px;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 4px;
          position: relative;
          overflow: visible;
        }
        .cycle-rsi-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.5s;
        }
        .cycle-rsi-marker {
          position: absolute;
          top: -4px;
          width: 4px;
          height: 16px;
          background: var(--text-primary);
          border-radius: 2px;
          transform: translateX(-50%);
          transition: left 0.5s;
        }
        .cycle-rsi-labels {
          display: flex;
          justify-content: space-between;
          font-size: 10px;
          color: var(--text-secondary);
          margin-top: var(--space-1);
        }
        .cycle-rsi-zone {
          font-weight: 600;
        }
        .cycle-percentile-bar {
          width: 100%;
          height: 8px;
          background: rgba(255, 255, 255, 0.08);
          border-radius: 4px;
          overflow: hidden;
          margin-bottom: 4px;
        }
        .cycle-percentile-fill {
          height: 100%;
          border-radius: 4px;
          transition: width 0.5s;
        }
        .cycle-percentile-labels {
          display: flex;
          justify-content: space-between;
          font-size: 10px;
          color: var(--text-secondary);
        }
        .cycle-deviation-hint {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          text-align: center;
          margin-top: var(--space-1);
        }
        .cycle-return-warn {
          font-size: var(--text-xs);
          color: var(--gold);
          text-align: center;
          margin-top: 4px;
          font-weight: 600;
        }
        .cycle-signals {
          background: rgba(255, 255, 255, 0.02);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: var(--space-4);
        }
        .cycle-signals-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          margin-bottom: 10px;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
        }
        .cycle-signal-item {
          display: flex;
          align-items: flex-start;
          gap: var(--space-2);
          font-size: var(--text-sm);
          color: var(--text-secondary);
          padding: 4px 0;
          line-height: 1.5;
        }
        .cycle-signal-dot {
          color: var(--accent);
          flex-shrink: 0;
        }
        @media (max-width: 640px) {
          .cycle-metrics-grid {
            grid-template-columns: 1fr;
          }
          .cycle-status-bar {
            flex-direction: column;
            text-align: center;
          }
        }
      `}</style>
    </>
  );
}
