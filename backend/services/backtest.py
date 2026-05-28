"""回测引擎 V4：均线交叉 + 趋势确认 + 逐笔止损"""
import math
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import asc
from models import FundNav, Fund
from services.calculator import calculate_rsi, calculate_atr
from constants import (
    FUND_SECTOR, INITIAL_BALANCE, MAX_POSITION_VALUE, MIN_CASH_RESERVE,
    STOP_LOSS, TRAILING_TRIGGER, TRAILING_DRAWDOWN,
    BUY_FEE, SELL_FEE_SHORT, SELL_FEE_LONG, SELL_FEE_YEAR,
    ATR_PERIOD_SHORT, HARD_STOP_ATR_MULTIPLE, TRAILING_STOP_ATR_MULTIPLE, TIME_STOP_BARS,
    TRADE_COOLDOWN_DAYS, TRAILING_STOP_PCT,
)


def calc_dynamic_slippage(atr_pct: float) -> float:
    """动态滑点：基于波动率，替代固定 0.05%
    - 波动率低（ATR<0.5%）→ 滑点 ~0.03%
    - 正常波动（ATR~1%）  → 滑点 ~0.15%
    - 高波动（ATR~2%）    → 滑点 ~0.35%
    """
    return 0.0002 + atr_pct * 0.15


@dataclass
class BuyLot:
    """单笔买入记录"""
    code: str
    name: str
    sector: str
    shares: float
    buy_nav: float
    buy_amount: float
    buy_date: date
    highest_nav: float
    trailing_active: bool


@dataclass
class TradeRecord:
    trade_date: date
    code: str
    name: str
    sector: str
    action: str
    shares: float
    nav: float
    amount: float
    fee: float
    reason: str


@dataclass
class DailySnapshot:
    trade_date: date
    total_assets: float
    cash: float
    holdings_value: float
    equity_ratio: float
    market_rsi: float
    market_mode: str
    num_positions: int
    daily_return: float


