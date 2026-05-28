"""策略模板：趋势 / 震荡 / 突破（含突破质量过滤+三天法则）"""
from dataclasses import dataclass
from typing import Optional
from services.calculator import (
    calculate_rsi, calculate_ema, calculate_atr,
    calculate_bollinger_bands, calculate_high_low_range,
)
from constants import (
    TREND_EMA_SHORT, TREND_EMA_LONG, TREND_ADX_MIN,
    TREND_RSI_PULLBACK_LOW, TREND_RSI_PULLBACK_HIGH,
    OSC_RANGE_PERIOD, OSC_RSI_OVERSOLD, OSC_STOP_ATR_MULTIPLE,
    BREAKOUT_RANGE_NARROW_DAYS, BREAKOUT_BW_PERIOD,
    BREAKOUT_BW_PERCENTILE, BREAKOUT_RSI_SURGE, BREAKOUT_EXIT_DAYS,
    HARD_STOP_ATR_MULTIPLE, TRAILING_STOP_ATR_MULTIPLE,
    TIME_STOP_BARS, ATR_PERIOD_SHORT,
    BREAKOUT_CONFIRM_BARS, BREAKOUT_MAX_PULLBACK_PCT, BREAKOUT_RSI_HOLD_MIN,
    THREE_DAY_EXIT_BARS,
)


@dataclass
class TradeSignal:
    """策略扫描输出：单只基金的交易信号"""
    fund_code: str
    fund_name: str
    action: str              # "buy" | "hold"
    strategy: str            # "trend" | "oscillation" | "breakout"
    strength: float          # 0-1 信号强度
    entry_price: float
    stop_loss_price: float
    initial_risk: float      # entry - stop（绝对值）
    reason: str
    r_target: float          # 预期 R 乘数目标


@dataclass
class ExitSignal:
    """退出扫描输出"""
    fund_code: str
    action: str              # "exit_full" | "exit_partial"
    exit_reason: str
    priority: int            # 1=最高
    sell_ratio: float
    reason: str
    r_multiple: float


class TrendStrategy:
    """趋势策略：EMA 排列 + ADX 确认 + RSI 回调入场"""

    def scan_entry(self, fund_code: str, fund_name: str, prices: list[float],
                   adx: float, plus_di: float, minus_di: float) -> Optional[TradeSignal]:
        """
        入场条件：
        1. EMA(5) > EMA(20)（周线代理）
        2. ADX > 25
        3. RSI 回调区间 40-60
        4. +DI > -DI（多头方向）
        """
        if len(prices) < max(TREND_EMA_LONG, 30):
            return None

        ema_short = calculate_ema(prices, TREND_EMA_SHORT)
        ema_long = calculate_ema(prices, TREND_EMA_LONG)
        rsi = calculate_rsi(prices)
        close = prices[-1]
        atr = calculate_atr(prices, ATR_PERIOD_SHORT)

        # 条件 1: EMA 排列
        if ema_short[-1] <= ema_long[-1]:
            return None
        # 条件 2: ADX 确认趋势
        if adx < TREND_ADX_MIN:
            return None
        # 条件 3: RSI 回调区间
        if not (TREND_RSI_PULLBACK_LOW <= rsi <= TREND_RSI_PULLBACK_HIGH):
            return None
        # 条件 4: 多头方向
        if plus_di <= minus_di:
            return None

        stop = close - HARD_STOP_ATR_MULTIPLE * atr
        initial_risk = close - stop
        strength = min(1.0, (adx - TREND_ADX_MIN) / 20 + 0.3)

        return TradeSignal(
            fund_code=fund_code, fund_name=fund_name,
            action="buy", strategy="trend", strength=strength,
            entry_price=close, stop_loss_price=round(stop, 4),
            initial_risk=round(initial_risk, 4),
            reason=f"趋势入场 EMA排列 ADX={adx:.0f} RSI={rsi:.0f}",
            r_target=2.0,
        )


class OscillationStrategy:
    """震荡策略：区间边界 + RSI 极值入场，均值回归止盈"""

    def scan_entry(self, fund_code: str, fund_name: str, prices: list[float],
                   adx: float = 0, plus_di: float = 0, minus_di: float = 0) -> Optional[TradeSignal]:
        """
        入场条件（仅做多）：
        1. 价格接近 20 日最低（< 区间 20% 分位）
        2. RSI < 30（超卖）
        """
        if len(prices) < OSC_RANGE_PERIOD + 5:
            return None

        rsi = calculate_rsi(prices)
        hl = calculate_high_low_range(prices, OSC_RANGE_PERIOD)
        close = prices[-1]
        atr = calculate_atr(prices, ATR_PERIOD_SHORT)

        # 价格在区间下沿
        range_size = hl["high"] - hl["low"]
        if range_size <= 0:
            return None
        position_in_range = (close - hl["low"]) / range_size

        if position_in_range > 0.20:
            return None
        if rsi >= OSC_RSI_OVERSOLD:
            return None

        stop = close - OSC_STOP_ATR_MULTIPLE * atr
        initial_risk = close - stop
        target = hl["midpoint"]
        strength = min(1.0, (OSC_RSI_OVERSOLD - rsi) / 20 + 0.3)

        return TradeSignal(
            fund_code=fund_code, fund_name=fund_name,
            action="buy", strategy="oscillation", strength=strength,
            entry_price=close, stop_loss_price=round(stop, 4),
            initial_risk=round(initial_risk, 4),
            reason=f"震荡入场 区间下沿 RSI={rsi:.0f} 目标={target:.4f}",
            r_target=round((target - close) / initial_risk, 1) if initial_risk > 0 else 1.0,
        )


