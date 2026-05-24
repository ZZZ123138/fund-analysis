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


def calculate_rsi(prices: list[float], period: int = 14) -> float:
    """计算 RSI 指标（Wilder 平滑法）。"""
    if len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder 平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def calculate_percentile(prices: list[float], lookback: int = 252) -> float:
    """计算当前价格在过去 N 个交易日中的历史百分位。"""
    if len(prices) < 2:
        return 50.0

    window = prices[-lookback:] if len(prices) >= lookback else prices
    current = prices[-1]
    count_below = sum(1 for p in window if p < current)
    return round(count_below / len(window) * 100, 2)


def calculate_ma_deviation(prices: list[float], period: int = 20) -> float:
    """计算均线乖离率（%）。"""
    if len(prices) < period:
        return 0.0

    ma = sum(prices[-period:]) / period
    if ma == 0:
        return 0.0
    return round((prices[-1] - ma) / ma * 100, 2)


def calculate_cycle_strength(prices: list[float]) -> dict:
    """综合判断强弱周期状态。"""
    rsi = calculate_rsi(prices)
    percentile = calculate_percentile(prices)
    ma_dev = calculate_ma_deviation(prices)

    signals = []
    score = 0

    # RSI 信号
    if rsi > 70:
        signals.append("RSI 超买区间，短期可能回调")
        score -= 1
    elif rsi < 30:
        signals.append("RSI 超卖区间，短期可能反弹")
        score += 1
    else:
        signals.append(f"RSI 处于中性区间 ({rsi})")

    # 百分位信号
    if percentile > 80:
        signals.append("价格处于历史高位区间")
        score -= 1
    elif percentile < 20:
        signals.append("价格处于历史低位区间")
        score += 1
    else:
        signals.append(f"价格处于历史中位区间 ({percentile}%)")

    # 乖离率信号
    if ma_dev > 5:
        signals.append("均线乖离率偏高，存在回归风险")
        score -= 1
    elif ma_dev < -5:
        signals.append("均线乖离率偏低，可能存在反弹机会")
        score += 1
    else:
        signals.append(f"均线乖离率正常 ({ma_dev}%)")

    # 综合判断
    if score >= 2:
        status = "weak"  # 低位 = 弱周期（买入机会）
    elif score <= -2:
        status = "strong"  # 高位 = 强周期（谨慎追高）
    else:
        status = "neutral"

    return {
        "rsi": rsi,
        "percentile": percentile,
        "ma_deviation": ma_dev,
        "status": status,
        "signals": signals,
    }


def calculate_annual_return(prices: list[float], lookback: int = 252) -> float:
    """计算过去一年涨幅。"""
    if len(prices) < lookback:
        if len(prices) < 2:
            return 0.0
        return round((prices[-1] - prices[0]) / prices[0] * 100, 2)

    year_ago_price = prices[-lookback]
    if year_ago_price == 0:
        return 0.0
    return round((prices[-1] - year_ago_price) / year_ago_price * 100, 2)


def get_merrill_clock_stage(annualized_return: float, volatility: float) -> dict:
    """基于收益率和波动率推断美林时钟阶段。

    高收益 + 低波动 → 复苏期
    高收益 + 高波动 → 过热期
    低收益 + 高波动 → 滞胀期
    低收益 + 低波动 → 衰退期
    """
    # 阈值设定
    return_threshold = 0.08  # 8% 年化收益为分界
    vol_threshold = 0.20  # 20% 年化波动率为分界

    high_return = annualized_return > return_threshold
    high_vol = volatility > vol_threshold

    if high_return and not high_vol:
        stage = "recovery"
        stage_cn = "复苏期"
        description = "经济回暖，企业盈利改善，市场温和上涨，波动较低。"
        advice = "适合配置股票型基金，把握经济复苏带来的上涨机会。"
    elif high_return and high_vol:
        stage = "overheat"
        stage_cn = "过热期"
        description = "经济过热，通胀上升，市场涨幅较大但波动加剧。"
        advice = "注意控制仓位，可适当配置抗通胀资产，警惕市场回调风险。"
    elif not high_return and high_vol:
        stage = "stagflation"
        stage_cn = "滞胀期"
        description = "经济增长放缓，通胀高企，市场表现不佳且波动较大。"
        advice = "建议降低权益类配置，增加债券或货币基金等防御性资产。"
    else:
        stage = "recession"
        stage_cn = "衰退期"
        description = "经济下行，市场低迷但波动降低，往往是布局良机。"
        advice = "可逐步布局优质基金，逢低建仓，为下一轮复苏做准备。"

    return {
        "stage": stage,
        "stage_cn": stage_cn,
        "description": description,
        "advice": advice,
    }


def infer_fund_type(fund_name: str) -> dict:
    """根据基金名称推断基金类型和特征。"""
    name = fund_name.lower()

    if any(kw in name for kw in ["指数", "etf", "lof", "沪深300", "中证500", "创业板", "科创"]):
        fund_type = "指数型"
        risk_level = "中高"
        description = "跟踪特定指数，费率低，走势与标的指数高度相关。"
        characteristics = ["被动管理", "费率低", "透明度高", "分散风险"]
    elif any(kw in name for kw in ["债", "信用", "利率", "可转债"]):
        fund_type = "债券型"
        risk_level = "低"
        description = "主要投资债券市场，收益相对稳定，波动较小。"
        characteristics = ["收益稳定", "波动小", "适合稳健投资", "受利率影响"]
    elif any(kw in name for kw in ["货币", "现金"]):
        fund_type = "货币型"
        risk_level = "极低"
        description = "投资短期货币工具，流动性好，风险极低。"
        characteristics = ["流动性好", "风险极低", "收益较低", "替代存款"]
    elif any(kw in name for kw in ["混合", "平衡", "灵活"]):
        fund_type = "混合型"
        risk_level = "中"
        description = "灵活配置股票和债券，攻守兼备。"
        characteristics = ["灵活配置", "攻守兼备", "基金经理主动管理", "风格多样"]
    elif any(kw in name for kw in ["qdii", "全球", "海外", "美国", "纳斯达克"]):
        fund_type = "QDII型"
        risk_level = "中高"
        description = "投资海外市场，分散地域风险，受汇率影响。"
        characteristics = ["海外投资", "地域分散", "汇率风险", "时差交易"]
    else:
        fund_type = "股票型"
        risk_level = "高"
        description = "主要投资股票市场，收益潜力大，波动也较大。"
        characteristics = ["收益潜力大", "波动较大", "长期持有", "选股能力关键"]

    return {
        "fund_type": fund_type,
        "risk_level": risk_level,
        "description": description,
        "characteristics": characteristics,
    }