def _ma(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return 0
    return sum(prices[-period:]) / period


def detect_market_mode(prices: list[float]) -> str:
    if len(prices) < 60:
        return "oscillation"
    ma20 = _ma(prices, 20)
    ma60 = _ma(prices, 60)
    close = prices[-1]
    if ma20 > ma60 and close > ma20:
        return "trend"
    return "oscillation"


class BacktestEngine:
    def __init__(self, db: Session, start_date: date, end_date: date, benchmark_code: str = "000961"):
        self.db = db
        self.start_date = start_date
        self.end_date = end_date
        self.benchmark_code = benchmark_code

        self.cash = INITIAL_BALANCE
        self.lots: list[BuyLot] = []
        self.trade_log: list[TradeRecord] = []
        self.daily_snapshots: list[DailySnapshot] = []
        self.total_fees = 0.0

        self.nav_data: dict[str, list[tuple[date, float]]] = {}
        self.fund_names: dict[str, str] = {}
        self._load_data()

    def _load_data(self):
        funds = self.db.query(Fund).all()
        self.fund_names = {f.code: (f.name or f.code) for f in funds}
        codes = list(FUND_SECTOR.keys()) + [self.benchmark_code]
        for code in set(codes):
            navs = (
                self.db.query(FundNav)
                .filter(FundNav.fund_code == code)
                .order_by(asc(FundNav.date))
                .all()
            )
            if navs:
                self.nav_data[code] = [(n.date, n.nav) for n in navs]

    def _get_nav(self, code: str, target_date: date) -> Optional[float]:
        if code not in self.nav_data:
            return None
        result = None
        for d, nav in self.nav_data[code]:
            if d <= target_date:
                result = nav
            else:
                break
        return result

    def _get_prices_until(self, code: str, target_date: date, min_count: int = 60) -> list[float]:
        if code not in self.nav_data:
            return []
        prices = [nav for d, nav in self.nav_data[code] if d <= target_date]
        return prices if len(prices) >= min_count else []

    def _get_trading_dates(self) -> list[date]:
        if self.benchmark_code not in self.nav_data:
            return []
        return [d for d, _ in self.nav_data[self.benchmark_code]
                if self.start_date <= d <= self.end_date]

    def _holdings_value(self, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            nav = self._get_nav(lot.code, ref_date)
            if nav:
                total += lot.shares * nav
        return total

    def _position_value(self, code: str, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            if lot.code == code:
                nav = self._get_nav(lot.code, ref_date)
                if nav:
                    total += lot.shares * nav
        return total

    def _sell_lot(self, lot: BuyLot, sell_shares: float, nav: float, trade_date: date, reason: str):
        if sell_shares <= 0 or lot.shares <= 0:
            return
        sell_shares = min(sell_shares, lot.shares)
        amount = sell_shares * nav

        holding_days = (trade_date - lot.buy_date).days
        if holding_days < 7:
            fee_rate = SELL_FEE_SHORT
        elif holding_days < 365:
            fee_rate = SELL_FEE_LONG
        else:
            fee_rate = SELL_FEE_YEAR
        fee = amount * fee_rate
        self.total_fees += fee

        self.cash += amount - fee
        lot.shares -= sell_shares

        action = "清仓" if lot.shares < 0.0001 else "减仓"
        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=lot.code, name=lot.name,
            sector=lot.sector, action=action,
            shares=sell_shares, nav=nav, amount=amount, fee=fee,
            reason=reason,
        ))

    def _buy(self, code: str, buy_amount: float, nav: float, trade_date: date, reason: str):
        fee = buy_amount * BUY_FEE
        self.total_fees += fee
        actual_amount = buy_amount - fee
        shares = actual_amount / nav
        self.cash -= buy_amount

        lot = BuyLot(
            code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"),
            shares=shares, buy_nav=nav, buy_amount=buy_amount,
            buy_date=trade_date, highest_nav=nav, trailing_active=False,
        )
        self.lots.append(lot)

        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"), action="建仓",
            shares=shares, nav=nav, amount=buy_amount, fee=fee,
            reason=reason,
        ))

    def run(self) -> dict:
        trading_dates = self._get_trading_dates()
        if not trading_dates:
            raise ValueError("回测期间无交易日数据")

        fund_codes = [c for c in FUND_SECTOR.keys() if c in self.nav_data]
        prev_total = INITIAL_BALANCE

        # 记录前一日的均线状态（用于判断交叉）
        prev_ma_state: dict[str, str] = {}  # code -> "above" / "below"
        last_dca_month: tuple[int, int] = (0, 0)  # 上次定投的 (year, month)

        for i, today in enumerate(trading_dates):
            # 预热期
            if i < 60:
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=INITIAL_BALANCE,
                    cash=INITIAL_BALANCE, holdings_value=0, equity_ratio=0,
                    market_rsi=50, market_mode="oscillation",
                    num_positions=0, daily_return=0,
                ))
                # 初始化均线状态
                if i >= 59:
                    for code in fund_codes:
                        prices = self._get_prices_until(code, today, 20)
                        if prices:
                            close = prices[-1]
                            ma20 = _ma(prices, 20)
                            prev_ma_state[code] = "above" if close > ma20 else "below"
                continue

            # 加载价格数据
            all_prices_map = {}
            all_rsis = []
            for code in fund_codes:
                prices = self._get_prices_until(code, today, 20)
                if prices:
                    all_prices_map[code] = prices
                    if len(prices) >= 60:
                        all_rsis.append(calculate_rsi(prices))

            market_rsi = sum(all_rsis) / len(all_rsis) if all_rsis else 50

            # 市场模式
            benchmark_prices = self._get_prices_until(self.benchmark_code, today, 60)
            market_mode = detect_market_mode(benchmark_prices) if benchmark_prices else "oscillation"

            if market_mode == "trend":
                max_equity_ratio = 0.80
            else:
                max_equity_ratio = 0.50

            # ============ 止损 / 止盈 ============
            for lot in list(self.lots):
                nav = self._get_nav(lot.code, today)
                if not nav:
                    continue

                lot.highest_nav = max(lot.highest_nav, nav)
                pnl_pct = (nav - lot.buy_nav) / lot.buy_nav if lot.buy_nav > 0 else 0
                from_peak = (nav - lot.highest_nav) / lot.highest_nav if lot.highest_nav > 0 else 0

                if pnl_pct >= TRAILING_TRIGGER:
                    lot.trailing_active = True

                should_sell = False
                reason = ""

                # 止损
                if pnl_pct <= STOP_LOSS:
                    should_sell = True
                    reason = f"止损 {pnl_pct*100:.1f}%≤{STOP_LOSS*100:.0f}%"

                # 移动止盈
                elif lot.trailing_active and from_peak <= -TRAILING_DRAWDOWN:
                    should_sell = True
                    reason = f"止盈 {pnl_pct*100:.1f}% 从高点{from_peak*100:.1f}%"

                # RSI 超买
                else:
                    rsi = calculate_rsi(all_prices_map.get(lot.code, []))
                    if rsi and rsi > 72:
                        should_sell = True
                        reason = f"RSI={rsi:.0f} 超买"

                # 均线死叉卖出：价格跌破 20MA 且之前在 20MA 上方
                if not should_sell:
                    prices = all_prices_map.get(lot.code, [])
                    if len(prices) >= 20:
                        close = prices[-1]
                        ma20 = _ma(prices, 20)
                        cur_state = "above" if close > ma20 else "below"
                        if cur_state == "below" and prev_ma_state.get(lot.code) == "above":
                            # 价格跌破 20MA，且持仓盈利 > 0 → 止盈
                            if pnl_pct > 0:
                                should_sell = True
                                reason = f"跌破20MA 盈利{pnl_pct*100:.1f}%"

                if should_sell:
                    self._sell_lot(lot, lot.shares, nav, today, reason)

            self.lots = [l for l in self.lots if l.shares > 0.0001]

            # ============ 买入 ============
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val

            # ===== 定投逻辑：每月第一个交易日买入宽基基金 =====
            current_month = (today.year, today.month)
            if current_month != last_dca_month:
                last_dca_month = current_month
                dca_funds = [c for c in fund_codes if FUND_SECTOR.get(c) in ("宽基", "消费", "科技")]
                dca_amount_per_fund = 3000  # 每只每月投 3000
                for code in dca_funds:
                    available = self.cash - MIN_CASH_RESERVE
                    if available < dca_amount_per_fund:
                        break
                    current_value = self._position_value(code, today)
                    if current_value >= MAX_POSITION_VALUE:
                        continue
                    nav = self._get_nav(code, today)
                    if nav:
                        self._buy(code, min(dca_amount_per_fund, available), nav, today,
                                  f"定投 {today.strftime('%Y-%m')}")

            # 战术买入：只在趋势市中进行，震荡市仅靠定投
            if market_mode == "trend":
                buy_candidates = []
                for code in fund_codes:
                    prices = all_prices_map.get(code, [])
                    if len(prices) < 60:
                        continue

                    close = prices[-1]
                    ma20_val = _ma(prices, 20)
                    ma60_val = _ma(prices, 60)
                    rsi = calculate_rsi(prices)
                    sector = FUND_SECTOR.get(code, "其他")

                    cur_state = "above" if close > ma20_val else "below"
                    prev_state = prev_ma_state.get(code, "below")

                    current_value = self._position_value(code, today)

                    # 信号1：金叉
                    golden_cross = cur_state == "above" and prev_state == "below"

                    # 信号2：趋势确认（价格>20MA>60MA 且 RSI 50-68）
                    trend_buy = (close > ma20_val > ma60_val > 0 and 50 <= rsi <= 68)

                    if not golden_cross and not trend_buy:
                        continue

                    if rsi > 68:
                        continue

                    if current_value >= MAX_POSITION_VALUE:
                        continue

                    base = 5000 if golden_cross else 3000

                    if current_value > 0:
                        remaining = MAX_POSITION_VALUE - current_value
                        if remaining <= 0:
                            continue
                        base = min(base, remaining, 3000)

                    available_equity = total_assets * max_equity_ratio - holdings_val
                    if available_equity <= 0:
                        break
                    base = min(base, available_equity)

                    available = self.cash - MIN_CASH_RESERVE
                    buy_amount = min(base, available)

                    if buy_amount >= 2000:
                        signal = "金叉" if golden_cross else "趋势"
                        buy_candidates.append({
                            "code": code, "amount": buy_amount,
                            "rsi": rsi, "sector": sector, "signal": signal,
                        })

                buy_candidates.sort(key=lambda x: x["rsi"])
                for cand in buy_candidates:
                    nav = self._get_nav(cand["code"], today)
                    if nav:
                        self._buy(cand["code"], cand["amount"], nav, today,
                                  f"{cand['signal']} RSI={cand['rsi']:.0f}")

            # 更新均线状态
            for code in fund_codes:
                prices = all_prices_map.get(code, [])
                if prices:
                    close = prices[-1]
                    ma20_val = _ma(prices, 20)
                    prev_ma_state[code] = "above" if close > ma20_val else "below"

            # 快照
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val
            daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0

            self.daily_snapshots.append(DailySnapshot(
                trade_date=today, total_assets=total_assets,
                cash=self.cash, holdings_value=holdings_val,
                equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                market_rsi=market_rsi, market_mode=market_mode,
                num_positions=len(self.lots),
                daily_return=daily_ret,
            ))
            prev_total = total_assets

        return self._compute_result(trading_dates)

    def _compute_result(self, trading_dates: list[date]) -> dict:
        if not self.daily_snapshots:
            raise ValueError("无快照数据")

        final_assets = self.daily_snapshots[-1].total_assets
        total_return = (final_assets - INITIAL_BALANCE) / INITIAL_BALANCE
        trading_days = len(self.daily_snapshots)
        years = trading_days / 252
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        peak = INITIAL_BALANCE
        max_dd = 0
        dd_start = trading_dates[0] if trading_dates else self.start_date
        dd_end = dd_start
        current_dd_start = dd_start
        for snap in self.daily_snapshots:
            if snap.total_assets > peak:
                peak = snap.total_assets
                current_dd_start = snap.trade_date
            dd = (peak - snap.total_assets) / peak
            if dd > max_dd:
                max_dd = dd
                dd_start = current_dd_start
                dd_end = snap.trade_date

        returns = [s.daily_return for s in self.daily_snapshots if s.daily_return != 0]
        if len(returns) > 1:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance) * math.sqrt(252)
            sharpe = ((annualized_return - 0.025) / volatility) if volatility > 0 else 0
        else:
            volatility = 0
            sharpe = 0

        calmar = annualized_return / max_dd if max_dd > 0 else 0

        # 胜率
        sell_trades = [t for t in self.trade_log if t.action == "清仓"]
        closed_lots_pnl = []
        for t in sell_trades:
            for buy_t in self.trade_log:
                if buy_t.code == t.code and buy_t.action == "建仓" and buy_t.trade_date <= t.trade_date:
                    if t.nav > buy_t.nav:
                        closed_lots_pnl.append(1)
                    else:
                        closed_lots_pnl.append(0)
                    break
        win_rate = sum(closed_lots_pnl) / len(closed_lots_pnl) if closed_lots_pnl else 0

        benchmark_nav_start = self._get_nav(self.benchmark_code, self.start_date)
        benchmark_nav_end = self._get_nav(self.benchmark_code, self.end_date)
        benchmark_return = ((benchmark_nav_end / benchmark_nav_start) - 1) if benchmark_nav_start and benchmark_nav_end else 0

        avg_equity = sum(s.equity_ratio for s in self.daily_snapshots) / len(self.daily_snapshots)
        trend_days = sum(1 for s in self.daily_snapshots if s.market_mode == "trend")
        osc_days = sum(1 for s in self.daily_snapshots if s.market_mode == "oscillation")

        return {
            "period": f"{self.start_date} ~ {self.end_date}",
            "trading_days": trading_days,
            "total_return": f"{total_return*100:.2f}%",
            "annualized_return": f"{annualized_return*100:.2f}%",
            "max_drawdown": f"{max_dd*100:.2f}%",
            "max_dd_period": f"{dd_start} ~ {dd_end}",
            "sharpe_ratio": round(sharpe, 4),
            "calmar_ratio": round(calmar, 4),
            "volatility": f"{volatility*100:.2f}%",
            "win_rate": f"{win_rate*100:.1f}%",
            "total_trades": len(self.trade_log),
            "total_fees": round(self.total_fees, 2),
            "final_balance": round(final_assets, 2),
            "benchmark_return": f"{benchmark_return*100:.2f}%",
            "excess_return": f"{(total_return - benchmark_return)*100:.2f}%",
            "avg_equity_ratio": f"{avg_equity*100:.1f}%",
            "trend_days": trend_days,
            "oscillation_days": osc_days,
            "equity_curve": [
                {"date": s.trade_date.isoformat(), "assets": round(s.total_assets, 2),
                 "equity_pct": round(s.equity_ratio * 100, 1), "rsi": round(s.market_rsi, 1),
                 "mode": s.market_mode}
                for s in self.daily_snapshots[::5]
            ],
            "trades": [
                {"date": t.trade_date.isoformat(), "code": t.code, "name": t.name,
                 "sector": t.sector, "action": t.action, "amount": round(t.amount, 2),
                 "nav": t.nav, "fee": round(t.fee, 2), "davis": 0, "reason": t.reason}
                for t in self.trade_log[-50:]
            ],
        }


