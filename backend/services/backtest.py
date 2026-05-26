"""回测引擎 V4：均线交叉 + 趋势确认 + 逐笔止损"""
import math
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import asc
from models import FundNav, Fund
from services.calculator import calculate_rsi
from constants import (
    FUND_SECTOR, INITIAL_BALANCE, MAX_POSITION_VALUE, MIN_CASH_RESERVE,
    STOP_LOSS, TRAILING_TRIGGER, TRAILING_DRAWDOWN,
    BUY_FEE, SELL_FEE_SHORT, SELL_FEE_LONG, SELL_FEE_YEAR,
)


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