class BreakoutStrategy:
    """突破策略：布林带收窄 + 突破上轨 + RSI 动量激增"""

    def scan_entry(self, fund_code: str, fund_name: str, prices: list[float],
                   adx: float = 0, plus_di: float = 0, minus_di: float = 0) -> Optional[TradeSignal]:
        """
        入场条件：
        1. 布林带宽度处于 20 日低位（< 20% 分位数）
        2. 收盘价突破上轨
        3. RSI 3天内激增 > 5 点（成交量代理）
        """
        if len(prices) < BREAKOUT_BW_PERIOD + 10:
            return None

        bb = calculate_bollinger_bands(prices)
        close = prices[-1]
        rsi = calculate_rsi(prices)
        rsi_prev = calculate_rsi(prices[:-3]) if len(prices) > 17 else 50
        atr = calculate_atr(prices, ATR_PERIOD_SHORT)

        # 条件 1: 布林带收窄
        # 计算历史带宽的百分位
        bw_history = []
        for i in range(BREAKOUT_BW_PERIOD, len(prices)):
            window = prices[max(0, i - 20):i + 1]
            if len(window) >= 20:
                mid = sum(window) / len(window)
                std_val = (sum((p - mid) ** 2 for p in window) / (len(window) - 1)) ** 0.5
                bw = (std_val * 4) / mid if mid > 0 else 0
                bw_history.append(bw)

        if len(bw_history) < 5:
            return None

        current_bw = bb["bandwidth"]
        bw_history_sorted = sorted(bw_history)
        bw_percentile_idx = int(len(bw_history_sorted) * BREAKOUT_BW_PERCENTILE / 100)
        bw_threshold = bw_history_sorted[min(bw_percentile_idx, len(bw_history_sorted) - 1)]

        if current_bw > bw_threshold:
            return None

        # 条件 2: 突破上轨
        if close <= bb["upper"]:
            return None

        # 条件 3: RSI 动量激增
        rsi_surge = rsi - rsi_prev
        if rsi_surge < BREAKOUT_RSI_SURGE:
            return None

        stop = bb["lower"]
        initial_risk = close - stop
        strength = min(1.0, rsi_surge / 15 + 0.4)

        return TradeSignal(
            fund_code=fund_code, fund_name=fund_name,
            action="buy", strategy="breakout", strength=strength,
            entry_price=close, stop_loss_price=round(stop, 4),
            initial_risk=round(initial_risk, 4),
            reason=f"突破入场 BB收窄 突破上轨 RSI激增{rsi_surge:.0f}",
            r_target=2.0,
        )

    def confirm_breakout(self, prices: list[float], breakout_price: float) -> dict:
        """突破质量过滤：突破后 N 根 K 线的确认检查。

        条件：
        1. 突破后 N 根 K 线内回调不超过突破实体的 50%
        2. RSI 在确认期不低于 BREAKOUT_RSI_HOLD_MIN

        Returns:
            confirmed: bool, 是否确认
            reason: str, 原因
        """
        if len(prices) < BREAKOUT_CONFIRM_BARS + 2:
            return {"confirmed": False, "reason": "数据不足"}

        # 取突破后的 K 线
        recent = prices[-BREAKOUT_CONFIRM_BARS:]
        max_pullback = 0
        for p in recent:
            pullback = (breakout_price - p) / breakout_price if breakout_price > 0 else 0
            max_pullback = max(max_pullback, pullback)

        rsi = calculate_rsi(prices)

        if max_pullback > BREAKOUT_MAX_PULLBACK_PCT:
            return {"confirmed": False,
                    "reason": f"回调 {max_pullback:.0%} 超过实体50%，突破质量差"}

        if rsi < BREAKOUT_RSI_HOLD_MIN:
            return {"confirmed": False,
                    "reason": f"RSI={rsi:.0f} 跌破{BREAKOUT_RSI_HOLD_MIN}，动量衰竭"}

        return {"confirmed": True, "reason": f"突破确认 回调{max_pullback:.0%} RSI={rsi:.0f}"}

    def check_three_day_exit(self, prices: list[float], entry_nav: float, bars_held: int) -> Optional[ExitSignal]:
        """三天法则：入场后 N 根 K 线无利润则离场。

        《金融怪杰》中的经典规则：如果突破后价格没有在合理时间内
        朝有利方向移动，说明突破失败，应立即退出。
        """
        if bars_held < THREE_DAY_EXIT_BARS:
            return None

        close = prices[-1]
        if close > entry_nav:
            return None  # 有利润，不触发

        pnl_pct = (close - entry_nav) / entry_nav if entry_nav > 0 else 0
        return ExitSignal(
            fund_code="", action="exit_full",
            exit_reason="three_day", priority=4, sell_ratio=1.0,
            reason=f"三天法则 {bars_held}天无利润 {pnl_pct*100:.1f}%",
            r_multiple=round(pnl_pct * 25, 2),  # 粗略 R 估算
        )