def run_backtest(db: Session, start_date: date, end_date: date) -> dict:
    engine = BacktestEngine(db, start_date, end_date)
    return engine.run()


# ==================== V6 回测引擎 ====================

from services.environment import sense_environment
from services.strategy import TrendStrategy, OscillationStrategy, BreakoutStrategy
from services.position import calculate_position_size
from services.exit_manager import ExitManager


class BacktestEngineV6:
    """V6 回测引擎：环境自适应 + 多策略 + ATR 仓位管理"""

    def __init__(self, db: Session, start_date: date, end_date: date, benchmark_code: str = "000961"):
        self.db = db
        self.start_date = start_date
        self.end_date = end_date
        self.benchmark_code = benchmark_code

        self.cash = INITIAL_BALANCE
        self.lots: list[BuyLot] = []
        self.trade_log: list[TradeRecord] = []
        self.daily_snapshots: list[DailySnapshot] = []
        self.total_fees = 0.0

        self.nav_data: dict[str, list[tuple[date, float]]] = {}
        self.fund_names: dict[str, str] = {}
        self._load_data()

    def _load_data(self):
        funds = self.db.query(Fund).all()
        self.fund_names = {f.code: (f.name or f.code) for f in funds}
        codes = list(FUND_SECTOR.keys()) + [self.benchmark_code]
        for code in set(codes):
            navs = (
                self.db.query(FundNav)
                .filter(FundNav.fund_code == code)
                .order_by(asc(FundNav.date))
                .all()
            )
            if navs:
                self.nav_data[code] = [(n.date, n.nav) for n in navs]

    def _get_nav(self, code: str, target_date: date) -> Optional[float]:
        if code not in self.nav_data:
            return None
        result = None
        for d, nav in self.nav_data[code]:
            if d <= target_date:
                result = nav
            else:
                break
        return result

    def _get_prices_until(self, code: str, target_date: date, min_count: int = 20) -> list[float]:
        if code not in self.nav_data:
            return []
        prices = [nav for d, nav in self.nav_data[code] if d <= target_date]
        return prices if len(prices) >= min_count else []

    def _get_trading_dates(self) -> list[date]:
        if self.benchmark_code not in self.nav_data:
            return []
        return [d for d, _ in self.nav_data[self.benchmark_code]
                if self.start_date <= d <= self.end_date]

    def _holdings_value(self, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            nav = self._get_nav(lot.code, ref_date)
            if nav:
                total += lot.shares * nav
        return total

    def _position_value(self, code: str, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            if lot.code == code:
                nav = self._get_nav(lot.code, ref_date)
                if nav:
                    total += lot.shares * nav
        return total

    def _sell_lot(self, lot: BuyLot, sell_shares: float, nav: float, trade_date: date, reason: str):
        if sell_shares <= 0 or lot.shares <= 0:
            return
        sell_shares = min(sell_shares, lot.shares)
        amount = sell_shares * nav

        holding_days = (trade_date - lot.buy_date).days
        if holding_days < 7:
            fee_rate = SELL_FEE_SHORT
        elif holding_days < 365:
            fee_rate = SELL_FEE_LONG
        else:
            fee_rate = SELL_FEE_YEAR
        fee = amount * fee_rate
        self.total_fees += fee

        self.cash += amount - fee
        lot.shares -= sell_shares

        action = "清仓" if lot.shares < 0.0001 else "减仓"
        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=lot.code, name=lot.name,
            sector=lot.sector, action=action,
            shares=sell_shares, nav=nav, amount=amount, fee=fee,
            reason=reason,
        ))

    def _buy(self, code: str, buy_amount: float, nav: float, trade_date: date, reason: str):
        fee = buy_amount * BUY_FEE
        self.total_fees += fee
        actual_amount = buy_amount - fee
        shares = actual_amount / nav
        self.cash -= buy_amount

        lot = BuyLot(
            code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"),
            shares=shares, buy_nav=nav, buy_amount=buy_amount,
            buy_date=trade_date, highest_nav=nav, trailing_active=False,
        )
        self.lots.append(lot)

        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"), action="建仓",
            shares=shares, nav=nav, amount=buy_amount, fee=fee,
            reason=reason,
        ))

    def run(self) -> dict:
        trading_dates = self._get_trading_dates()
        if not trading_dates:
            raise ValueError("回测期间无交易日数据")

        fund_codes = [c for c in FUND_SECTOR.keys() if c in self.nav_data]
        prev_total = INITIAL_BALANCE
        exit_mgr = ExitManager()

        strategies = {
            "trend": TrendStrategy(),
            "oscillation": OscillationStrategy(),
            "breakout": BreakoutStrategy(),
        }

        for i, today in enumerate(trading_dates):
            # 预热期
            if i < 80:
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=INITIAL_BALANCE,
                    cash=INITIAL_BALANCE, holdings_value=0, equity_ratio=0,
                    market_rsi=50, market_mode="oscillation",
                    num_positions=0, daily_return=0,
                ))
                continue

            # Layer 1: 环境感知
            benchmark_prices = self._get_prices_until(self.benchmark_code, today, 80)
            if len(benchmark_prices) < 80:
                continue

            env_result = sense_environment(benchmark_prices)

            # 加载价格
            all_prices_map = {}
            for code in fund_codes:
                prices = self._get_prices_until(code, today, 20)
                if prices:
                    all_prices_map[code] = prices

            # Layer 4: 退出检查
            for lot in list(self.lots):
                nav = self._get_nav(lot.code, today)
                if not nav:
                    continue

                lot.highest_nav = max(lot.highest_nav, nav)
                pnl_pct = (nav - lot.buy_nav) / lot.buy_nav if lot.buy_nav > 0 else 0
                rsi = calculate_rsi(all_prices_map.get(lot.code, []))

                # 更新退出管理器
                if lot.code not in exit_mgr.positions:
                    exit_mgr.add_position(
                        lot.code, lot.buy_nav, lot.buy_nav * 0.04,
                        env_result.strategy, env_result.environment.value,
                    )
                exit_mgr.update_bar(lot.code, nav)

                # 状态破坏退出
                from services.strategy import _is_environment_break
                if _is_environment_break(env_result.environment.value, env_result.environment.value, env_result.strategy):
                    self._sell_lot(lot, lot.shares, nav, today, "状态破坏")
                    exit_mgr.remove_position(lot.code)
                    continue

                # 硬止损
                atr = calculate_atr(all_prices_map.get(lot.code, []), ATR_PERIOD_SHORT)
                stop_price = lot.buy_nav - HARD_STOP_ATR_MULTIPLE * atr
                if nav <= stop_price:
                    self._sell_lot(lot, lot.shares, nav, today, f"硬止损 {pnl_pct*100:.1f}%")
                    exit_mgr.remove_position(lot.code)
                    continue

                # 移动止盈（趋势环境）
                if env_result.strategy == "trend" and lot.highest_nav > lot.buy_nav:
                    trailing_stop = lot.highest_nav - TRAILING_STOP_ATR_MULTIPLE * atr
                    if nav <= trailing_stop:
                        self._sell_lot(lot, lot.shares, nav, today, f"移动止盈 R={pnl_pct*100:.1f}%")
                        exit_mgr.remove_position(lot.code)
                        continue

                # 时间止损（震荡环境）
                pos = exit_mgr.positions.get(lot.code)
                if env_result.strategy == "oscillation" and pos and pos.bars_held >= TIME_STOP_BARS and pnl_pct <= 0:
                    self._sell_lot(lot, lot.shares, nav, today, f"时间止损 {pos.bars_held}天")
                    exit_mgr.remove_position(lot.code)
                    continue

            self.lots = [l for l in self.lots if l.shares > 0.0001]

            # 跳过暂停环境
            if env_result.strategy == "pause":
                holdings_val = self._holdings_value(today)
                total_assets = self.cash + holdings_val
                daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=total_assets,
                    cash=self.cash, holdings_value=holdings_val,
                    equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                    market_rsi=50, market_mode="pause",
                    num_positions=len(self.lots), daily_return=daily_ret,
                ))
                prev_total = total_assets
                continue

            # Layer 2 & 3: 策略扫描 + 仓位计算
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val
            current_dd = (INITIAL_BALANCE - total_assets) / INITIAL_BALANCE if total_assets < INITIAL_BALANCE else 0

            active_strategy = strategies.get(env_result.strategy)
            if active_strategy:
                buy_signals = []
                for code in fund_codes:
                    prices = all_prices_map.get(code, [])
                    if len(prices) < 30:
                        continue
                    if self._position_value(code, today) > 0:
                        continue

                    signal = active_strategy.scan_entry(
                        code, self.fund_names.get(code, code), prices,
                        env_result.adx, env_result.plus_di, env_result.minus_di,
                    )
                    if signal:
                        buy_signals.append(signal)

                buy_signals.sort(key=lambda s: s.strength, reverse=True)

                for signal in buy_signals:
                    if self.cash < MIN_CASH_RESERVE + 2000:
                        break

                    pos = calculate_position_size(
                        total_assets, all_prices_map.get(signal.fund_code, []),
                        env_result.position_coeff, current_dd,
                    )
                    if pos["amount"] <= 0:
                        continue

                    buy_amount = min(pos["amount"], self.cash - MIN_CASH_RESERVE)
                    if buy_amount < 2000:
                        continue

                    nav = self._get_nav(signal.fund_code, today)
                    if nav:
                        self._buy(signal.fund_code, buy_amount, nav, today, signal.reason)
                        exit_mgr.add_position(
                            signal.fund_code, nav, signal.initial_risk,
                            signal.strategy, env_result.environment.value,
                        )

            # 快照
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val
            daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0

            self.daily_snapshots.append(DailySnapshot(
                trade_date=today, total_assets=total_assets,
                cash=self.cash, holdings_value=holdings_val,
                equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                market_rsi=50, market_mode=env_result.environment.value,
                num_positions=len(self.lots), daily_return=daily_ret,
            ))
            prev_total = total_assets

        return self._compute_result(trading_dates)

    def _compute_result(self, trading_dates: list[date]) -> dict:
        if not self.daily_snapshots:
            raise ValueError("无快照数据")

        final_assets = self.daily_snapshots[-1].total_assets
        total_return = (final_assets - INITIAL_BALANCE) / INITIAL_BALANCE
        trading_days = len(self.daily_snapshots)
        years = trading_days / 252
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        peak = INITIAL_BALANCE
        max_dd = 0
        dd_start = trading_dates[0] if trading_dates else self.start_date
        dd_end = dd_start
        current_dd_start = dd_start
        for snap in self.daily_snapshots:
            if snap.total_assets > peak:
                peak = snap.total_assets
                current_dd_start = snap.trade_date
            dd = (peak - snap.total_assets) / peak
            if dd > max_dd:
                max_dd = dd
                dd_start = current_dd_start
                dd_end = snap.trade_date

        returns = [s.daily_return for s in self.daily_snapshots if s.daily_return != 0]
        if len(returns) > 1:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance) * math.sqrt(252)
            sharpe = ((annualized_return - 0.025) / volatility) if volatility > 0 else 0
        else:
            volatility = 0
            sharpe = 0

        calmar = annualized_return / max_dd if max_dd > 0 else 0

        sell_trades = [t for t in self.trade_log if t.action == "清仓"]
        closed_lots_pnl = []
        for t in sell_trades:
            for buy_t in self.trade_log:
                if buy_t.code == t.code and buy_t.action == "建仓" and buy_t.trade_date <= t.trade_date:
                    closed_lots_pnl.append(1 if t.nav > buy_t.nav else 0)
                    break
        win_rate = sum(closed_lots_pnl) / len(closed_lots_pnl) if closed_lots_pnl else 0

        benchmark_nav_start = self._get_nav(self.benchmark_code, self.start_date)
        benchmark_nav_end = self._get_nav(self.benchmark_code, self.end_date)
        benchmark_return = ((benchmark_nav_end / benchmark_nav_start) - 1) if benchmark_nav_start and benchmark_nav_end else 0

        avg_equity = sum(s.equity_ratio for s in self.daily_snapshots) / len(self.daily_snapshots)
        env_distribution = {}
        for s in self.daily_snapshots:
            env_distribution[s.market_mode] = env_distribution.get(s.market_mode, 0) + 1

        return {
            "engine": "V6",
            "period": f"{self.start_date} ~ {self.end_date}",
            "trading_days": trading_days,
            "total_return": f"{total_return*100:.2f}%",
            "annualized_return": f"{annualized_return*100:.2f}%",
            "max_drawdown": f"{max_dd*100:.2f}%",
            "max_dd_period": f"{dd_start} ~ {dd_end}",
            "sharpe_ratio": round(sharpe, 4),
            "calmar_ratio": round(calmar, 4),
            "volatility": f"{volatility*100:.2f}%",
            "win_rate": f"{win_rate*100:.1f}%",
            "total_trades": len(self.trade_log),
            "total_fees": round(self.total_fees, 2),
            "final_balance": round(final_assets, 2),
            "benchmark_return": f"{benchmark_return*100:.2f}%",
            "excess_return": f"{(total_return - benchmark_return)*100:.2f}%",
            "avg_equity_ratio": f"{avg_equity*100:.1f}%",
            "env_distribution": env_distribution,
            "equity_curve": [
                {"date": s.trade_date.isoformat(), "assets": round(s.total_assets, 2),
                 "equity_pct": round(s.equity_ratio * 100, 1), "mode": s.market_mode}
                for s in self.daily_snapshots[::5]
            ],
            "trades": [
                {"date": t.trade_date.isoformat(), "code": t.code, "name": t.name,
                 "sector": t.sector, "action": t.action, "amount": round(t.amount, 2),
                 "nav": t.nav, "fee": round(t.fee, 2), "reason": t.reason}
                for t in self.trade_log[-50:]
            ],
        }


