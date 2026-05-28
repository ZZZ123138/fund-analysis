"""策略进化系统：候选策略管理 + 行为指纹 + 异常检测"""
import json
from datetime import datetime, date, timedelta
from typing import Optional
from database import SessionLocal
from models import (
    StrategyCandidate, BehaviorFingerprint, AnomalyAlert,
    TradeRecord, VirtualTrade,
)


# ==================== 策略候选管理 ====================

def submit_candidate(
    name: str,
    strategy_type: str,
    parameters: dict,
    logic_code: str,
    description: str = "",
    source: str = "backtest",
    backtest_results: dict = None,
) -> StrategyCandidate:
    """提交候选策略（学习层 → 审核层）"""
    db = SessionLocal()
    try:
        candidate = StrategyCandidate(
            name=name,
            description=description,
            strategy_type=strategy_type,
            parameters=json.dumps(parameters, ensure_ascii=False),
            logic_code=logic_code,
            source=source,
            status="pending",
        )
        if backtest_results:
            candidate.backtest_return = backtest_results.get("return")
            candidate.backtest_sharpe = backtest_results.get("sharpe")
            candidate.backtest_max_dd = backtest_results.get("max_dd")
            candidate.backtest_win_rate = backtest_results.get("win_rate")
            candidate.backtest_trades = backtest_results.get("trades")
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate
    finally:
        db.close()


def approve_candidate(
    candidate_id: int,
    approved_by: str = "admin",
    notes: str = "",
    trial_days: int = 14,
    trial_capital: float = 10000.0,
) -> StrategyCandidate:
    """审核通过候选策略（人工审批）"""
    db = SessionLocal()
    try:
        c = db.query(StrategyCandidate).filter(StrategyCandidate.id == candidate_id).first()
        if not c:
            raise ValueError(f"候选策略 {candidate_id} 不存在")
        if c.status != "pending":
            raise ValueError(f"策略状态为 {c.status}，无法审批")

        c.status = "approved"
        c.approved_by = approved_by
        c.reviewer_notes = notes
        c.approved_at = datetime.now()
        c.trial_start = date.today()
        c.trial_end = date.today() + timedelta(days=trial_days)
        c.trial_capital = trial_capital
        db.commit()
        db.refresh(c)
        return c
    finally:
        db.close()


def reject_candidate(candidate_id: int, notes: str = "") -> StrategyCandidate:
    """拒绝候选策略"""
    db = SessionLocal()
    try:
        c = db.query(StrategyCandidate).filter(StrategyCandidate.id == candidate_id).first()
        if not c:
            raise ValueError(f"候选策略 {candidate_id} 不存在")
        c.status = "rejected"
        c.reviewer_notes = notes
        db.commit()
        db.refresh(c)
        return c
    finally:
        db.close()


