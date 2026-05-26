"use client";

import { useState, useEffect } from "react";

interface WatchlistItem {
  fund_code: string;
  fund_name: string;
  enabled: number;
}

interface NotificationConfig {
  serverchan_key: string;
  enabled: boolean;
  check_interval_minutes: number;
}

export default function MarketMonitor() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [config, setConfig] = useState<NotificationConfig>({
    serverchan_key: "",
    enabled: false,
    check_interval_minutes: 60,
  });
  const [addCode, setAddCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  };

  const loadData = async () => {
    try {
      const [wl, nc] = await Promise.all([
        fetch("/api/watchlist").then((r) => r.json()),
        fetch("/api/notification/config").then((r) => r.json()),
      ]);
      setWatchlist(wl);
      setConfig(nc);
    } catch {}
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleAdd = async () => {
    if (!addCode.match(/^\d{6}$/)) {
      showToast("请输入6位基金代码");
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fund_code: addCode }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setAddCode("");
        showToast(`已添加 ${data.fund_name}`);
        loadData();
      } else {
        showToast(data.detail || "添加失败");
      }
    } catch {
      showToast("网络错误");
    }
    setLoading(false);
  };

  const handleRemove = async (code: string) => {
    try {
      await fetch(`/api/watchlist/${code}`, { method: "DELETE" });
      showToast("已移除");
      loadData();
    } catch {
      showToast("操作失败");
    }
  };

  const handleToggle = async (code: string, enabled: number) => {
    try {
      await fetch(`/api/watchlist/${code}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled ? 0 : 1 }),
      });
      loadData();
    } catch {}
  };

  const handleSaveConfig = async () => {
    try {
      const resp = await fetch("/api/notification/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
      });
      if (resp.ok) showToast("配置已保存");
    } catch {
      showToast("保存失败");
    }
  };

  const handleTest = async () => {
    try {
      const resp = await fetch("/api/notification/test", { method: "POST" });
      const data = await resp.json();
      showToast(data.message);
    } catch {
      showToast("测试失败");
    }
  };

  return (
    <>
      <div className="mm-section">
        <div className="mm-title">关注列表</div>
        <div className="mm-desc">添加要监控的基金，开盘期间自动分析信号并推送</div>

        <div className="mm-add-row">
          <input
            type="text"
            value={addCode}
            onChange={(e) => setAddCode(e.target.value)}
            placeholder="输入基金代码 如 000001"
            className="mm-input"
            maxLength={6}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          />
          <button className="btn btn-primary mm-btn" onClick={handleAdd} disabled={loading}>
            {loading ? "添加中..." : "添加"}
          </button>
        </div>

        {watchlist.length === 0 ? (
          <div className="mm-empty">暂无关注基金，添加后自动监控</div>
        ) : (
          <div className="mm-list">
            {watchlist.map((item) => (
              <div key={item.fund_code} className="mm-item">
                <div className="mm-item-info">
                  <div className="mm-item-name">{item.fund_name}</div>
                  <div className="mm-item-code">{item.fund_code}</div>
                </div>
                <div className="mm-item-actions">
                  <div
                    className={`mm-switch ${item.enabled ? "mm-switch-on" : ""}`}
                    onClick={() => handleToggle(item.fund_code, item.enabled)}
                  >
                    <div className="mm-switch-knob" />
                  </div>
                  <button className="mm-remove" onClick={() => handleRemove(item.fund_code)}>
                    移除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mm-section">
        <div className="mm-title">微信推送配置</div>
        <div className="mm-desc">
          使用{" "}
          <a href="https://sct.ftqq.com/" target="_blank" rel="noopener" className="mm-link">
            Server酱
          </a>{" "}
          免费推送到微信
        </div>

        <div className="mm-config-grid">
          <div className="mm-field">
            <label className="mm-label">Server酱 SendKey</label>
            <input
              type="text"
              value={config.serverchan_key}
              onChange={(e) => setConfig((p) => ({ ...p, serverchan_key: e.target.value }))}
              placeholder="SCT..."
              className="mm-input"
            />
          </div>
          <div className="mm-field">
            <label className="mm-label">启用推送</label>
            <div
              className={`mm-switch ${config.enabled ? "mm-switch-on" : ""}`}
              onClick={() => setConfig((p) => ({ ...p, enabled: !p.enabled }))}
            >
              <div className="mm-switch-knob" />
            </div>
          </div>
        </div>

        <div className="mm-actions">
          <button className="btn btn-primary mm-btn" onClick={handleSaveConfig}>
            保存配置
          </button>
          <button className="btn mm-btn mm-btn-outline" onClick={handleTest}>
            测试推送
          </button>
        </div>
      </div>

      <div className="mm-section mm-section-info">
        <div className="mm-title">监控规则</div>
        <div className="mm-rules">
          <div className="mm-rule">
            <span className="mm-rule-icon" style={{ color: "var(--green)" }}>●</span>
            <span>RSI &lt; 30 + 百分位 &lt; 20% → 买入信号</span>
          </div>
          <div className="mm-rule">
            <span className="mm-rule-icon" style={{ color: "var(--red)" }}>●</span>
            <span>RSI &gt; 70 + 百分位 &gt; 80% → 卖出信号</span>
          </div>
          <div className="mm-rule">
            <span className="mm-rule-icon" style={{ color: "var(--gold)" }}>●</span>
            <span>年涨幅 &gt; 20% → 止盈提醒</span>
          </div>
          <div className="mm-rule">
            <span className="mm-rule-icon" style={{ color: "var(--text-secondary)" }}>●</span>
            <span>周一至周五 9:30-15:00 每小时检查一次</span>
          </div>
        </div>
      </div>

      {toast && <div className="toast">{toast}</div>}

      <style jsx>{`
        .mm-section {
          padding: var(--space-4);
          background: rgba(255, 255, 255, 0.02);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          margin-bottom: var(--space-3);
        }
        .mm-section-info {
          background: rgba(0, 212, 170, 0.03);
          border-color: rgba(0, 212, 170, 0.1);
        }
        .mm-title {
          font-size: var(--text-sm);
          color: var(--accent);
          font-weight: 600;
          border-left: 3px solid var(--accent);
          padding-left: 8px;
          margin-bottom: var(--space-2);
        }
        .mm-desc {
          font-size: var(--text-xs);
          color: var(--text-secondary);
          margin-bottom: var(--space-3);
          line-height: 1.5;
        }
        .mm-add-row {
          display: flex;
          gap: var(--space-2);
          margin-bottom: var(--space-3);
        }
        .mm-input {
          flex: 1;
          padding: 8px 12px;
          font-size: var(--text-sm);
          border: 1px solid var(--border);
          border-radius: var(--radius-sm);
          background: var(--bg-primary);
          color: var(--text-primary);
          outline: none;
        }
        .mm-input:focus {
          border-color: var(--accent);
        }
        .mm-btn {
          padding: 8px 16px;
          font-size: var(--text-sm);
          border-radius: var(--radius-sm);
          cursor: pointer;
          white-space: nowrap;
        }
        .mm-btn-outline {
          background: transparent;
          border: 1px solid var(--border);
          color: var(--text-secondary);
        }
        .mm-btn-outline:hover {
          border-color: var(--accent);
          color: var(--accent);
        }
        .mm-empty {
          text-align: center;
          padding: var(--space-4);
          font-size: var(--text-xs);
          color: var(--text-tertiary);
        }
        .mm-list {
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }
        .mm-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px var(--space-3);
          background: var(--bg-elevated);
          border-radius: var(--radius-sm);
          border: 1px solid var(--border);
        }
        .mm-item-name {
          font-size: var(--text-sm);
          font-weight: 600;
          color: var(--text-primary);
        }
        .mm-item-code {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .mm-item-actions {
          display: flex;
          align-items: center;
          gap: var(--space-3);
        }
        .mm-switch {
          width: 40px;
          height: 22px;
          border-radius: 11px;
          background: var(--border);
          cursor: pointer;
          position: relative;
          transition: background 0.2s;
        }
        .mm-switch-on {
          background: var(--accent);
        }
        .mm-switch-knob {
          width: 18px;
          height: 18px;
          border-radius: 50%;
          background: white;
          position: absolute;
          top: 2px;
          left: 2px;
          transition: left 0.2s;
        }
        .mm-switch-on .mm-switch-knob {
          left: 20px;
        }
        .mm-remove {
          font-size: var(--text-xs);
          color: var(--text-tertiary);
          background: none;
          border: none;
          cursor: pointer;
        }
        .mm-remove:hover {
          color: var(--red);
        }
        .mm-config-grid {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: var(--space-3);
          align-items: end;
          margin-bottom: var(--space-3);
        }
        .mm-field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .mm-label {
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .mm-actions {
          display: flex;
          gap: var(--space-2);
        }
        .mm-link {
          color: var(--accent);
          text-decoration: underline;
        }
        .mm-rules {
          display: flex;
          flex-direction: column;
          gap: var(--space-2);
        }
        .mm-rule {
          display: flex;
          align-items: center;
          gap: var(--space-2);
          font-size: var(--text-xs);
          color: var(--text-secondary);
        }
        .mm-rule-icon {
          font-size: 8px;
        }
        @media (max-width: 640px) {
          .mm-config-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </>
  );
}
