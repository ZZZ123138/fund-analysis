"""环境感知：波动率状态 + 趋势强度 → 环境矩阵 → 策略选择 + 双周期状态矩阵"""
from dataclasses import dataclass
from enum import Enum
from services.calculator import calculate_atr, calculate_adx, calculate_rsi, calculate_ema
from constants import (
    ATR_PERIOD_SHORT, ATR_PERIOD_LONG, ADX_PERIOD,
    ADX_STRONG_THRESHOLD, ADX_WEAK_THRESHOLD,
    VOL_EXPANSION_RATIO, VOL_CONTRACTION_RATIO,
    ENV_STRONG_COEFF, ENV_WEAK_COEFF, ENV_NONE_COEFF,
    LONG_CYCLE_EMA, SHORT_CYCLE_EMA, LONG_TREND_BIAS_ADX,
    PULLBACK_RSI_LOW, PULLBACK_RSI_HIGH,
)


class VolState(Enum):
    EXPANSION = "expansion"
    STABLE = "stable"
    CONTRACTION = "contraction"


class TrendState(Enum):
    STRONG = "strong"
    WEAK = "weak"
    NONE = "none"


class Environment(Enum):
    STRONG_TREND_EXPANSION = "strong_trend_expansion"
    STRONG_TREND_CONTRACTION = "strong_trend_contraction"
    WEAK_TREND = "weak_trend"
    NO_TREND_CONTRACTION = "none_contraction"
    NO_TREND_EXPANSION = "none_expansion"


@dataclass
class EnvironmentResult:
    vol_state: VolState
    trend_state: TrendState
    environment: Environment
    atr_20: float
    atr_60: float
    atr_ratio: float
    adx: float
    plus_di: float
    minus_di: float
    strategy: str          # "trend" | "oscillation" | "breakout" | "pause"
    position_coeff: float  # 1.0, 0.85, 0.7, 0.5, 0.3, 0.0


def sense_environment(prices: list[float]) -> EnvironmentResult:
    """给定基准（如 000961）价格序列，计算完整环境状态。
    需要至少 80 个数据点。
    """
    atr_20 = calculate_atr(prices, ATR_PERIOD_SHORT)
    atr_60 = calculate_atr(prices, ATR_PERIOD_LONG)
    atr_ratio = atr_20 / atr_60 if atr_60 > 0 else 1.0

    adx_data = calculate_adx(prices, ADX_PERIOD)
    adx = adx_data["adx"]
    plus_di = adx_data["plus_di"]
    minus_di = adx_data["minus_di"]

    vol = classify_vol_state(atr_ratio)
    trend = classify_trend_state(adx)
    env, strategy, coeff = select_strategy(trend, vol)

    return EnvironmentResult(
        vol_state=vol,
        trend_state=trend,
        environment=env,
        atr_20=round(atr_20, 4),
        atr_60=round(atr_60, 4),
        atr_ratio=round(atr_ratio, 4),
        adx=adx,
        plus_di=plus_di,
        minus_di=minus_di,
        strategy=strategy,
        position_coeff=coeff,
    )


def classify_vol_state(atr_ratio: float) -> VolState:
    """ATR(20)/ATR(60) 比值 → 波动率状态"""
    if atr_ratio >= VOL_EXPANSION_RATIO:
        return VolState.EXPANSION
    elif atr_ratio <= VOL_CONTRACTION_RATIO:
        return VolState.CONTRACTION
    return VolState.STABLE


def classify_trend_state(adx: float) -> TrendState:
    """ADX 值 → 趋势强度"""
    if adx >= ADX_STRONG_THRESHOLD:
        return TrendState.STRONG
    elif adx >= ADX_WEAK_THRESHOLD:
        return TrendState.WEAK
    return TrendState.NONE


def select_strategy(trend: TrendState, vol: VolState) -> tuple[Environment, str, float]:
    """环境矩阵 → (环境类型, 策略名, 仓位系数)

    矩阵：
    强趋势 + 扩张 → 趋势, 1.0
    强趋势 + 稳定 → 趋势, 0.85
    强趋势 + 收缩 → 趋势, 0.7（收紧止损）
    弱趋势 + 扩张 → 趋势, 0.7
    弱趋势 + 稳定 → 趋势, 0.7
    弱趋势 + 收缩 → 震荡, 0.5
    无趋势 + 收缩 → 震荡, 0.5
    无趋势 + 稳定 → 震荡, 0.5
    无趋势 + 扩张 → 暂停, 0.0（关键安全机制）
    """
    if trend == TrendState.STRONG:
        if vol == VolState.EXPANSION:
            return Environment.STRONG_TREND_EXPANSION, "trend", ENV_STRONG_COEFF
        elif vol == VolState.STABLE:
            return Environment.STRONG_TREND_EXPANSION, "trend", 0.85
        else:  # contraction
            return Environment.STRONG_TREND_CONTRACTION, "trend", ENV_WEAK_COEFF

    elif trend == TrendState.WEAK:
        if vol == VolState.CONTRACTION:
            return Environment.WEAK_TREND, "oscillation", 0.5
        else:  # expansion or stable
            return Environment.WEAK_TREND, "trend", ENV_WEAK_COEFF

    else:  # NONE
        if vol == VolState.EXPANSION:
            return Environment.NO_TREND_EXPANSION, "pause", 0.0
        else:  # stable or contraction
            return Environment.NO_TREND_CONTRACTION, "oscillation", 0.5