def list_candidates(status: str = None, limit: int = 20) -> list[dict]:
    """列出候选策略"""
    db = SessionLocal()
    try:
        q = db.query(StrategyCandidate)
        if status:
            q = q.filter(StrategyCandidate.status == status)
        candidates = q.order_by(StrategyCandidate.created_at.desc()).limit(limit).all()
        return [
            {
                "id": c.id,
                "name": c.name,
                "type": c.strategy_type,
                "status": c.status,
                "description": c.description,
                "source": c.source,
                "backtest": {
                    "return": c.backtest_return,
                    "sharpe": c.backtest_sharpe,
                    "max_dd": c.backtest_max_dd,
                    "win_rate": c.backtest_win_rate,
                    "trades": c.backtest_trades,
                },
                "stress_test_pass": c.stress_test_pass,
                "overfit_score": c.overfit_score,
                "robustness_score": c.robustness_score,
                "approved_by": c.approved_by,
                "trial_start": c.trial_start.isoformat() if c.trial_start else None,
                "trial_end": c.trial_end.isoformat() if c.trial_end else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in candidates
        ]
    finally:
        db.close()


# ==================== 行为指纹 ====================

def update_behavior_fingerprints():
    """更新策略行为指纹（基于历史交易数据）"""
    db = SessionLocal()
    try:
        trades = db.query(TradeRecord).order_by(TradeRecord.trade_date.desc()).limit(200).all()
        if len(trades) < 10:
            return

        # 交易金额分布
        amounts = [t.amount for t in trades if t.amount]
        if amounts:
            _upsert_fingerprint(db, "system", "trade_amount_mean", sum(amounts) / len(amounts))
            _upsert_fingerprint(db, "system", "trade_amount_std", _std(amounts))

        # 交易频率（每日平均）
        dates = set(t.trade_date.date() for t in trades if t.trade_date)
        if dates:
            span = (max(dates) - min(dates)).days or 1
            freq = len(trades) / span
            _upsert_fingerprint(db, "system", "daily_trade_freq", freq)

        # 板块分布
        from constants import FUND_SECTOR
        sector_counts = {}
        for t in trades:
            sector = FUND_SECTOR.get(t.fund_code, "其他")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        total = sum(sector_counts.values())
        for sector, count in sector_counts.items():
            _upsert_fingerprint(db, "system", f"sector_{sector}", count / total)

        # 持仓集中度
        from collections import Counter
        fund_counts = Counter(t.fund_code for t in trades)
        if fund_counts:
            max_pct = max(fund_counts.values()) / sum(fund_counts.values())
            _upsert_fingerprint(db, "system", "max_fund_concentration", max_pct)

        db.commit()
    finally:
        db.close()


def _upsert_fingerprint(db, strategy: str, metric: str, value: float):
    """更新或创建指纹"""
    fp = db.query(BehaviorFingerprint).filter(
        BehaviorFingerprint.strategy_name == strategy,
        BehaviorFingerprint.metric_name == metric,
    ).first()
    if fp:
        # 增量更新均值和标准差
        n = fp.sample_count
        fp.metric_mean = (fp.metric_mean * n + value) / (n + 1)
        fp.metric_std = max(fp.metric_std * 0.95, abs(value - fp.metric_mean))
        fp.sample_count = n + 1
    else:
        db.add(BehaviorFingerprint(
            strategy_name=strategy,
            metric_name=metric,
            metric_mean=value,
            metric_std=max(abs(value * 0.1), 0.001),  # 初始标准差
            sample_count=1,
        ))


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


# ==================== 异常检测 ====================

def detect_anomalies() -> list[dict]:
    """检测执行层行为异常"""
    db = SessionLocal()
    anomalies = []
    try:
        fingerprints = db.query(BehaviorFingerprint).all()
        fp_map = {(f.strategy_name, f.metric_name): f for f in fingerprints}

        # 检查最近交易
        recent = db.query(TradeRecord).order_by(
            TradeRecord.trade_date.desc()
        ).limit(20).all()

        if len(recent) < 5:
            return []

        # 检测1：交易金额异常
        fp_amount = fp_map.get(("system", "trade_amount_mean"))
        if fp_amount and fp_amount.sample_count >= 5:
            for t in recent[:5]:
                if t.amount and fp_amount.metric_std > 0:
                    z = abs(t.amount - fp_amount.metric_mean) / fp_amount.metric_std
                    if z > 3:
                        anomalies.append({
                            "type": "size_spike",
                            "metric": "trade_amount",
                            "expected": fp_amount.metric_mean,
                            "actual": t.amount,
                            "z_score": round(z, 2),
                            "severity": "critical" if z > 5 else "warning",
                            "detail": f"{t.fund_code} 交易金额 {t.amount:.0f} 偏离均值 {z:.1f}σ",
                        })

        # 检测2：交易频率异常
        fp_freq = fp_map.get(("system", "daily_trade_freq"))
        if fp_freq and fp_freq.sample_count >= 5:
            today_count = sum(1 for t in recent if t.trade_date and t.trade_date.date() == date.today())
            if fp_freq.metric_std > 0:
                z = abs(today_count - fp_freq.metric_mean) / fp_freq.metric_std
                if z > 3:
                    anomalies.append({
                        "type": "freq_spike",
                        "metric": "daily_trade_freq",
                        "expected": fp_freq.metric_mean,
                        "actual": today_count,
                        "z_score": round(z, 2),
                        "severity": "warning",
                        "detail": f"今日交易 {today_count} 笔，偏离均值 {z:.1f}σ",
                    })

        # 检测3：新基金交易（之前从未交易过的基金）
        from constants import FUND_SECTOR
        known_funds = set(t.fund_code for t in db.query(TradeRecord).all())
        for t in recent[:5]:
            if t.fund_code not in known_funds:
                anomalies.append({
                    "type": "new_fund",
                    "metric": "fund_code",
                    "expected": "已知基金",
                    "actual": t.fund_code,
                    "z_score": 0,
                    "severity": "warning",
                    "detail": f"首次交易 {t.fund_code} ({t.fund_name})",
                })

        # 保存告警
        for a in anomalies:
            db.add(AnomalyAlert(
                strategy_name="system",
                anomaly_type=a["type"],
                metric_name=a["metric"],
                expected_value=a["expected"],
                actual_value=a["actual"],
                z_score=a["z_score"],
                severity=a["severity"],
                action_taken="logged",
            ))
        if anomalies:
            db.commit()

        return anomalies
    finally:
        db.close()


def get_anomaly_alerts(resolved: int = 0, limit: int = 20) -> list[dict]:
    """获取异常告警"""
    db = SessionLocal()
    try:
        alerts = db.query(AnomalyAlert).filter(
            AnomalyAlert.resolved == resolved
        ).order_by(AnomalyAlert.created_at.desc()).limit(limit).all()
        return [
            {
                "id": a.id,
                "date": a.alert_date.isoformat() if a.alert_date else None,
                "type": a.anomaly_type,
                "metric": a.metric_name,
                "expected": a.expected_value,
                "actual": a.actual_value,
                "z_score": a.z_score,
                "severity": a.severity,
                "action": a.action_taken,
                "resolved": a.resolved,
            }
            for a in alerts
        ]
    finally:
        db.close()


# ==================== 红队对抗测试 ====================

# 历史极端行情场景（用于压力测试）
STRESS_SCENARIOS = {
    "2015_crash": {
        "name": "2015年股灾",
        "description": "A股暴跌，千股跌停，流动性枯竭",
        "shock_days": 15,
        "max_drop": -0.45,
        "volatility_mult": 3.0,
        "recovery_days": 60,
    },
    "2018_bear": {
        "name": "2018年熊市",
        "description": "中美贸易战，持续阴跌",
        "shock_days": 120,
        "max_drop": -0.30,
        "volatility_mult": 1.5,
        "recovery_days": 90,
    },
    "2020_covid": {
        "name": "2020年疫情冲击",
        "description": "全球恐慌性抛售，V型反转",
        "shock_days": 20,
        "max_drop": -0.15,
        "volatility_mult": 2.5,
        "recovery_days": 30,
    },
    "2022_slow_bleed": {
        "name": "2022年慢熊",
        "description": "反复磨底，持续6个月低迷",
        "shock_days": 180,
        "max_drop": -0.25,
        "volatility_mult": 1.2,
        "recovery_days": 120,
    },
    "flash_crash": {
        "name": "闪崩场景",
        "description": "单日暴跌8%后次日反弹5%",
        "shock_days": 2,
        "max_drop": -0.08,
        "volatility_mult": 5.0,
        "recovery_days": 3,
    },
}


def red_team_stress_test(candidate_id: int) -> dict:
    """红队压力测试：用历史极端场景测试策略"""
    db = SessionLocal()
    try:
        c = db.query(StrategyCandidate).filter(StrategyCandidate.id == candidate_id).first()
        if not c:
            return {"error": "候选策略不存在"}

        results = {}
        all_passed = True

        for scenario_id, scenario in STRESS_SCENARIOS.items():
            # 模拟策略在极端行情下的表现
            sim = _simulate_scenario(c.parameters, scenario)
            results[scenario_id] = {
                "name": scenario["name"],
                "max_loss": sim["max_loss"],
                "recovery_days": sim["recovery_days"],
                "passed": sim["max_loss"] > -0.20,  # 最大亏损不超过20%
            }
            if not results[scenario_id]["passed"]:
                all_passed = False

        # 更新候选策略
        c.stress_test_pass = 1 if all_passed else 0
        db.commit()

        return {
            "candidate_id": candidate_id,
            "all_passed": all_passed,
            "scenarios": results,
        }
    finally:
        db.close()


def _simulate_scenario(params_json: str, scenario: dict) -> dict:
    """模拟策略在特定场景下的表现"""
    import json
    try:
        params = json.loads(params_json)
    except Exception:
        params = {}

    # 简化模拟：基于参数估算极端行情下的损失
    max_loss = scenario["max_drop"]
    vol_mult = scenario["volatility_mult"]

    # 趋势策略在暴跌中损失更大
    strategy_type = params.get("type", "trend")
    if strategy_type == "trend":
        max_loss *= 1.2  # 趋势跟踪在反转时损失更大
    elif strategy_type == "oscillation":
        max_loss *= 0.8  # 震荡策略损失较小

    # 止损越紧，损失越小但可能频繁触发
    stop_pct = params.get("stop_loss_pct", 0.07)
    if stop_pct < 0.05:
        max_loss *= 0.7  # 紧止损限制损失
    elif stop_pct > 0.10:
        max_loss *= 1.3  # 宽止损损失更大

    recovery_days = scenario["recovery_days"]
    if max_loss < -0.15:
        recovery_days = int(recovery_days * 1.5)  # 大亏后恢复更慢

    return {
        "max_loss": round(max_loss, 4),
        "recovery_days": recovery_days,
    }


def overfit_detection(candidate_id: int) -> dict:
    """过拟合检测：参数敏感度分析"""
    db = SessionLocal()
    try:
        c = db.query(StrategyCandidate).filter(StrategyCandidate.id == candidate_id).first()
        if not c:
            return {"error": "候选策略不存在"}

        import json
        try:
            params = json.loads(c.parameters)
        except Exception:
            params = {}

        # 检测过拟合信号
        signals = []
        score = 0.0

        # 1. 参数过多
        param_count = len(params)
        if param_count > 10:
            signals.append(f"参数过多({param_count}个)，过拟合风险高")
            score += 0.3

        # 2. 回测交易次数过少
        if c.backtest_trades and c.backtest_trades < 30:
            signals.append(f"交易次数过少({c.backtest_trades}次)，统计显著性不足")
            score += 0.3

        # 3. 胜率异常高
        if c.backtest_win_rate and c.backtest_win_rate > 0.75:
            signals.append(f"胜率异常高({c.backtest_win_rate*100:.0f}%)，可能存在前视偏差")
            score += 0.2

        # 4. 夏普比率异常高
        if c.backtest_sharpe and c.backtest_sharpe > 3.0:
            signals.append(f"夏普比率异常高({c.backtest_sharpe:.1f})，可能过拟合")
            score += 0.2

        # 5. 最大回撤过小
        if c.backtest_max_dd and abs(c.backtest_max_dd) < 0.03:
            signals.append(f"最大回撤过小({c.backtest_max_dd*100:.1f}%)，可能数据泄露")
            score += 0.2

        overfit_score = min(1.0, score)
        c.overfit_score = round(overfit_score, 2)
        c.robustness_score = round(1.0 - overfit_score, 2)
        db.commit()

        return {
            "candidate_id": candidate_id,
            "overfit_score": round(overfit_score, 2),
            "robustness_score": round(1.0 - overfit_score, 2),
            "signals": signals,
            "verdict": "高风险" if overfit_score > 0.6 else "中等" if overfit_score > 0.3 else "低风险",
        }
    finally:
        db.close()


# ==================== 执行层熔断 ====================

def check_execution_circuit_breaker() -> dict:
    """执行层行为熔断：检测到严重异常时自动停止交易"""
    db = SessionLocal()
    try:
        # 检查未处理的严重告警
        critical_alerts = db.query(AnomalyAlert).filter(
            AnomalyAlert.resolved == 0,
            AnomalyAlert.severity == "critical",
        ).count()

        # 检查最近1小时内的告警数量
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_alerts = db.query(AnomalyAlert).filter(
            AnomalyAlert.resolved == 0,
            AnomalyAlert.created_at >= one_hour_ago,
        ).count()

        # 熔断条件
        halted = False
        reason = ""

        if critical_alerts >= 1:
            halted = True
            reason = f"存在{critical_alerts}个严重异常未处理"
        elif recent_alerts >= 5:
            halted = True
            reason = f"最近1小时内{recent_alerts}个告警，异常频发"

        return {
            "halted": halted,
            "reason": reason,
            "critical_alerts": critical_alerts,
            "recent_alerts": recent_alerts,
        }
    finally:
        db.close()


def run_full_evaluation(candidate_id: int) -> dict:
    """完整评估流程：过拟合检测 + 红队压力测试"""
    overfit = overfit_detection(candidate_id)
    stress = red_team_stress_test(candidate_id)

    # 综合评分
    overfit_score = overfit.get("overfit_score", 1.0)
    stress_passed = stress.get("all_passed", False)

    recommendation = "reject"
    if stress_passed and overfit_score < 0.4:
        recommendation = "approve"
    elif stress_passed and overfit_score < 0.6:
        recommendation = "trial_with_caution"

    return {
        "candidate_id": candidate_id,
        "overfit": overfit,
        "stress_test": stress,
        "recommendation": recommendation,
        "summary": f"过拟合风险={overfit.get('verdict', '?')}, 压力测试={'通过' if stress_passed else '未通过'}, 建议={recommendation}",
    }