def run_backtest_v6(db: Session, start_date: date, end_date: date) -> dict:
    engine = BacktestEngineV6(db, start_date, end_date)
    return engine.run()


# ==================== 融合版回测引擎 ====================

from services.environment import sense_environment, analyze_dual_cycle
from services.risk_manager import analyze_r_distribution, get_position_scale_from_r
from constants import RISK_PER_TRADE_PCT


class BacktestEngineFused:
    """融合版回测：V5 信号 + ATR 风控 + 双周期矩阵 + R 分布 + 熔断"""

    def __init__(self, db: Session, start_date: date, end_date: date, benchmark_code: str = "000961"):
        self.db = db
        self.start_date = start_date
        self.end_date = end_date
        self.benchmark_code = benchmark_code

        self.cash = INITIAL_BALANCE
        self.lots: list[BuyLot] = []
        self.trade_log: list[TradeRecord] = []
        self.daily_snapshots: list[DailySnapshot] = []
        self.total_fees = 0.0
        self.r_history: list[float] = []  # R 乘数历史
        self.last_exit_date: dict[str, date] = {}  # 基金冷却期追踪

        self.nav_data: dict[str, list[tuple[date, float]]] = {}
        self.fund_names: dict[str, str] = {}
        self._load_data()

    def _load_data(self):
        funds = self.db.query(Fund).all()
        self.fund_names = {f.code: (f.name or f.code) for f in funds}
        codes = list(FUND_SECTOR.keys()) + [self.benchmark_code]
        for code in set(codes):
            navs = self.db.query(FundNav).filter(FundNav.fund_code == code).order_by(asc(FundNav.date)).all()
            if navs:
                self.nav_data[code] = [(n.date, n.nav) for n in navs]

    def _get_nav(self, code: str, target_date: date) -> Optional[float]:
        if code not in self.nav_data:
            return None
        result = None
        for d, nav in self.nav_data[code]:
            if d <= target_date:
                result = nav
            else:
                break
        return result

    def _get_prices_until(self, code: str, target_date: date, min_count: int = 20) -> list[float]:
        if code not in self.nav_data:
            return []
        prices = [nav for d, nav in self.nav_data[code] if d <= target_date]
        return prices if len(prices) >= min_count else []

    def _get_trading_dates(self) -> list[date]:
        if self.benchmark_code not in self.nav_data:
            return []
        return [d for d, _ in self.nav_data[self.benchmark_code]
                if self.start_date <= d <= self.end_date]

    def _holdings_value(self, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            nav = self._get_nav(lot.code, ref_date)
            if nav:
                total += lot.shares * nav
        return total

    def _position_value(self, code: str, ref_date: date) -> float:
        total = 0
        for lot in self.lots:
            if lot.code == code:
                nav = self._get_nav(lot.code, ref_date)
                if nav:
                    total += lot.shares * nav
        return total

    def _sell_lot(self, lot: BuyLot, sell_shares: float, nav: float,
                  trade_date: date, reason: str, atr_pct: float = 0.005):
        if sell_shares <= 0 or lot.shares <= 0:
            return
        sell_shares = min(sell_shares, lot.shares)
        amount = sell_shares * nav

        # 基础赎回费率（不含滑点）
        holding_days = (trade_date - lot.buy_date).days
        if holding_days < 7:
            base_rate = 0.015
        elif holding_days < 365:
            base_rate = 0.005
        else:
            base_rate = 0.0025

        slippage = calc_dynamic_slippage(atr_pct)
        fee = amount * (base_rate + slippage)
        self.total_fees += fee
        self.cash += amount - fee

        # 记录 R 乘数
        initial_risk = lot.buy_nav * 0.04  # 粗略估算：2ATR ≈ 4% 价格
        r_mult = (nav - lot.buy_nav) / initial_risk if initial_risk > 0 else 0
        self.r_history.append(r_mult)

        lot.shares -= sell_shares
        action = "清仓" if lot.shares < 0.0001 else "减仓"
        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=lot.code, name=lot.name,
            sector=lot.sector, action=action,
            shares=sell_shares, nav=nav, amount=amount, fee=fee,
            reason=reason,
        ))
        if lot.shares < 0.0001:
            self.last_exit_date[lot.code] = trade_date

    def _buy(self, code: str, buy_amount: float, nav: float,
             trade_date: date, reason: str, atr_pct: float = 0.005):
        slippage = calc_dynamic_slippage(atr_pct)
        fee = buy_amount * (0.0015 + slippage)  # 申购费 + 动态滑点
        self.total_fees += fee
        actual_amount = buy_amount - fee
        shares = actual_amount / nav
        self.cash -= buy_amount

        lot = BuyLot(
            code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"),
            shares=shares, buy_nav=nav, buy_amount=buy_amount,
            buy_date=trade_date, highest_nav=nav, trailing_active=False,
        )
        self.lots.append(lot)
        self.trade_log.append(TradeRecord(
            trade_date=trade_date, code=code, name=self.fund_names.get(code, code),
            sector=FUND_SECTOR.get(code, "其他"), action="建仓",
            shares=shares, nav=nav, amount=buy_amount, fee=fee,
            reason=reason,
        ))

    def _check_nav_gap(self, code: str, today: date) -> bool:
        """单日净值变动>5% → 拒绝交易（模拟涨跌停/流动性枯竭）"""
        prices = self._get_prices_until(code, today, 2)
        if len(prices) < 2:
            return True  # 数据不足，拒绝
        daily_change = abs(prices[-1] - prices[-2]) / prices[-2]
        return daily_change > 0.05

    def run(self) -> dict:
        trading_dates = self._get_trading_dates()
        if not trading_dates:
            raise ValueError("回测期间无交易日数据")

        fund_codes = [c for c in FUND_SECTOR.keys()
                      if c in self.nav_data and len(self.nav_data[c]) >= 250]
        prev_total = INITIAL_BALANCE
        last_dca_month = (0, 0)

        for i, today in enumerate(trading_dates):
            # 预热期（需要 80 天数据给环境感知）
            if i < 80:
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=INITIAL_BALANCE,
                    cash=INITIAL_BALANCE, holdings_value=0, equity_ratio=0,
                    market_rsi=50, market_mode="warmup",
                    num_positions=0, daily_return=0,
                ))
                continue

            # 环境感知
            benchmark_prices = self._get_prices_until(self.benchmark_code, today, 80)
            env_result = sense_environment(benchmark_prices)
            env_coeff = env_result.position_coeff

            # 体制识别：长周期方向判断
            dual = analyze_dual_cycle(benchmark_prices)
            long_cycle_down = dual.long_cycle.value == "trend_down"
            long_cycle_up = dual.long_cycle.value == "trend_up"

            # 市场模式（兼容）+ 体制识别
            market_mode = "trend" if env_result.strategy in ("trend", "breakout") else "oscillation"
            if env_result.strategy == "pause":
                market_mode = "pause"
            if long_cycle_down:
                market_mode = "downtrend"
                max_equity_ratio = 0.30
            elif long_cycle_up and market_mode == "trend":
                max_equity_ratio = 0.80
            elif long_cycle_up:
                max_equity_ratio = 0.50
            elif not long_cycle_up and not long_cycle_down:
                # range模式：仓位适度收紧但不过度
                max_equity_ratio = 0.40
            else:
                max_equity_ratio = 0.50

            # R 分布 + 凸性检查
            r_scale = get_position_scale_from_r(self.r_history)

            # 加载价格
            all_prices_map = {}
            for code in fund_codes:
                prices = self._get_prices_until(code, today, 20)
                if prices:
                    all_prices_map[code] = prices

            # ============ ATR 止损 / 止盈 ============
            for lot in list(self.lots):
                nav = self._get_nav(lot.code, today)
                if not nav:
                    continue

                lot.highest_nav = max(lot.highest_nav, nav)
                pnl_pct = (nav - lot.buy_nav) / lot.buy_nav if lot.buy_nav > 0 else 0
                prices = all_prices_map.get(lot.code, [])
                atr = calculate_atr(prices, ATR_PERIOD_SHORT) if prices else 0
                rsi = calculate_rsi(prices) if prices else 50

                should_sell = False
                reason = ""
                holding_days = (today - lot.buy_date).days

                # 1. ATR 硬止损：入场价 - 3*ATR
                if atr > 0 and nav <= lot.buy_nav - HARD_STOP_ATR_MULTIPLE * atr:
                    should_sell = True
                    reason = f"ATR止损 {pnl_pct*100:.1f}%"

                # 2. 固定百分比移动止盈：从高点回撤15%
                elif lot.highest_nav > lot.buy_nav:
                    trailing_stop = lot.highest_nav * (1 - TRAILING_STOP_PCT)
                    if nav <= trailing_stop:
                        peak_pnl = (lot.highest_nav - lot.buy_nav) / lot.buy_nav * 100
                        should_sell = True
                        reason = f"止盈回撤 peak+{peak_pnl:.1f}% now{pnl_pct*100:.1f}%"

                # 3. RSI 超买
                elif rsi > 72:
                    should_sell = True
                    reason = f"RSI={rsi:.0f} 超买"

                # 4. 均线死叉
                elif len(prices) >= 20:
                    ma20 = sum(prices[-20:]) / 20
                    if nav < ma20 and pnl_pct > 0:
                        # 检查前一天是否在 MA 上方
                        prev_prices = prices[:-1]
                        if len(prev_prices) >= 20:
                            prev_ma20 = sum(prev_prices[-20:]) / 20
                            if prev_prices[-1] >= prev_ma20:
                                should_sell = True
                                reason = f"跌破20MA 盈利{pnl_pct*100:.1f}%"

                # 5. 下跌趋势强制减仓
                if not should_sell and long_cycle_down and pnl_pct < 0:
                    should_sell = True
                    reason = f"下跌趋势减仓 {pnl_pct*100:.1f}%"

                if should_sell:
                    atr_pct = atr / nav if nav > 0 and atr > 0 else 0.005
                    self._sell_lot(lot, lot.shares, nav, today, reason, atr_pct)

            self.lots = [l for l in self.lots if l.shares > 0.0001]

            # 暂停环境跳过买入
            if market_mode == "pause":
                holdings_val = self._holdings_value(today)
                total_assets = self.cash + holdings_val
                daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=total_assets,
                    cash=self.cash, holdings_value=holdings_val,
                    equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                    market_rsi=50, market_mode="pause",
                    num_positions=len(self.lots), daily_return=daily_ret,
                ))
                prev_total = total_assets
                continue

            # 凸性暂停
            if r_scale == 0:
                holdings_val = self._holdings_value(today)
                total_assets = self.cash + holdings_val
                daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0
                self.daily_snapshots.append(DailySnapshot(
                    trade_date=today, total_assets=total_assets,
                    cash=self.cash, holdings_value=holdings_val,
                    equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                    market_rsi=50, market_mode="convexity_pause",
                    num_positions=len(self.lots), daily_return=daily_ret,
                ))
                prev_total = total_assets
                continue

            # ============ 定投（弱势环境跳过/减额） ============
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val
            current_month = (today.year, today.month)
            dca_amount = 3000
            if not long_cycle_up:
                dca_amount = 1500  # range模式：定投减半
            if long_cycle_down or market_mode == "pause":
                dca_amount = 0     # 下跌/暂停：不定投
            if current_month != last_dca_month and dca_amount > 0:
                last_dca_month = current_month
                dca_funds = [c for c in fund_codes if FUND_SECTOR.get(c) in ("宽基", "消费", "科技")]
                for code in dca_funds:
                    available = self.cash - MIN_CASH_RESERVE
                    if available < dca_amount:
                        break
                    current_value = self._position_value(code, today)
                    if current_value >= MAX_POSITION_VALUE:
                        continue
                    nav = self._get_nav(code, today)
                    # 冷却期检查
                    last_exit = self.last_exit_date.get(code)
                    if last_exit and (today - last_exit).days < TRADE_COOLDOWN_DAYS:
                        continue
                    if nav and not self._check_nav_gap(code, today):
                        prices_dca = all_prices_map.get(code, [])
                        atr_dca = calculate_atr(prices_dca, ATR_PERIOD_SHORT) if prices_dca else 0
                        atr_pct_dca = atr_dca / nav if nav > 0 and atr_dca > 0 else 0.005
                        self._buy(code, min(dca_amount, available), nav, today,
                                  f"定投 {today.strftime('%Y-%m')}", atr_pct_dca)

            # ============ 战术买入（V5 信号 + 双周期过滤 + ATR 仓位） ============
            if market_mode == "trend":
                holdings_val = self._holdings_value(today)
                total_assets = self.cash + holdings_val
                current_dd = (INITIAL_BALANCE - total_assets) / INITIAL_BALANCE if total_assets < INITIAL_BALANCE else 0

                buy_candidates = []
                for code in fund_codes:
                    prices = all_prices_map.get(code, [])
                    if len(prices) < 60:
                        continue
                    if self._check_nav_gap(code, today):
                        continue
                    # 冷却期检查
                    last_exit = self.last_exit_date.get(code)
                    if last_exit and (today - last_exit).days < TRADE_COOLDOWN_DAYS:
                        continue

                    close = prices[-1]
                    ma20_val = _ma(prices, 20)
                    ma60_val = _ma(prices, 60)
                    rsi = calculate_rsi(prices)

                    # V5 信号
                    prev_close = prices[-2] if len(prices) >= 2 else close
                    prev_ma20 = sum(prices[-21:-1]) / 20 if len(prices) >= 21 else ma20_val
                    golden_cross = (close > ma20_val) and (prev_close <= prev_ma20)
                    trend_buy = (close > ma20_val > ma60_val > 0 and 50 <= rsi <= 68)

                    if not golden_cross and not trend_buy:
                        continue
                    if rsi > 68:
                        continue

                    # 双周期矩阵过滤
                    dual = analyze_dual_cycle(prices)
                    if dual.allowed_strategy == "none" and dual.cell_expectation == "negative":
                        continue

                    current_value = self._position_value(code, today)
                    if current_value >= MAX_POSITION_VALUE:
                        continue

                    # ATR 仓位 × 环境系数 × R 缩放
                    atr = calculate_atr(prices, ATR_PERIOD_SHORT)
                    risk_budget = total_assets * RISK_PER_TRADE_PCT
                    atr_pct = atr / close if close > 0 else 0.01
                    base_from_atr = risk_budget / atr_pct if atr_pct > 0 else 5000
                    base = base_from_atr * env_coeff * r_scale
                    base = max(2000, min(8000, base))

                    if current_value > 0:
                        remaining = MAX_POSITION_VALUE - current_value
                        if remaining <= 0:
                            continue
                        base = min(base, remaining)

                    available_equity = total_assets * max_equity_ratio - holdings_val
                    if available_equity <= 0:
                        break
                    base = min(base, available_equity)

                    available = self.cash - MIN_CASH_RESERVE
                    buy_amount = min(base, available)

                    if buy_amount >= 2000:
                        signal = "金叉" if golden_cross else "趋势"
                        buy_candidates.append({
                            "code": code, "amount": buy_amount,
                            "rsi": rsi, "signal": signal,
                            "atr_pct": atr_pct,
                        })

                buy_candidates.sort(key=lambda x: x["rsi"])
                for cand in buy_candidates:
                    nav = self._get_nav(cand["code"], today)
                    if nav:
                        self._buy(cand["code"], cand["amount"], nav, today,
                                  f"{cand['signal']} RSI={cand['rsi']:.0f}",
                                  cand["atr_pct"])

            # 快照
            holdings_val = self._holdings_value(today)
            total_assets = self.cash + holdings_val
            daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0

            all_rsis = []
            for code in fund_codes:
                prices = all_prices_map.get(code, [])
                if len(prices) >= 60:
                    all_rsis.append(calculate_rsi(prices))
            market_rsi = sum(all_rsis) / len(all_rsis) if all_rsis else 50

            self.daily_snapshots.append(DailySnapshot(
                trade_date=today, total_assets=total_assets,
                cash=self.cash, holdings_value=holdings_val,
                equity_ratio=holdings_val / total_assets if total_assets > 0 else 0,
                market_rsi=market_rsi, market_mode=market_mode,
                num_positions=len(self.lots), daily_return=daily_ret,
            ))
            prev_total = total_assets

        return self._compute_result(trading_dates)

    def _compute_result(self, trading_dates: list[date]) -> dict:
        if not self.daily_snapshots:
            raise ValueError("无快照数据")

        final_assets = self.daily_snapshots[-1].total_assets
        total_return = (final_assets - INITIAL_BALANCE) / INITIAL_BALANCE
        trading_days = len(self.daily_snapshots)
        years = trading_days / 252
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        peak = INITIAL_BALANCE
        max_dd = 0
        dd_start = trading_dates[0] if trading_dates else self.start_date
        dd_end = dd_start
        current_dd_start = dd_start
        for snap in self.daily_snapshots:
            if snap.total_assets > peak:
                peak = snap.total_assets
                current_dd_start = snap.trade_date
            dd = (peak - snap.total_assets) / peak
            if dd > max_dd:
                max_dd = dd
                dd_start = current_dd_start
                dd_end = snap.trade_date

        returns = [s.daily_return for s in self.daily_snapshots if s.daily_return != 0]
        if len(returns) > 1:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            volatility = math.sqrt(variance) * math.sqrt(252)
            sharpe = ((annualized_return - 0.025) / volatility) if volatility > 0 else 0
        else:
            volatility = 0
            sharpe = 0

        calmar = annualized_return / max_dd if max_dd > 0 else 0

        # 胜率
        sell_trades = [t for t in self.trade_log if t.action == "清仓"]
        closed_pnl = []
        for t in sell_trades:
            for buy_t in self.trade_log:
                if buy_t.code == t.code and buy_t.action == "建仓" and buy_t.trade_date <= t.trade_date:
                    closed_pnl.append(1 if t.nav > buy_t.nav else 0)
                    break
        win_rate = sum(closed_pnl) / len(closed_pnl) if closed_pnl else 0

        benchmark_nav_start = self._get_nav(self.benchmark_code, self.start_date)
        benchmark_nav_end = self._get_nav(self.benchmark_code, self.end_date)
        benchmark_return = ((benchmark_nav_end / benchmark_nav_start) - 1) if benchmark_nav_start and benchmark_nav_end else 0

        avg_equity = sum(s.equity_ratio for s in self.daily_snapshots) / len(self.daily_snapshots)

        # R 分布统计
        r_dist = analyze_r_distribution(self.r_history) if self.r_history else {}

        env_distribution = {}
        for s in self.daily_snapshots:
            env_distribution[s.market_mode] = env_distribution.get(s.market_mode, 0) + 1

        # ============ A/B 对比 5 指标 ============

        # 1. 月胜率
        monthly_returns = {}
        for snap in self.daily_snapshots:
            if snap.daily_return == 0:
                continue
            mk = snap.trade_date.strftime("%Y-%m")
            monthly_returns.setdefault(mk, []).append(snap.daily_return)
        monthly_cum = {}
        for mk, rets in monthly_returns.items():
            cum = 1.0
            for r in rets:
                cum *= (1 + r)
            monthly_cum[mk] = cum - 1
        win_months = sum(1 for v in monthly_cum.values() if v > 0)
        month_win_rate = win_months / len(monthly_cum) if monthly_cum else 0

        # 2. 盈亏比
        profit_loss_ratio = 0.0
        if r_dist.get("avg_win") and r_dist.get("avg_loss") and r_dist["avg_loss"] != 0:
            profit_loss_ratio = abs(r_dist["avg_win"] / r_dist["avg_loss"])

        # 3/4. 上下行捕获率
        bench_prices = self.nav_data.get(self.benchmark_code, [])
        bench_daily = {}
        for j in range(1, len(bench_prices)):
            d_prev, nav_prev = bench_prices[j - 1]
            d_curr, nav_curr = bench_prices[j]
            if nav_prev > 0:
                bench_daily[d_curr] = (nav_curr - nav_prev) / nav_prev

        up_strat, up_bench = [], []
        down_strat, down_bench = [], []
        for snap in self.daily_snapshots:
            if snap.daily_return == 0:
                continue
            br = bench_daily.get(snap.trade_date)
            if br is None:
                continue
            if br > 0:
                up_strat.append(snap.daily_return)
                up_bench.append(br)
            elif br < 0:
                down_strat.append(snap.daily_return)
                down_bench.append(br)

        up_capture = (sum(up_strat) / len(up_strat)) / (sum(up_bench) / len(up_bench)) if up_bench else 0
        down_capture = (sum(down_strat) / len(down_strat)) / (sum(down_bench) / len(down_bench)) if down_bench else 0

        # 5. 凸性暂停触发频率
        convexity_pause_days = env_distribution.get("convexity_pause", 0)
        total_trading_days = max(1, len(self.daily_snapshots) - 80)
        convexity_pause_freq = convexity_pause_days / total_trading_days

        return {
            "engine": "Fused",
            "period": f"{self.start_date} ~ {self.end_date}",
            "trading_days": trading_days,
            "total_return": f"{total_return*100:.2f}%",
            "annualized_return": f"{annualized_return*100:.2f}%",
            "max_drawdown": f"{max_dd*100:.2f}%",
            "max_dd_period": f"{dd_start} ~ {dd_end}",
            "sharpe_ratio": round(sharpe, 4),
            "calmar_ratio": round(calmar, 4),
            "volatility": f"{volatility*100:.2f}%",
            "win_rate": f"{win_rate*100:.1f}%",
            "total_trades": len(self.trade_log),
            "total_fees": round(self.total_fees, 2),
            "final_balance": round(final_assets, 2),
            "benchmark_return": f"{benchmark_return*100:.2f}%",
            "excess_return": f"{(total_return - benchmark_return)*100:.2f}%",
            "avg_equity_ratio": f"{avg_equity*100:.1f}%",
            "env_distribution": env_distribution,
            "r_distribution": r_dist,
            "ab_metrics": {
                "month_win_rate": f"{month_win_rate*100:.1f}%",
                "profit_loss_ratio": round(profit_loss_ratio, 2),
                "upside_capture": f"{up_capture*100:.1f}%",
                "downside_capture": f"{down_capture*100:.1f}%",
                "convexity_pause_freq": f"{convexity_pause_freq*100:.1f}%",
            },
            "equity_curve": [
                {"date": s.trade_date.isoformat(), "assets": round(s.total_assets, 2),
                 "equity_pct": round(s.equity_ratio * 100, 1), "mode": s.market_mode}
                for s in self.daily_snapshots[::5]
            ],
            "trades": [
                {"date": t.trade_date.isoformat(), "code": t.code, "name": t.name,
                 "sector": t.sector, "action": t.action, "amount": round(t.amount, 2),
                 "nav": t.nav, "fee": round(t.fee, 2), "reason": t.reason}
                for t in self.trade_log[-50:]
            ],
        }


def run_backtest_fused(db: Session, start_date: date, end_date: date) -> dict:
    engine = BacktestEngineFused(db, start_date, end_date)
    return engine.run()
