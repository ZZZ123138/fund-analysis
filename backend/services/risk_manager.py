"""风控管理：熔断机制 + 策略生命周期 + R分布监控 + 凸性约束"""
import math
from datetime import date
from sqlalchemy.orm import Session
from models import RiskState
from constants import (
    CIRCUIT_BREAKER_DAILY_LOSS,
    CIRCUIT_BREAKER_WEEKLY_DD,
    CIRCUIT_BREAKER_TOTAL_DD,
    STRATEGY_MAX_CONSECUTIVE_LOSSES,
    STRATEGY_MONTHLY_EV_THRESHOLD,
    STRATEGY_ARCHIVE_MONTHS,
    R_DIST_MIN_TRADES, R_EXPECTATION_THRESHOLD, R_SKEWNESS_THRESHOLD, R_LEFT_TAIL_PCT,
)


def update_risk_state(
    db: Session,
    today: date,
    daily_pnl: float,
    daily_pnl_pct: float,
    total_assets: float,
    initial_balance: float,
    strategy_name: str = "",
) -> RiskState:
    """每日更新风控状态，返回当前 RiskState。"""
    state = db.query(RiskState).filter(RiskState.state_date == today).first()
    if not state:
        state = RiskState(state_date=today)
        db.add(state)

    # 获取前一天状态
    prev = (
        db.query(RiskState)
        .filter(RiskState.state_date < today)
        .order_by(RiskState.state_date.desc())
        .first()
    )

    # 更新峰值
    peak = prev.peak_assets if prev and prev.peak_assets else initial_balance
    if total_assets > peak:
        peak = total_assets
    state.peak_assets = peak

    weekly_peak = prev.weekly_peak_assets if prev and prev.weekly_peak_assets else initial_balance
    if total_assets > weekly_peak:
        weekly_peak = total_assets
    state.weekly_peak_assets = weekly_peak

    # 日度盈亏
    state.daily_pnl = round(daily_pnl, 2)
    state.daily_pnl_pct = round(daily_pnl_pct, 4)

    # 总回撤
    total_dd = (peak - total_assets) / peak if peak > 0 else 0
    state.total_drawdown = round(total_dd, 4)

    # 周回撤
    weekly_dd = (weekly_peak - total_assets) / weekly_peak if weekly_peak > 0 else 0
    state.weekly_drawdown = round(weekly_dd, 4)

    # 连亏计数
    if daily_pnl < 0:
        state.consecutive_losses = (prev.consecutive_losses + 1) if prev else 1
    else:
        state.consecutive_losses = 0

    # 策略名称
    state.strategy_name = strategy_name

    # 熔断判断
    state.circuit_breaker_daily = 1 if abs(daily_pnl_pct) >= CIRCUIT_BREAKER_DAILY_LOSS else 0
    state.circuit_breaker_weekly = 1 if weekly_dd >= CIRCUIT_BREAKER_WEEKLY_DD else 0
    state.circuit_breaker_total = 1 if total_dd >= CIRCUIT_BREAKER_TOTAL_DD else 0

    # 策略生命周期
    if state.consecutive_losses >= STRATEGY_MAX_CONSECUTIVE_LOSSES:
        state.strategy_status = "paused"
    elif prev and prev.strategy_status == "paused" and state.consecutive_losses < 3:
        state.strategy_status = "active"
    else:
        state.strategy_status = prev.strategy_status if prev else "active"

    # 月度 EV（简化：用最近交易的盈亏均值）
    state.monthly_expected_value = round(daily_pnl_pct, 4)
    if prev and prev.monthly_expected_value is not None:
        state.monthly_expected_value = round(
            prev.monthly_expected_value * 0.9 + daily_pnl_pct * 0.1, 4
        )

    db.commit()
    db.refresh(state)
    return state


def check_circuit_breaker(state: RiskState) -> dict:
    """检查熔断状态，返回是否允许交易及原因。"""
    if state.circuit_breaker_daily:
        return {"allowed": False, "reason": "日亏损熔断", "level": "daily"}
    if state.circuit_breaker_total:
        return {"allowed": False, "reason": "总回撤熔断", "level": "total"}

    # 周熔断：仓位减半（不完全禁止）
    position_scale = 0.5 if state.circuit_breaker_weekly else 1.0

    # 策略暂停
    if state.strategy_status == "paused":
        return {"allowed": False, "reason": "策略暂停（连续亏损过多）", "level": "strategy"}

    return {"allowed": True, "reason": "", "level": "", "position_scale": position_scale}


def get_risk_summary(db: Session, today: date) -> dict:
    """获取当日风控摘要"""
    state = db.query(RiskState).filter(RiskState.state_date == today).first()
    if not state:
        return {"has_state": False}

    cb = check_circuit_breaker(state)
    return {
        "has_state": True,
        "daily_pnl": state.daily_pnl,
        "daily_pnl_pct": state.daily_pnl_pct,
        "weekly_drawdown": state.weekly_drawdown,
        "total_drawdown": state.total_drawdown,
        "consecutive_losses": state.consecutive_losses,
        "strategy_status": state.strategy_status,
        "circuit_breaker": cb,
    }