# ==================== 双周期状态矩阵 ====================

class LongCycleState(Enum):
    """长周期方向（模拟周线，用 60 日 EMA + ADX 判断）"""
    TREND_UP = "trend_up"       # 价格 > EMA(60)，ADX > 25
    TREND_DOWN = "trend_down"   # 价格 < EMA(60)，ADX > 25
    RANGE = "range"             # ADX < 25，无明确趋势


class ShortCycleState(Enum):
    """短周期位置（日线级别回调/超卖/突破）"""
    PULLBACK = "pullback"       # RSI 35-55，趋势中的健康回调
    OVERSOLD = "oversold"       # RSI < 35，超卖
    OVERBOUGHT = "overbought"   # RSI > 70，超买
    BREAKOUT = "breakout"       # 价格突破近期高点
    NEUTRAL = "neutral"         # 无明显信号


@dataclass
class DualCycleResult:
    long_cycle: LongCycleState
    short_cycle: ShortCycleState
    long_ema: float
    short_ema: float
    adx: float
    rsi: float
    allowed_strategy: str   # "trend" | "oscillation" | "none"
    cell_expectation: str   # "positive" | "neutral" | "negative"


def analyze_dual_cycle(prices: list[float]) -> DualCycleResult:
    """双周期状态矩阵：长周期定方向 × 短周期等回调。

    只在正期望单元格内开仓：
    - (trend_up, pullback) → 趋势策略 ✓
    - (trend_up, oversold) → 震荡策略 ✓
    - (range, oversold)    → 震荡策略 ✓
    - 其他组合 → 不开仓
    """
    if len(prices) < LONG_CYCLE_EMA + 5:
        return DualCycleResult(
            long_cycle=LongCycleState.RANGE, short_cycle=ShortCycleState.NEUTRAL,
            long_ema=0, short_ema=0, adx=0, rsi=50,
            allowed_strategy="none", cell_expectation="negative",
        )

    close = prices[-1]

    # 长周期：EMA(60) 方向 + ADX 趋势确认
    ema_long = calculate_ema(prices, LONG_CYCLE_EMA)
    ema_short = calculate_ema(prices, SHORT_CYCLE_EMA)
    adx_data = calculate_adx(prices, ADX_PERIOD)
    adx = adx_data["adx"]
    rsi = calculate_rsi(prices)

    long_val = ema_long[-1]
    short_val = ema_short[-1]

    if adx >= LONG_TREND_BIAS_ADX:
        if close > long_val:
            long_cycle = LongCycleState.TREND_UP
        else:
            long_cycle = LongCycleState.TREND_DOWN
    else:
        long_cycle = LongCycleState.RANGE

    # 短周期：RSI 位置 + 价格行为
    if rsi < PULLBACK_RSI_LOW:
        short_cycle = ShortCycleState.OVERSOLD
    elif rsi > 70:
        short_cycle = ShortCycleState.OVERBOUGHT
    elif PULLBACK_RSI_LOW <= rsi <= PULLBACK_RSI_HIGH and close > long_val:
        # 价格在长周期均线上方 + RSI 回调区间 = 健康回调
        short_cycle = ShortCycleState.PULLBACK
    else:
        # 检查是否突破（价格 > 短期 EMA 且 EMA 上穿）
        if close > short_val and ema_short[-1] > ema_short[-2]:
            short_cycle = ShortCycleState.BREAKOUT
        else:
            short_cycle = ShortCycleState.NEUTRAL

    # 查矩阵：正期望单元格
    cell_key = (long_cycle.value, short_cycle.value)
    positive_cells = {
        ("trend_up", "pullback"): "trend",
        ("trend_up", "oversold"): "oscillation",
        ("trend_up", "neutral"): "trend",
        ("range", "oversold"): "oscillation",
        ("range", "pullback"): "oscillation",
    }

    if cell_key in positive_cells:
        allowed = positive_cells[cell_key]
        expectation = "positive"
    elif long_cycle == LongCycleState.TREND_UP and short_cycle == ShortCycleState.BREAKOUT:
        allowed = "trend"
        expectation = "neutral"  # 突破需要额外确认
    elif long_cycle == LongCycleState.TREND_DOWN:
        allowed = "none"
        expectation = "negative"  # 下跌趋势不开仓
    else:
        allowed = "none"
        expectation = "neutral"

    return DualCycleResult(
        long_cycle=long_cycle,
        short_cycle=short_cycle,
        long_ema=round(long_val, 4),
        short_ema=round(short_val, 4),
        adx=adx,
        rsi=rsi,
        allowed_strategy=allowed,
        cell_expectation=expectation,
    )
