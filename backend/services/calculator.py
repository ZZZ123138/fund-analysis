import math
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import asc
from models import FundNav, Fund


RISK_FREE_RATE = 0.025  # 无风险利率 2.5%


def calculate_metrics(fund_code: str, db: Session) -> dict:
    """计算基金的各项指标。"""
    navs = (
        db.query(FundNav)
        .filter(FundNav.fund_code == fund_code)
        .order_by(asc(FundNav.date))
        .all()
    )
    if len(navs) < 2:
        raise ValueError("净值数据不足，无法计算指标")

    fund = db.query(Fund).filter(Fund.code == fund_code).first()
    fund_name = fund.name if fund else ""

    dates = [n.date for n in navs]
    prices = [n.nav for n in navs]

    # 日收益率
    daily_returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]

    total_return = (prices[-1] - prices[0]) / prices[0]
    trading_days = len(dates) - 1
    years = trading_days / 252
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    max_dd = _max_drawdown(prices)

    # 年化波动率 = 日收益率标准差(样本) * sqrt(252)
    vol = _std_sample(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0
    sharpe = ((annualized_return - RISK_FREE_RATE) / vol) if vol > 0 else 0

    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "annualized_return": round(annualized_return, 4),
        "max_drawdown": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "volatility": round(vol, 4),
        "total_return": round(total_return, 4),
        "trading_days": trading_days,
        "start_date": dates[0],
        "end_date": dates[-1],
    }


def _max_drawdown(prices: list[float]) -> float:
    """计算最大回撤。"""
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        dd = (peak - p) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _std_sample(data: list[float]) -> float:
    """计算样本标准差。"""
    n = len(data)
    if n < 2:
        return 0.0
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / (n - 1)
    return math.sqrt(variance)
