"""仓位管理：ATR 风险平价 + 环境系数 + 回撤系数"""
from services.calculator import calculate_atr
from constants import (
    ATR_PERIOD_SHORT, RISK_PER_TRADE_PCT,
    ENV_STRONG_COEFF, ENV_WEAK_COEFF, ENV_NONE_COEFF,
    DRAWDOWN_COEFF_THRESHOLD, DRAWDOWN_COEFF_VALUE,
    SINGLE_FUND_MAX_PCT, MIN_TRADE_AMOUNT,
)


def calculate_position_size(
    account_value: float,
    prices: list[float],
    environment_coeff: float,
    current_drawdown: float = 0.0,
) -> dict:
    """ATR 风险平价仓位计算。

    公式：base = (账户总值 × 1%) / ATR(20)
    final = base × 环境系数 × 回撤系数

    Args:
        account_value: 账户总市值（含持仓）
        prices: 收盘价序列
        environment_coeff: 环境矩阵给出的仓位系数 (1.0 / 0.85 / 0.7 / 0.5 / 0.0)
        current_drawdown: 当前账户总回撤比例 (0.05 = 5%)

    Returns:
        {"shares": float, "amount": float, "atr": float, "risk_budget": float,
         "drawdown_coeff": float, "final_coeff": float, "rationale": str}
    """
    atr = calculate_atr(prices, ATR_PERIOD_SHORT)
    if atr <= 0:
        return {"shares": 0, "amount": 0, "atr": 0, "risk_budget": 0,
                "drawdown_coeff": 0, "final_coeff": 0, "rationale": "ATR为零，无法计算仓位"}

    # 风险预算 = 账户 × 1%
    risk_budget = account_value * RISK_PER_TRADE_PCT

    # 基础仓位金额 = 风险预算 / (ATR / 价格) → 转换为金额
    close = prices[-1]
    atr_pct = atr / close
    base_amount = risk_budget / atr_pct if atr_pct > 0 else 0

    # 回撤系数
    if current_drawdown >= DRAWDOWN_COEFF_THRESHOLD:
        drawdown_coeff = DRAWDOWN_COEFF_VALUE
    else:
        drawdown_coeff = 1.0

    # 最终系数
    final_coeff = environment_coeff * drawdown_coeff
    final_amount = base_amount * final_coeff

    # 约束：单基金不超过总资产 20%
    max_amount = account_value * SINGLE_FUND_MAX_PCT
    if final_amount > max_amount:
        final_amount = max_amount

    # 约束：最低交易金额
    if final_amount < MIN_TRADE_AMOUNT:
        return {"shares": 0, "amount": 0, "atr": round(atr, 4),
                "risk_budget": round(risk_budget, 2), "drawdown_coeff": drawdown_coeff,
                "final_coeff": round(final_coeff, 4),
                "rationale": f"计算金额{final_amount:.0f}低于最低{MIN_TRADE_AMOUNT}，跳过"}

    shares = final_amount / close
    rationale = (
        f"ATR={atr:.4f} 风险预算={risk_budget:.0f} "
        f"环境系数={environment_coeff} 回撤系数={drawdown_coeff} "
        f"最终系数={final_coeff:.2f} 金额={final_amount:.0f}"
    )

    return {
        "shares": round(shares, 2),
        "amount": round(final_amount, 2),
        "atr": round(atr, 4),
        "risk_budget": round(risk_budget, 2),
        "drawdown_coeff": drawdown_coeff,
        "final_coeff": round(final_coeff, 4),
        "rationale": rationale,
    }


def get_max_buy_amount(account_value: float, cash_balance: float) -> float:
    """可用买入金额上限：min(现金储备余量, 单基金上限)"""
    from constants import MIN_CASH_RESERVE
    available = cash_balance - MIN_CASH_RESERVE
    max_single = account_value * SINGLE_FUND_MAX_PCT
    return max(0, min(available, max_single))