# ==================== R 乘数分布监控 ====================

def analyze_r_distribution(r_values: list[float]) -> dict:
    """分析 R 乘数分布，判断策略健康度。

    Args:
        r_values: 历史交易的 R 乘数列表（正=盈利，负=亏损）

    Returns:
        期望值、胜率、平均盈亏比、偏度、左尾占比、健康评级
    """
    if len(r_values) < R_DIST_MIN_TRADES:
        return {
            "count": len(r_values), "expectation": 0, "win_rate": 0,
            "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
            "skewness": 0, "left_tail_pct": 0, "health": "insufficient",
            "verdict": "交易数据不足，暂不评估",
        }

    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    n = len(r_values)

    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    loss_rate = 1 - win_rate

    # 期望值 = 胜率 × 平均盈利R - 败率 × |平均亏损R|
    expectation = win_rate * avg_win - loss_rate * abs(avg_loss)

    # 盈亏比 = 平均盈利 / |平均亏损|
    profit_factor = avg_win / abs(avg_loss) if avg_loss != 0 else float('inf')

    # 偏度（收益分布不对称性）
    mean_r = sum(r_values) / n
    variance = sum((r - mean_r) ** 2 for r in r_values) / n
    std_r = math.sqrt(variance) if variance > 0 else 1
    skewness = sum(((r - mean_r) / std_r) ** 3 for r in r_values) / n

    # 左尾占比：亏损交易中 R < -2 的比例
    severe_losses = [r for r in losses if r < -2]
    left_tail_pct = len(severe_losses) / len(losses) if losses else 0

    # 健康评级
    if expectation < R_EXPECTATION_THRESHOLD:
        health = "weak"
        verdict = f"期望值 {expectation:.2f}R 偏低，策略盈利能力不足"
    elif skewness < R_SKEWNESS_THRESHOLD:
        health = "concave"
        verdict = f"偏度 {skewness:.2f} 为负（凹性），频繁小赚偶发大亏，反脆弱性差"
    elif left_tail_pct > R_LEFT_TAIL_PCT:
        health = "tail_risk"
        verdict = f"左尾风险 {left_tail_pct:.0%} 偏高，需收紧止损"
    elif expectation > 0.5 and skewness > 0:
        health = "excellent"
        verdict = f"期望值 {expectation:.2f}R，正偏度，策略健康"
    else:
        health = "normal"
        verdict = f"期望值 {expectation:.2f}R，策略运行正常"

    return {
        "count": n,
        "expectation": round(expectation, 3),
        "win_rate": round(win_rate, 3),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "profit_factor": round(profit_factor, 2),
        "skewness": round(skewness, 3),
        "left_tail_pct": round(left_tail_pct, 3),
        "health": health,
        "verdict": verdict,
    }


def check_convexity(r_values: list[float]) -> dict:
    """凸性约束检查：策略收益分布必须具有凸性。

    凸性 = 正偏度（右尾厚于左尾）
    凹性 = 负偏度（左尾厚于右尾）→ 该策略应降权或暂停

    Returns:
        is_convex: 是否具有凸性
        skewness: 偏度值
        action: "continue" | "reduce" | "pause"
        reason: 原因说明
    """
    if len(r_values) < R_DIST_MIN_TRADES:
        return {"is_convex": True, "skewness": 0, "action": "continue",
                "reason": "数据不足，默认通过"}

    n = len(r_values)
    mean_r = sum(r_values) / n
    variance = sum((r - mean_r) ** 2 for r in r_values) / n
    std_r = math.sqrt(variance) if variance > 0 else 1
    skewness = sum(((r - mean_r) / std_r) ** 3 for r in r_values) / n

    if skewness < R_SKEWNESS_THRESHOLD:
        return {
            "is_convex": False,
            "skewness": round(skewness, 3),
            "action": "pause",
            "reason": f"凹性检测：偏度 {skewness:.2f} < {R_SKEWNESS_THRESHOLD}，策略呈反脆弱特征，暂停使用",
        }
    elif skewness < 0:
        return {
            "is_convex": False,
            "skewness": round(skewness, 3),
            "action": "reduce",
            "reason": f"偏度 {skewness:.2f} 略负，建议降低仓位系数",
        }
    else:
        return {
            "is_convex": True,
            "skewness": round(skewness, 3),
            "action": "continue",
            "reason": f"凸性良好，偏度 {skewness:.2f}",
        }


def get_position_scale_from_r(r_values: list[float]) -> float:
    """根据 R 分布健康度返回仓位缩放系数。

    Returns:
        0.0 ~ 1.0 的仓位系数
    """
    convexity = check_convexity(r_values)
    if convexity["action"] == "pause":
        return 0.0
    if convexity["action"] == "reduce":
        return 0.5

    dist = analyze_r_distribution(r_values)
    if dist["health"] == "weak":
        return 0.5
    if dist["health"] == "tail_risk":
        return 0.7
    return 1.0
