"use client";

interface MacroData {
  stage: string;
  stage_cn: string;
  description: string;
  advice: string;
}

interface Props {
  data: MacroData;
}

const STAGES = [
  { key: "recovery", label: "复苏", icon: "🌱", color: "var(--green)", pos: "top-left" },
  { key: "overheat", label: "过热", icon: "🔥", color: "var(--gold)", pos: "top-right" },
  { key: "stagflation", label: "滞胀", icon: "❄", color: "var(--accent-blue)", pos: "bottom-right" },
  { key: "recession", label: "衰退", icon: "📉", color: "var(--red)", pos: "bottom-left" },
];

export default function MacroClockView({ data }: Props) {
  const currentStage = STAGES.find((s) => s.key === data.stage) || STAGES[0];

  return (
    <>
      <div className="macro-layout">
        {/* 时钟四象限 */}
        <div className="macro-clock">
          <div className="macro-clock-axes">
            <div className="macro-axis-x">
              <span className="macro-axis-label">低波动</span>
              <span className="macro-axis-label">高波动</span>
            </div>
            <div className="macro-axis-y">
              <span className="macro-axis-label">高收益</span>
              <span className="macro-axis-label">低收益</span>
            </div>
          </div>
          {STAGES.map((stage) => (
            <div
              key={stage.key}
              className={`macro-quadrant macro-${stage.pos} ${
                data.stage === stage.key ? "macro-quadrant-active" : ""
              }`}
              style={{
                borderColor: data.stage === stage.key ? stage.color : undefined,
                background: data.stage === stage.key ? `${stage.color}11` : undefined,
              }}
            >
              <span className="macro-quadrant-icon">{stage.icon}</span>
              <span className="macro-quadrant-label" style={{
                color: data.stage === stage.key ? stage.color : "var(--text-secondary)"
              }}>
                {stage.label}
              </span>
              {data.stage === stage.key && (
                <span className="macro-quadrant-dot" style={{ background: stage.color }} />
              )}
            </div>
          ))}
        </div>

        {/* 当前阶段信息 */}
        <div className="macro-info">
          <div className="macro-current">
            <span className="macro-current-icon">{currentStage.icon}</span>
            <div>
              <div className="macro-current-label">当前经济阶段</div>
              <div className="macro-current-stage" style={{ color: currentStage.color }}>
                {data.stage_cn}
              </div>
            </div>
          </div>
          <div className="macro-description">{data.description}</div>
          <div className="macro-advice">
            <div className="macro-advice-title">投资建议</div>
            <div className="macro-advice-text">{data.advice}</div>
          </div>
        </div>
      </div>

      <style jsx>{`
        .macro-layout {
          display: flex;
          gap: 24px;
          align-items: flex-start;
        }
        .macro-clock {
          width: 200px;
          height: 200px;
          position: relative;
          flex-shrink: 0;
          display: grid;
          grid-template-columns: 1fr 1fr;
          grid-template-rows: 1fr 1fr;
          gap: 4px;
        }
        .macro-clock-axes {
          position: absolute;
          inset: 0;
          pointer-events: none;
        }
        .macro-axis-x {
          position: absolute;
          top: 50%;
          left: 0;
          right: 0;
          display: flex;
          justify-content: space-between;
          padding: 0 2px;
          transform: translateY(-50%);
        }
        .macro-axis-y {
          position: absolute;
          left: 50%;
          top: 0;
          bottom: 0;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 2px 0;
          transform: translateX(-50%);
        }
        .macro-axis-label {
          font-size: 9px;
          color: var(--text-secondary);
          opacity: 0.6;
          background: var(--bg-card);
          padding: 1px 3px;
          border-radius: 2px;
        }
        .macro-quadrant {
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 4px;
          transition: all 0.3s;
          position: relative;
        }
        .macro-quadrant-active {
          transform: scale(1.05);
          box-shadow: 0 0 12px rgba(0, 0, 0, 0.3);
        }
        .macro-quadrant-icon {
          font-size: var(--text-xl);
        }
        .macro-quadrant-label {
          font-size: var(--text-xs);
          font-weight: 600;
        }
        .macro-quadrant-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          position: absolute;
          bottom: 6px;
        }
        .macro-info {
          flex: 1;
          min-width: 0;
        }
        .macro-current {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: var(--space-4);
          padding: var(--space-4);
          background: rgba(255, 255, 255, 0.03);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
        }
        .macro-current-icon {
          font-size: 28px;
        }
        .macro-current-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .macro-current-stage {
          font-size: var(--text-xl);
          font-weight: 700;
        }
        .macro-description {
          font-size: var(--text-sm);
          color: var(--text-secondary);
          line-height: 1.6;
          margin-bottom: 12px;
        }
        .macro-advice {
          background: rgba(0, 212, 170, 0.06);
          border: 1px solid rgba(0, 212, 170, 0.2);
          border-radius: var(--radius-md);
          padding: var(--space-3);
        }
        .macro-advice-title {
          font-size: var(--text-xs);
          color: var(--accent);
          font-weight: 600;
          margin-bottom: 6px;
        }
        .macro-advice-text {
          font-size: var(--text-sm);
          color: var(--text-primary);
          line-height: 1.6;
        }
        @media (max-width: 640px) {
          .macro-layout {
            flex-direction: column;
            align-items: center;
          }
          .macro-clock {
            width: 180px;
            height: 180px;
          }
        }
      `}</style>
    </>
  );
}