def evaluate_exit(
    fund_code: str,
    prices: list[float],
    entry_nav: float,
    peak_nav: float,
    bars_held: int,
    current_environment: str,
    entry_environment: str,
    strategy_name: str,
    initial_risk: float,
    partial_profit_taken: dict,
) -> Optional[ExitSignal]:
    """统一退出评估，按优先级排序。

    优先级 1: 状态破坏（环境变化）
    优先级 2: 硬止损（2 ATR）
    优先级 3: 移动止盈（趋势环境，1.5 ATR）
    优先级 4: 时间止损（震荡环境，5根K线无利润）
    优先级 5: 分批止盈
    """
    close = prices[-1]
    atr = calculate_atr(prices, ATR_PERIOD_SHORT)
    pnl_pct = (close - entry_nav) / entry_nav if entry_nav > 0 else 0
    r_mult = (close - entry_nav) / initial_risk if initial_risk > 0 else 0

    # 优先级 1: 状态破坏
    if _is_environment_break(entry_environment, current_environment, strategy_name):
        return ExitSignal(
            fund_code=fund_code, action="exit_full",
            exit_reason="state_break", priority=1, sell_ratio=1.0,
            reason=f"状态破坏 入场环境={entry_environment} 当前={current_environment}",
            r_multiple=round(r_mult, 2),
        )

    # 优先级 2: 硬止损
    stop_price = entry_nav - HARD_STOP_ATR_MULTIPLE * (initial_risk / HARD_STOP_ATR_MULTIPLE)
    if close <= stop_price:
        return ExitSignal(
            fund_code=fund_code, action="exit_full",
            exit_reason="hard_stop", priority=2, sell_ratio=1.0,
            reason=f"硬止损 亏损{pnl_pct * 100:.1f}%",
            r_multiple=round(r_mult, 2),
        )

    # 优先级 3: 移动止盈（趋势环境）
    if strategy_name == "trend" and peak_nav > entry_nav:
        trailing_stop = peak_nav - TRAILING_STOP_ATR_MULTIPLE * atr
        if close <= trailing_stop:
            return ExitSignal(
                fund_code=fund_code, action="exit_full",
                exit_reason="trailing", priority=3, sell_ratio=1.0,
                reason=f"移动止盈 从高点回落 R={r_mult:.1f}",
                r_multiple=round(r_mult, 2),
            )

    # 优先级 4: 时间止损（震荡环境）
    if strategy_name == "oscillation" and bars_held >= TIME_STOP_BARS and pnl_pct <= 0:
        return ExitSignal(
            fund_code=fund_code, action="exit_full",
            exit_reason="time", priority=4, sell_ratio=1.0,
            reason=f"时间止损 {bars_held}根K线无利润",
            r_multiple=round(r_mult, 2),
        )

    # 优先级 5: 分批止盈
    if r_mult >= 1.0 and not partial_profit_taken.get(1):
        return ExitSignal(
            fund_code=fund_code, action="exit_partial",
            exit_reason="partial_profit", priority=5,
            sell_ratio=0.30,
            reason=f"1R止盈 R={r_mult:.1f} 出30%",
            r_multiple=round(r_mult, 2),
        )
    if r_mult >= 2.0 and not partial_profit_taken.get(2):
        return ExitSignal(
            fund_code=fund_code, action="exit_partial",
            exit_reason="partial_profit", priority=5,
            sell_ratio=0.40,
            reason=f"2R止盈 R={r_mult:.1f} 出40%",
            r_multiple=round(r_mult, 2),
        )
    if r_mult >= 3.0 and not partial_profit_taken.get(3):
        return ExitSignal(
            fund_code=fund_code, action="exit_partial",
            exit_reason="partial_profit", priority=5,
            sell_ratio=0.30,
            reason=f"3R止盈 R={r_mult:.1f} 出剩余",
            r_multiple=round(r_mult, 2),
        )

    return None


def _is_environment_break(entry_env: str, current_env: str, strategy: str) -> bool:
    """判断环境是否发生根本性变化（状态破坏退出）。
    核心原则：入场时依赖的环境条件是否仍然存在。
    """
    if strategy == "trend":
        # 趋势策略入场 → 如果当前处于暂停或无趋势震荡，环境破坏
        if current_env in ("none_expansion", "none_contraction"):
            return True
    elif strategy == "oscillation":
        # 震荡策略入场 → 如果当前强趋势扩张（应追趋势不做震荡），环境破坏
        if current_env == "strong_trend_expansion":
            return True
    elif strategy == "breakout":
        # 突破策略入场 → 如果环境回到无趋势收缩，突破失败
        if current_env in ("none_contraction", "none_expansion"):
            return True
    return False
