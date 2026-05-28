"""退出管理：持仓退出状态跟踪 + 分批止盈记录"""
from dataclasses import dataclass, field
from typing import Optional
from services.strategy import evaluate_exit, ExitSignal


@dataclass
class PositionState:
    """单只基金的持仓退出状态"""
    fund_code: str
    entry_nav: float
    initial_risk: float
    strategy_name: str
    entry_environment: str
    peak_nav: float
    bars_held: int = 0
    partial_profit_taken: dict = field(default_factory=lambda: {1: False, 2: False, 3: False})


class ExitManager:
    """管理所有持仓的退出状态，统一调用 evaluate_exit。"""

    def __init__(self):
        self.positions: dict[str, PositionState] = {}

    def add_position(self, fund_code: str, entry_nav: float, initial_risk: float,
                     strategy_name: str, entry_environment: str):
        """买入时注册持仓状态"""
        self.positions[fund_code] = PositionState(
            fund_code=fund_code,
            entry_nav=entry_nav,
            initial_risk=initial_risk,
            strategy_name=strategy_name,
            entry_environment=entry_environment,
            peak_nav=entry_nav,
        )

    def remove_position(self, fund_code: str):
        """清仓时移除"""
        self.positions.pop(fund_code, None)

    def update_bar(self, fund_code: str, current_nav: float):
        """每日更新：递增持仓天数，刷新峰值"""
        pos = self.positions.get(fund_code)
        if pos:
            pos.bars_held += 1
            if current_nav > pos.peak_nav:
                pos.peak_nav = current_nav

    def mark_partial_profit(self, fund_code: str, r_level: int):
        """标记某级止盈已执行"""
        pos = self.positions.get(fund_code)
        if pos:
            pos.partial_profit_taken[r_level] = True

    def check_exit(self, fund_code: str, prices: list[float],
                   current_environment: str) -> Optional[ExitSignal]:
        """检查单只基金是否触发退出信号"""
        pos = self.positions.get(fund_code)
        if not pos:
            return None

        return evaluate_exit(
            fund_code=fund_code,
            prices=prices,
            entry_nav=pos.entry_nav,
            peak_nav=pos.peak_nav,
            bars_held=pos.bars_held,
            current_environment=current_environment,
            entry_environment=pos.entry_environment,
            strategy_name=pos.strategy_name,
            initial_risk=pos.initial_risk,
            partial_profit_taken=pos.partial_profit_taken,
        )

    def scan_all_exits(self, price_map: dict[str, list[float]],
                       current_environment: str) -> list[ExitSignal]:
        """扫描所有持仓，返回触发退出的信号列表"""
        signals = []
        for fund_code in list(self.positions.keys()):
            prices = price_map.get(fund_code)
            if not prices:
                continue
            signal = self.check_exit(fund_code, prices, current_environment)
            if signal:
                signals.append(signal)
        # 按优先级排序（数字越小越优先）
        signals.sort(key=lambda s: s.priority)
        return signals
