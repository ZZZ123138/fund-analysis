import os
import re
import asyncio
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
from datetime import date, datetime
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import asc, func
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import engine, get_db, Base
from models import Fund, FundNav, FundReport, VirtualAccount, VirtualTrade, WatchlistFund, NotificationConfig, SystemState, StrategyState, TradeRecord, RiskState
from constants import (
    FUND_SECTOR, FUND_UNIVERSE, INITIAL_BALANCE, MAX_POSITION_VALUE, MIN_CASH_RESERVE,
    STOP_LOSS, TRAILING_TRIGGER, TRAILING_DRAWDOWN,
    ATR_PERIOD_SHORT, HARD_STOP_ATR_MULTIPLE, TRAILING_STOP_ATR_MULTIPLE, RISK_PER_TRADE_PCT,
    ASSET_CLASS, ASSET_CLASS_MAX_PCT, ASSET_CLASS_CORRELATION,
    DAILY_PURCHASE_LIMIT, SUSPENDED_FUNDS, QDII_FUNDS,
)
from services.environment import sense_environment, analyze_dual_cycle
from services.strategy import TrendStrategy, OscillationStrategy, BreakoutStrategy
from services.position import calculate_position_size
from services.exit_manager import ExitManager
from services.risk_manager import (
    update_risk_state, check_circuit_breaker,
    analyze_r_distribution, get_position_scale_from_r,
)
from schemas import FundInfo, FundMetrics, NavPoint, FundReportData, ReportRequest, PortfolioInit, PortfolioBuy, PortfolioSell, WatchlistItem, WatchlistUpdate, NotificationSettings
from services.fund_data import fetch_fund_nav
from services.calculator import (
    calculate_metrics,
    calculate_cycle_strength,
    calculate_annual_return,
    calculate_rsi,
    calculate_atr,
    calculate_industry_score,
    calculate_correlation,
    calculate_crowding_score,
    calculate_davis_score,
    calculate_style_preference,
    get_merrill_clock_stage,
    infer_fund_type,
)
from services.report import generate_html_report

Base.metadata.create_all(bind=engine)

# 定时任务调度器
scheduler = AsyncIOScheduler()

FUND_CODE_RE = re.compile(r"^\d{6}$")


def validate_fund_code(code: str) -> str:
    if not FUND_CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="基金代码必须为6位数字")
    return code


# ==================== T+1 份额确认逻辑 ====================

_HOLIDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 21),
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 31), date(2026, 6, 1), date(2026, 6, 2),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
}


def _is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in _HOLIDAYS_2026


def _next_trading_day(d: date, after_15: bool = False) -> date:
    """返回确认日期：15:00前买入=T+1，15:00后买入=T+2"""
    from datetime import timedelta
    days = 2 if after_15 else 1
    nxt = d + timedelta(days=days)
    while not _is_trading_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def _auto_confirm_trades(db: Session):
    """自动将到期的 pending 交易转为 confirmed"""
    today = date.today()
    pending = db.query(VirtualTrade).filter(
        VirtualTrade.status == "pending",
        VirtualTrade.confirm_date <= today,
    ).all()
    for t in pending:
        t.status = "confirmed"
    # 同步 TradeRecord
    pending_records = db.query(TradeRecord).filter(
        TradeRecord.status == "pending",
        TradeRecord.confirm_date <= today,
    ).all()
    for r in pending_records:
        r.status = "confirmed"
    if pending or pending_records:
        db.commit()
        print(f"[{datetime.now()}] 自动确认 {len(pending)} 笔交易")


def _get_today_purchases(db: Session, fund_code: str) -> float:
    """获取某基金今日已申购总额（含 pending + confirmed）"""
    today = date.today()
    result = db.query(func.sum(VirtualTrade.amount)).filter(
        VirtualTrade.fund_code == fund_code,
        VirtualTrade.trade_type == "buy",
        VirtualTrade.trade_date >= today,
    ).scalar()
    return result or 0.0


def _check_suspended_funds() -> set:
    """自动检测暂停申购的 QDII 基金"""
    import requests
    suspended = set()
    for code in QDII_FUNDS:
        try:
            r = requests.get(f"https://fund.eastmoney.com/{code}.html", timeout=10)
            if "暂停申购" in r.text or "暂停大额申购" in r.text:
                suspended.add(code)
                print(f"  {code} 暂停申购")
        except Exception as e:
            print(f"⚠️ {code} 状态检查失败: {e}")
    return suspended


app = FastAPI(title="基金分析系统", version="1.0.0")


async def update_all_funds():
    """定时任务：更新所有基金数据"""
    if not _is_trading_day(date.today()):
        print(f"[{datetime.now()}] 非交易日，跳过基金数据更新")
        return
    print(f"[{datetime.now()}] 开始定时更新基金数据...")
    from database import SessionLocal
    db = SessionLocal()
    try:
        funds = db.query(Fund).all()
        for fund in funds:
            try:
                await fetch_fund_nav(fund.code, db)
                print(f"  更新基金 {fund.code} ({fund.name}) 成功")
            except Exception as e:
                print(f"  更新基金 {fund.code} 失败: {e}")
        print(f"[{datetime.now()}] 基金数据更新完成")
    finally:
        db.close()


async def ai_daily_analysis(db) -> str:
    """用 DeepSeek AI 生成每日策略分析报告"""
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        return ""

    try:
        # 收集今日交易数据
        today = date.today()
        all_trades = db.query(VirtualTrade).filter(VirtualTrade.trade_date >= today).all()
        account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
        if not account:
            return ""

        # 计算持仓和收益（只计已确认交易）
        all_trades_all = db.query(VirtualTrade).all()
        net_shares = {}
        cost_map = {}
        for t in all_trades_all:
            if t.trade_type == "buy" and t.status == "pending":
                continue
            if t.trade_type == "buy":
                net_shares[t.fund_code] = net_shares.get(t.fund_code, 0) + t.shares
                cost_map[t.fund_code] = cost_map.get(t.fund_code, 0) + t.amount
            else:
                if t.fund_code in net_shares and net_shares[t.fund_code] > 0:
                    ratio = t.shares / (net_shares[t.fund_code] + t.shares) if (net_shares[t.fund_code] + t.shares) > 0 else 0
                    cost_map[t.fund_code] = cost_map.get(t.fund_code, 0) * (1 - ratio)
                net_shares[t.fund_code] = net_shares.get(t.fund_code, 0) - t.shares

        holdings_val = 0
        fund_pnl = {}
        for fc, ns in net_shares.items():
            if ns > 0.0001:
                nav_row = db.query(FundNav.nav).filter(FundNav.fund_code == fc).order_by(FundNav.date.desc()).first()
                if nav_row:
                    val = ns * nav_row[0]
                    holdings_val += val
                    cost = cost_map.get(fc, val)
                    pnl = (val - cost) / cost * 100 if cost > 0 else 0
                    fund = db.query(Fund).filter(Fund.code == fc).first()
                    fund_pnl[fc] = {
                        "name": fund.name if fund else fc,
                        "pnl": round(pnl, 2),
                        "value": round(val, 0),
                    }

        total_assets = holdings_val + account.balance
        equity_ratio = holdings_val / total_assets * 100 if total_assets > 0 else 0
        total_return = (total_assets - 100000) / 100000 * 100

        # 找最大贡献和最大拖累
        if fund_pnl:
            best = max(fund_pnl.values(), key=lambda x: x["pnl"])
            worst = min(fund_pnl.values(), key=lambda x: x["pnl"])
        else:
            best = worst = {"name": "无", "pnl": 0}

        # 今日交易统计
        buys = [t for t in all_trades if t.trade_type == "buy"]
        sells = [t for t in all_trades if t.trade_type != "buy"]

        # 构造 prompt
        prompt = f"""今日收益{total_return:+.2f}%，{best['name']}贡献最大（{best['pnl']:+.2f}%）、{worst['name']}拖累（{worst['pnl']:+.2f}%），持仓比例{equity_ratio:.0f}%，余额{account.balance:,.0f}元，今日买入{len(buys)}笔卖出{len(sells)}笔。

请分析：
1. 当前策略最脆弱的环节是什么？
2. 明日必须遵守的3条操作纪律

要求：简洁直接，每条不超过30字，用中文回答。"""

        # 调用 DeepSeek API
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "你是一个专业的量化基金交易策略分析师。回答要简洁、直接、有操作性。"},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            if data.get("choices"):
                return data["choices"][0]["message"]["content"]
            return ""
    except Exception as e:
        print(f"[AI] 分析异常: {e}")
        return ""


async def fetch_us_market() -> dict:
    """获取美股三大指数 + A股主要指数 + 恒生指数 via 新浪财经"""
    result = {}
    symbols = {
        "gb_dji": "道琼斯", "gb_ixic": "纳斯达克", "gb_inx": "标普500",
        "sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指",
        "rt_hkHSI": "恒生指数",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://hq.sinajs.cn/list={','.join(symbols.keys())}",
                headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
            )
            text = resp.text
            for line in text.strip().split("\n"):
                if "=" not in line or '""' in line:
                    continue
                var_part, val_part = line.split("=", 1)
                val = val_part.strip().strip('";')
                if not val:
                    continue
                fields = val.split(",")
                # 提取 key
                key = var_part.split("_")[-1]
                symbol = key if not var_part.startswith("var hq_str_") else var_part.replace("var hq_str_", "")

                if symbol in ("gb_dji", "gb_ixic", "gb_inx"):
                    # 美股: name,price,pct,...,change,...
                    name_raw = fields[0]
                    price = float(fields[1]) if fields[1] else 0
                    pct = float(fields[2]) if fields[2] else 0
                    change = float(fields[4]) if len(fields) > 4 and fields[4] else 0
                    if "道琼斯" in name_raw:
                        result["道琼斯"] = {"price": price, "change": change, "pct": pct}
                    elif "纳斯达克" in name_raw:
                        result["纳斯达克"] = {"price": price, "change": change, "pct": pct}
                    elif "标普" in name_raw:
                        result["标普500"] = {"price": price, "change": change, "pct": pct}
                elif symbol in ("sh000001", "sz399001", "sz399006"):
                    # A股: name,open,prev_close,price,high,low,...
                    name_raw = fields[0]
                    prev_close = float(fields[2]) if fields[2] else 0
                    price = float(fields[3]) if fields[3] else 0
                    pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    label = symbols.get(symbol, symbol)
                    result[label] = {"price": price, "change": price - prev_close, "pct": round(pct, 2)}
                elif "HSI" in symbol:
                    # 恒生: code,name,prev_close,price,...
                    prev_close = float(fields[2]) if len(fields) > 2 and fields[2] else 0
                    price = float(fields[3]) if len(fields) > 3 and fields[3] else 0
                    pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    result["恒生指数"] = {"price": price, "change": price - prev_close, "pct": round(pct, 2)}
    except Exception as e:
        result["error"] = str(e)
    return result


async def pre_market_analysis():
    """盘前分析：美股隔夜行情 + A股影响预判"""
    if not _is_trading_day(date.today()):
        print(f"[{datetime.now()}] 非交易日，跳过盘前分析")
        return
    from database import SessionLocal
    db = SessionLocal()
    try:
        config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
        if not config or not config.enabled or not config.serverchan_key:
            return

        now = datetime.now()

        # 获取美股数据
        us_market = await fetch_us_market()
        sp500 = us_market.get("标普500", {})
        nasdaq = us_market.get("纳斯达克", {})
        dow = us_market.get("道琼斯", {})

        if sp500.get("pct", 0) == 0 and nasdaq.get("pct", 0) == 0:
            print(f"[{now}] 盘前分析: 美股数据获取失败，跳过")
            return

        # 获取 A 股和港股数据
        sh_index = us_market.get("上证指数", {})
        sz_index = us_market.get("深证成指", {})
        cy_index = us_market.get("创业板指", {})
        hsi_index = us_market.get("恒生指数", {})

        # 判断市场信号
        avg_pct = (sp500.get("pct", 0) + nasdaq.get("pct", 0) + dow.get("pct", 0)) / 3
        if avg_pct > 1.0:
            signal = "偏多"
            signal_icon = "  "
        elif avg_pct > 0.3:
            signal_icon = "  "
            signal = "略偏多"
        elif avg_pct < -1.0:
            signal = "偏空"
            signal_icon = "  "
        elif avg_pct < -0.3:
            signal = "略偏空"
            signal_icon = "  "
        else:
            signal = "中性"
            signal_icon = "  "

        # 加载持仓（只计已确认交易）
        _auto_confirm_trades(db)
        all_trades = db.query(VirtualTrade).all()
        net_shares_map = {}
        for t in all_trades:
            if t.trade_type == "buy" and t.status == "pending":
                continue
            sign = 1 if t.trade_type == "buy" else -1
            net_shares_map[t.fund_code] = net_shares_map.get(t.fund_code, 0) + t.shares * sign

        held_funds = []
        for fc, ns in net_shares_map.items():
            if ns > 0.0001:
                fund = db.query(Fund).filter(Fund.code == fc).first()
                held_funds.append({
                    "code": fc,
                    "name": fund.name if fund else fc,
                    "sector": FUND_SECTOR.get(fc, "其他"),
                    "shares": ns,
                })

        # 分析持仓影响
        sector_impact = {
            "科技": nasdaq.get("pct", 0) * 0.8,
            "新能源": nasdaq.get("pct", 0) * 0.6,
            "宽基": sp500.get("pct", 0) * 0.5,
            "消费": sp500.get("pct", 0) * 0.3,
            "白酒": sp500.get("pct", 0) * 0.3,
            "医疗": sp500.get("pct", 0) * 0.2,
            "军工": sp500.get("pct", 0) * 0.15,
        }

        # 生成建议
        if avg_pct > 1.5:
            advice = "持仓观望，高开不追涨。如果持仓基金高开超2%，注意止盈。"
        elif avg_pct > 0.5:
            advice = "可继续持有，观察开盘表现再决定。"
        elif avg_pct < -1.5:
            advice = "谨慎观望，如果低开超2%，优质基金可考虑逢低补仓。"
        elif avg_pct < -0.5:
            advice = "影响有限，正常操作即可。"
        else:
            advice = "美股波动小，按原计划操作。"

        # 构建报告
        lines = [f"##   盘前分析 ({now.strftime('%H:%M')})\n"]

        lines.append("**美股隔夜：**")
        for name in ["标普500", "纳斯达克", "道琼斯"]:
            d = us_market.get(name, {})
            pct = d.get("pct", 0)
            icon = "  " if pct > 0 else ("  " if pct < 0 else "  ")
            lines.append(f"- {icon} {name}: {d.get('price', 0):,.2f} ({pct:+.2f}%)")

        # A 股主要指数（如果有数据）
        if sh_index or sz_index or cy_index:
            lines.append("\n**A股/港股：**")
            for name, data in [("上证指数", sh_index), ("深证成指", sz_index), ("创业板指", cy_index), ("恒生指数", hsi_index)]:
                if data and data.get("price", 0) > 0:
                    pct = data.get("pct", 0)
                    icon = "  " if pct > 0 else ("  " if pct < 0 else "  ")
                    lines.append(f"- {icon} {name}: {data['price']:,.2f} ({pct:+.2f}%)")

        lines.append(f"\n**市场信号**: {signal_icon} {signal} (美股均值 {avg_pct:+.2f}%)")

        if held_funds:
            lines.append("\n**持仓影响预估：**")
            for hf in held_funds:
                impact = sector_impact.get(hf["sector"], avg_pct * 0.3)
                icon = "  " if impact > 0.3 else ("  " if impact < -0.3 else "  ")
                lines.append(f"- {icon} {hf['name']}({hf['sector']}): 预计{'高开' if impact > 0 else '低开'} {abs(impact):.1f}%")

        lines.append(f"\n**今日建议**: {advice}")

        title = f"盘前分析 {signal} {avg_pct:+.2f}%"
        content = "\n".join(lines)
        await send_serverchan(config.serverchan_key, title, content)
        print(f"[{now}] 盘前分析: {signal} {avg_pct:+.2f}%")
    finally:
        db.close()


async def send_serverchan(key: str, title: str, content: str):
    """通过 Server酱 推送消息到微信"""
    url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, data={"title": title, "desp": content})
            result = resp.json()
            if result.get("code") == 0:
                print(f"  Server酱推送成功: {title}")
            else:
                print(f"  Server酱推送失败: {result}")
            return result
    except Exception as e:
        print(f"  Server酱推送异常: {e}")
        return {"code": -1, "message": str(e)}


async def market_monitor():
    """AI 自主交易：V5 信号 + V6 风控（ATR 止损/环境仓位/熔断）"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
        if not config or not config.enabled or not config.serverchan_key:
            return

        now = datetime.now()
        today = date.today()

        # 硬约束：14:55后禁止下单（留5分钟缓冲）
        from constants import ORDER_CUTOFF_HOUR, ORDER_CUTOFF_MINUTE, MIN_HOLD_DAYS_FOR_SELL, QDII_FUNDS, QDII_NAV_DELAY_DAYS
        if now.hour > ORDER_CUTOFF_HOUR or (now.hour == ORDER_CUTOFF_HOUR and now.minute >= ORDER_CUTOFF_MINUTE):
            print(f"[{now}] 14:55后禁止下单，跳过扫描")
            db.close()
            return

        # 优化1：中国股市节假日检测（跳过非交易日）
        if not _is_trading_day(today):
            print(f"[{now}] 非交易日，跳过扫描")
            db.close()
            return

        # 自动确认到期的 pending 交易
        _auto_confirm_trades(db)

        # 确保数据存在
        for code in FUND_UNIVERSE:
            fund = db.query(Fund).filter(Fund.code == code).first()
            if not fund:
                try:
                    await fetch_fund_nav(code, db)
                except Exception:
                    pass

        account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
        if not account:
            account = VirtualAccount(id=1, balance=100000.0)
            db.add(account)
            db.commit()

        # 加载价格数据
        all_prices_map, fund_names = _load_price_data(db, FUND_UNIVERSE)

        # 数据校验：确保数据完整可用
        data_ok = True
        issues = []
        if len(all_prices_map) < 5:
            data_ok = False
            issues.append(f"可用基金仅{len(all_prices_map)}只，不足")
        benchmark_prices = all_prices_map.get("000961", [])
        if len(benchmark_prices) < 60:
            data_ok = False
            issues.append(f"基准000961数据仅{len(benchmark_prices)}条，不足60")
        # 检查数据新鲜度：基准最新数据应在2天内
        if benchmark_prices:
            from models import FundNav as FN
            latest_nav = db.query(FN.date).filter(FN.fund_code == "000961").order_by(FN.date.desc()).first()
            if latest_nav:
                data_age = (today - latest_nav.date).days
                if data_age > 2:
                    data_ok = False
                    issues.append(f"基准数据已过期{data_age}天")
        if not data_ok:
            msg = "数据校验失败: " + "; ".join(issues)
            print(f"[{now}] {msg}")
            await send_serverchan(config.serverchan_key, "⚠️ 扫描跳过", msg)
            db.close()
            return

        # 执行层熔断检查：行为异常时停止交易
        from services.evolution import check_execution_circuit_breaker
        cb_status = check_execution_circuit_breaker()
        if cb_status["halted"]:
            msg = f"执行层熔断: {cb_status['reason']}"
            print(f"[{now}] {msg}")
            await send_serverchan(config.serverchan_key, "   执行层熔断", msg)
            db.close()
            return

        # ==================== QDII 暂停申购自动检测（每天一次） ====================
        suspension_key = f"suspended_{today}"
        cached = db.query(SystemState).filter(SystemState.key == suspension_key).first()
        if cached:
            dynamic_suspended = set(cached.value.split(",")) if cached.value else set()
            # 检查之前暂停的基金是否恢复了
            for code in list(dynamic_suspended):
                if code in SUSPENDED_FUNDS:
                    continue  # 静态配置的不检查恢复
                try:
                    import requests
                    r = requests.get(f"https://fund.eastmoney.com/{code}.html", timeout=10)
                    if "暂停申购" not in r.text and "暂停大额申购" not in r.text:
                        dynamic_suspended.discard(code)
                        print(f"[{now}]   {code} 恢复申购")
                        await send_serverchan(config.serverchan_key,
                            "  QDII恢复申购",
                            f"{code} 已恢复申购，可重新参与买入")
                        # 更新缓存
                        cached.value = ",".join(dynamic_suspended)
                        db.commit()
                except Exception:
                    pass
        else:
            dynamic_suspended = _check_suspended_funds()
            # 合并静态配置 + 动态检测
            all_suspended = SUSPENDED_FUNDS | dynamic_suspended
            db.add(SystemState(key=suspension_key, value=",".join(all_suspended)))
            db.commit()
            new_suspended = dynamic_suspended - SUSPENDED_FUNDS
            if new_suspended:
                print(f"[{now}] 发现新暂停基金: {new_suspended}")
                await send_serverchan(config.serverchan_key,
                    "⚠️ QDII暂停申购",
                    f"新发现暂停申购基金: {', '.join(new_suspended)}\n已自动跳过这些基金的买入")
            dynamic_suspended = all_suspended
        # 用动态结果替换静态集合（模块级变量不可变，用局部变量覆盖）
        active_suspended = dynamic_suspended

        # 优化2：QDII品种标记（净值T+2延迟，信号容忍2天滞后）
        qdii_stale = {}
        for code in QDII_FUNDS:
            if code in all_prices_map and len(all_prices_map[code]) >= 3:
                # QDII最新净值可能是T-2的，记录提醒
                qdii_stale[code] = True

        # ==================== 环境感知 ====================
        benchmark_code = "000961"
        benchmark_prices = all_prices_map.get(benchmark_code, [])
        env_coeff = 1.0
        env_label = "unknown"
        if len(benchmark_prices) >= 80:
            env_result = sense_environment(benchmark_prices)
            env_coeff = env_result.position_coeff
            env_label = env_result.environment.value
            # 保存环境快照
            existing_state = db.query(StrategyState).filter(StrategyState.state_date == today).first()
            if not existing_state:
                db.add(StrategyState(
                    state_date=today,
                    vol_state=env_result.vol_state.value,
                    trend_state=env_result.trend_state.value,
                    environment=env_result.environment.value,
                    atr_20=env_result.atr_20, atr_60=env_result.atr_60,
                    adx=env_result.adx,
                    plus_di=env_result.plus_di, minus_di=env_result.minus_di,
                    active_strategy=env_result.strategy,
                    environment_coeff=env_result.position_coeff,
                ))
                db.flush()

        # 市场模式判断（兼容旧逻辑）
        if len(benchmark_prices) >= 60:
            ma20_b = sum(benchmark_prices[-20:]) / 20
            ma60_b = sum(benchmark_prices[-60:]) / 60
            close_b = benchmark_prices[-1]
            market_mode = "trend" if (ma20_b > ma60_b and close_b > ma20_b) else "oscillation"
        else:
            market_mode = "oscillation"

        max_equity_ratio = 0.80 if market_mode == "trend" else 0.50

        # ==================== 风控：熔断检查 ====================
        net_shares_map, cost_basis_map, held_funds = _compute_holdings(db)
        holdings_value = 0
        for fc in held_funds:
            holdings_value += net_shares_map[fc] * all_prices_map[fc][-1]
        total_assets = holdings_value + account.balance

        risk_state = update_risk_state(
            db, today, daily_pnl=0, daily_pnl_pct=0,
            total_assets=total_assets, initial_balance=INITIAL_BALANCE,
            strategy_name=market_mode,
        )
        cb = check_circuit_breaker(risk_state)
        if not cb["allowed"]:
            print(f"[{now}] 熔断: {cb['reason']}")
            db.commit()
            return
        position_scale = cb.get("position_scale", 1.0)

        trades_done = []

        # ==================== 止损 / 止盈（V6: ATR 自适应） ====================
        state_rows = db.query(SystemState).filter(
            SystemState.key.like("highest_nav_%") | SystemState.key.like("ma_state_%")
        ).all()
        state_map = {s.key: s.value for s in state_rows}

        for code in held_funds:
            if code not in all_prices_map:
                continue
            prices = all_prices_map[code]
            nav = prices[-1]
            ns = net_shares_map.get(code, 0)
            if ns <= 0.0001:
                continue

            avg_cost = cost_basis_map.get(code, 0) / ns if ns > 0 else nav
            pnl_pct = (nav - avg_cost) / avg_cost if avg_cost > 0 else 0
            rsi = calculate_rsi(prices)
            atr = calculate_atr(prices, ATR_PERIOD_SHORT)

            # 移动止盈：追踪最高净值
            hn_key = f"highest_nav_{code}"
            prev_highest = float(state_map.get(hn_key, nav))
            current_highest = max(prev_highest, nav)
            hn_row = db.query(SystemState).filter(SystemState.key == hn_key).first()
            if hn_row:
                hn_row.value = str(current_highest)
            else:
                db.add(SystemState(key=hn_key, value=str(current_highest)))

            # 均线死叉检测
            ma_key = f"ma_state_{code}"
            prev_ma = state_map.get(ma_key, "below")
            if len(prices) >= 20:
                ma20 = sum(prices[-20:]) / 20
                cur_ma = "above" if nav > ma20 else "below"
            else:
                cur_ma = "below"
            ms_row = db.query(SystemState).filter(SystemState.key == ma_key).first()
            if ms_row:
                ms_row.value = cur_ma
            else:
                db.add(SystemState(key=ma_key, value=cur_ma))

            should_sell = False
            sell_ratio_val = 0.0
            reason = ""

            # 硬约束：持有不足7天禁止赎回
            latest_buy = db.query(VirtualTrade).filter(
                VirtualTrade.fund_code == code,
                VirtualTrade.trade_type == "buy",
            ).order_by(VirtualTrade.trade_date.desc()).first()
            if latest_buy:
                days_held = (now - latest_buy.trade_date).days
                if days_held < MIN_HOLD_DAYS_FOR_SELL:
                    print(f"[{now}] {code} 持有{days_held}天 < 7天，禁止赎回")
                    continue

            # 1. ATR 硬止损：入场价 - 2*ATR（替代固定 -7%）
            atr_stop_price = avg_cost - HARD_STOP_ATR_MULTIPLE * atr
            if nav <= atr_stop_price:
                should_sell, sell_ratio_val = True, 1.0
                reason = f"ATR止损 {pnl_pct*100:.1f}% (止损价={atr_stop_price:.4f})"
            # 2. ATR 移动止盈：从高点回落 1.5*ATR（替代固定 5%/3%）
            elif current_highest > avg_cost and atr > 0:
                trailing_stop_price = current_highest - TRAILING_STOP_ATR_MULTIPLE * atr
                if nav <= trailing_stop_price:
                    should_sell, sell_ratio_val = True, 1.0
                    reason = f"ATR止盈 {pnl_pct*100:.1f}% 从高点回落1.5ATR"
            # 3. RSI 超买
            elif rsi > 72:
                should_sell, sell_ratio_val = True, 1.0
                reason = f"RSI={rsi:.0f} 超买"
            # 4. 均线死叉：跌破 20MA 且持仓盈利
            elif cur_ma == "below" and prev_ma == "above" and pnl_pct > 0:
                should_sell, sell_ratio_val = True, 1.0
                reason = f"跌破20MA 盈利{pnl_pct*100:.1f}%"
            # 5. 持仓老化：持有>30天且收益<3%，释放资金
            elif days_held > 30 and pnl_pct < 0.03:
                should_sell, sell_ratio_val = True, 0.5
                reason = f"持仓老化 {days_held}天 收益仅{pnl_pct*100:.1f}%"

            if should_sell:
                sell_shares = ns * sell_ratio_val
                sell_amount = sell_shares * nav
                account.balance += sell_amount
                trade = VirtualTrade(
                    fund_code=code, fund_name=fund_names.get(code, code),
                    trade_type="sell", shares=sell_shares,
                    nav=nav, amount=sell_amount,
                    status="confirmed",
                )
                db.add(trade)
                db.add(TradeRecord(
                    fund_code=code, fund_name=fund_names.get(code, code),
                    trade_type="sell", shares=sell_shares,
                    nav=nav, amount=sell_amount,
                    status="confirmed",
                    strategy_name=market_mode, environment=env_label,
                    exit_reason="stop" if "止损" in reason else "other",
                ))
                trades_done.append({
                    "name": fund_names.get(code, code), "code": code,
                    "sector": FUND_SECTOR.get(code, "其他"),
                    "asset_class": ASSET_CLASS.get(code, "A股"),
                    "action": "卖出", "amount": round(sell_amount, 2),
                    "nav": nav, "reason": reason,
                })
                net_shares_map[code] -= sell_shares

        # ==================== 定投：每月第一次扫描，全球资产分散 ====================
        dca_key = f"dca_{now.strftime('%Y-%m')}"
        already_dca = db.query(SystemState).filter(SystemState.key == dca_key).first()

        dca_done = False
        if not already_dca and now.day <= 5:
            # 全球分散定投：A股宽基 + 商品 + 美股 + 港股 + 新兴市场
            dca_sectors = [
                ("宽基", 4000),        # A股宽基
                ("商品", 2000),        # 黄金/商品对冲
                ("美股", 3000),        # 标普500/纳斯达克
                ("港股", 2000),        # 港股
                ("新兴市场", 2000),    # 印度/越南
            ]
            for sector, max_amount in dca_sectors:
                dca_funds = [c for c in FUND_UNIVERSE if FUND_SECTOR.get(c) == sector and c in all_prices_map and c not in active_suspended]
                for code in dca_funds:
                    available = account.balance - MIN_CASH_RESERVE
                    if available < 2000:
                        break
                    ns = net_shares_map.get(code, 0)
                    current_value = ns * all_prices_map[code][-1] if ns > 0 else 0
                    if current_value >= MAX_POSITION_VALUE:
                        continue
                    nav = all_prices_map[code][-1]
                    buy_amount = min(max_amount, available)
                    # QDII 每日申购限额
                    daily_limit = DAILY_PURCHASE_LIMIT.get(code, 0)
                    if daily_limit > 0:
                        today_bought = _get_today_purchases(db, code)
                        remaining = daily_limit - today_bought
                        if remaining <= 0:
                            continue
                        buy_amount = min(buy_amount, remaining)
                    if buy_amount >= 2000:
                        shares = buy_amount / nav
                        account.balance -= buy_amount
                        after_15 = datetime.now().hour >= 15
                        confirm_dt = _next_trading_day(today, after_15)
                        trade = VirtualTrade(
                            fund_code=code, fund_name=fund_names.get(code, code),
                            trade_type="buy", trade_label="定投", shares=shares,
                            nav=nav, amount=buy_amount,
                            status="pending", confirm_date=confirm_dt,
                        )
                        db.add(trade)
                        trades_done.append({
                            "name": fund_names.get(code, code), "code": code,
                            "sector": sector,
                            "asset_class": ASSET_CLASS.get(code, "A股"),
                            "action": "定投",
                            "amount": round(buy_amount, 2), "nav": nav,
                            "reason": f"月度定投 {now.strftime('%Y-%m')}（T+1确认）",
                        })
                        dca_done = True
            if dca_done:
                db.add(SystemState(key=dca_key, value=now.isoformat()))
                db.flush()

        # ==================== R 分布 + 凸性检查 ====================
        from models import TradeRecord as TRModel
        recent_trades = db.query(TRModel.r_multiple).filter(
            TRModel.r_multiple.isnot(None)
        ).order_by(TRModel.trade_date.desc()).limit(50).all()
        r_values = [t.r_multiple for t in recent_trades if t.r_multiple is not None]
        r_scale = get_position_scale_from_r(r_values)
        r_dist = analyze_r_distribution(r_values) if r_values else None

        if r_scale == 0:
            print(f"[{now}] 凸性暂停：策略收益分布呈凹性，暂停开仓")
            db.commit()
            if trades_done:
                title = f"AI交易：{len(trades_done)}笔 凸性暂停"
                content = f"## AI交易报告\n\n**R分布**: {r_dist['verdict'] if r_dist else '无数据'}\n\n卖出 {len(trades_done)} 笔已完成"
                await send_serverchan(config.serverchan_key, title, content)
            return

        # ==================== 优化3：板块相对强度排名 ====================
        sector_momentum = {}
        for code in FUND_UNIVERSE:
            if code not in all_prices_map:
                continue
            prices = all_prices_map[code]
            if len(prices) >= 20:
                mom = (prices[-1] - prices[-20]) / prices[-20]  # 20日动量
                sector = FUND_SECTOR.get(code, "其他")
                if sector not in sector_momentum:
                    sector_momentum[sector] = []
                sector_momentum[sector].append(mom)
        # 计算板块平均动量并排名
        sector_rank = {}
        for sector, moms in sector_momentum.items():
            sector_rank[sector] = sum(moms) / len(moms)
        sorted_sectors = sorted(sector_rank.items(), key=lambda x: x[1], reverse=True)
        if sorted_sectors:
            print(f"[{now}] 板块强度: {', '.join(f'{s}={m*100:.1f}%' for s, m in sorted_sectors)}")

        # 市场宽度：站上20日均线的比例
        above_ma20 = 0
        total_with_ma = 0
        for code in FUND_UNIVERSE:
            if code in all_prices_map and len(all_prices_map[code]) >= 20:
                total_with_ma += 1
                if all_prices_map[code][-1] > sum(all_prices_map[code][-20:]) / 20:
                    above_ma20 += 1
        breadth_pct = above_ma20 / total_with_ma * 100 if total_with_ma > 0 else 0
        print(f"[{now}] 市场宽度: {above_ma20}/{total_with_ma} ({breadth_pct:.0f}%) 站上MA20")

        # ==================== 战术买入（V5 信号 + V6 仓位 + 双周期矩阵） ====================
        if market_mode == "trend":
            holdings_value = 0
            for fc, ns in net_shares_map.items():
                if ns > 0.0001 and fc in all_prices_map:
                    holdings_value += ns * all_prices_map[fc][-1]
            total_assets = holdings_value + account.balance

            buy_candidates = []
            for code in FUND_UNIVERSE:
                if code in active_suspended:
                    continue  # 暂停申购，跳过
                if code not in all_prices_map:
                    continue
                prices = all_prices_map[code]
                if len(prices) < 60:
                    continue

                close = prices[-1]
                ma20_val = sum(prices[-20:]) / 20
                ma60_val = sum(prices[-60:]) / 60
                rsi = calculate_rsi(prices)

                prev_close = prices[-2] if len(prices) >= 2 else close
                prev_ma20 = sum(prices[-21:-1]) / 20 if len(prices) >= 21 else ma20_val

                golden_cross = (close > ma20_val) and (prev_close <= prev_ma20)
                trend_buy = (close > ma20_val > ma60_val > 0 and 50 <= rsi <= 68)

                if not golden_cross and not trend_buy:
                    continue
                if rsi > 68:
                    continue

                # 双周期矩阵过滤：只在正期望单元格开仓
                dual = analyze_dual_cycle(prices)
                if dual.allowed_strategy == "none" and dual.cell_expectation == "negative":
                    continue  # 下跌趋势或无正期望，跳过

                ns = net_shares_map.get(code, 0)
                current_value = ns * close if ns > 0 else 0
                if current_value >= MAX_POSITION_VALUE:
                    continue

                # 仓位：ATR 风险平价 × 环境系数 × 熔断系数 × R分布系数
                atr = calculate_atr(prices, ATR_PERIOD_SHORT)
                risk_budget = total_assets * RISK_PER_TRADE_PCT
                atr_pct = atr / close if close > 0 else 0.01
                base_from_atr = risk_budget / atr_pct if atr_pct > 0 else 5000
                base = base_from_atr * env_coeff * position_scale * r_scale
                base = max(2000, min(8000, base))

                if current_value > 0:
                    remaining = MAX_POSITION_VALUE - current_value
                    if remaining <= 0:
                        continue
                    base = min(base, remaining)

                available_for_equity = total_assets * max_equity_ratio - holdings_value
                if available_for_equity <= 0:
                    break
                base = min(base, available_for_equity)

                available = account.balance - MIN_CASH_RESERVE
                buy_amount = min(base, available)

                if buy_amount >= 2000:
                    signal = "金叉" if golden_cross else "趋势"
                    # 板块集中度检查
                    sector = FUND_SECTOR.get(code, "其他")
                    sector_value = sum(
                        net_shares_map.get(c, 0) * all_prices_map[c][-1]
                        for c in FUND_UNIVERSE
                        if FUND_SECTOR.get(c) == sector and c in all_prices_map
                    )
                    if (sector_value + buy_amount) / total_assets > SECTOR_MAX_PCT:
                        continue  # 板块超限，跳过

                    # 资产类别集中度检查（全球分散化）
                    asset_class = ASSET_CLASS.get(code, "A股")
                    ac_group = ASSET_CLASS_CORRELATION.get(asset_class, asset_class)
                    ac_value = sum(
                        net_shares_map.get(c, 0) * all_prices_map[c][-1]
                        for c in FUND_UNIVERSE
                        if ASSET_CLASS_CORRELATION.get(ASSET_CLASS.get(c, "A股"), ASSET_CLASS.get(c, "A股")) == ac_group
                        and c in all_prices_map
                    )
                    if (ac_value + buy_amount) / total_assets > ASSET_CLASS_MAX_PCT:
                        continue  # 资产类别超限，跳过

                    # QDII 每日申购限额检查
                    daily_limit = DAILY_PURCHASE_LIMIT.get(code, 0)
                    if daily_limit > 0:
                        today_bought = _get_today_purchases(db, code)
                        remaining_limit = daily_limit - today_bought
                        if remaining_limit <= 0:
                            continue  # 今日已达限额，跳过
                        buy_amount = min(buy_amount, remaining_limit)
                        if buy_amount < 2000:
                            continue  # 限额太小，不值得买

                    buy_candidates.append({
                        "code": code, "amount": buy_amount,
                        "rsi": rsi, "signal": signal,
                        "dual": dual,
                    })

            buy_candidates.sort(key=lambda x: x["rsi"])
            after_15 = datetime.now().hour >= 15
            confirm_dt = _next_trading_day(today, after_15)
            for cand in buy_candidates:
                nav = all_prices_map[cand["code"]][-1]
                shares = cand["amount"] / nav
                account.balance -= cand["amount"]
                _label = "建仓" if net_shares_map.get(cand["code"], 0) <= 0 else "补仓"
                trade = VirtualTrade(
                    fund_code=cand["code"], fund_name=fund_names.get(cand["code"], cand["code"]),
                    trade_type="buy", trade_label=_label, shares=shares,
                    nav=nav, amount=cand["amount"],
                    status="pending", confirm_date=confirm_dt,
                )
                db.add(trade)
                dual = cand["dual"]
                db.add(TradeRecord(
                    fund_code=cand["code"],
                    fund_name=fund_names.get(cand["code"], cand["code"]),
                    trade_type="buy", trade_label=_label, shares=shares,
                    nav=nav, amount=cand["amount"],
                    status="pending", confirm_date=confirm_dt,
                    strategy_name=market_mode, environment=env_label,
                    initial_risk=calculate_atr(all_prices_map[cand["code"]], ATR_PERIOD_SHORT) * HARD_STOP_ATR_MULTIPLE,
                    position_size_rationale=f"长周期={dual.long_cycle.value} 短周期={dual.short_cycle.value} R缩放={r_scale:.1f}",
                ))
                trades_done.append({
                    "name": fund_names.get(cand["code"], cand["code"]),
                    "code": cand["code"],
                    "sector": FUND_SECTOR.get(cand["code"], "其他"),
                    "asset_class": ASSET_CLASS.get(cand["code"], "A股"),
                    "action": "建仓" if net_shares_map.get(cand["code"], 0) <= 0 else "补仓",
                    "amount": round(cand["amount"], 2), "nav": nav,
                    "reason": f"{cand['signal']} RSI={cand['rsi']:.0f} {dual.long_cycle.value}×{dual.short_cycle.value}（T+1确认）",
                })

        db.commit()

        # ==================== 推送结果 ====================
        # 计算持仓概况
        holdings_count = sum(1 for ns in net_shares_map.values() if ns > 0.0001)
        r_info = f" | **R期望**: {r_dist['expectation']:.2f} ({r_dist['health']})" if r_dist else ""

        # 优化4：绩效指标（胜率、平均R、板块强度、市场宽度）
        win_trades = [r for r in r_values if r > 0] if r_values else []
        loss_trades = [r for r in r_values if r <= 0] if r_values else []
        win_rate = len(win_trades) / len(r_values) * 100 if r_values else 0
        avg_r = sum(r_values) / len(r_values) if r_values else 0
        top_sector = sorted_sectors[0] if sorted_sectors else ("--", 0)
        breadth_label = "强" if breadth_pct >= 60 else "中" if breadth_pct >= 40 else "弱"

        if trades_done:
            lines = [f"## AI交易报告 ({now.strftime('%H:%M')})\n"]
            lines.append(
                f"**环境**: {env_label} | "
                f"**市场**: {'趋势' if market_mode=='trend' else '震荡'} | "
                f"**仓位系数**: {env_coeff}×{r_scale:.1f} | **余额**: ¥{account.balance:,.2f}{r_info}\n"
                f"**胜率**: {win_rate:.0f}% ({len(win_trades)}/{len(r_values)}) | "
                f"**均R**: {avg_r:.2f} | "
                f"**最强板块**: {top_sector[0]}({top_sector[1]*100:+.1f}%) | "
                f"**市场宽度**: {breadth_pct:.0f}%{breadth_label}"
            )

            buys = [t for t in trades_done if t["action"] in ("建仓", "补仓", "定投")]
            sells = [t for t in trades_done if t["action"] == "卖出"]
            if buys:
                lines.append(f"\n###   买入 {len(buys)} 笔")
                for t in buys:
                    ac = t.get('asset_class', '')
                    ac_tag = f"[{ac}]" if ac and ac != 'A股' else ''
                    lines.append(f"- {t['action']} {t['name']}({t['code']}){ac_tag} ¥{t['amount']:,.2f} {t['reason']}")
            if sells:
                lines.append(f"\n###   卖出 {len(sells)} 笔")
                for t in sells:
                    lines.append(f"- {t['action']} {t['name']}({t['code']}) ¥{t['amount']:,.2f} {t['reason']}")

            title = f"AI交易：{len(trades_done)}笔 {env_label}"
            content = "\n".join(lines)
            await send_serverchan(config.serverchan_key, title, content)
            print(f"[{now}] {len(trades_done)}笔 {env_label} {market_mode}")
        else:
            # 无交易时也推送状态，确认系统正常运行
            title = f"AI监控：无操作 {env_label}"
            content = (
                f"## AI监控报告 ({now.strftime('%H:%M')})\n\n"
                f"**环境**: {env_label} | "
                f"**市场**: {'趋势' if market_mode=='trend' else '震荡'} | "
                f"**持仓**: {holdings_count}只 | **余额**: ¥{account.balance:,.2f}{r_info}\n"
                f"**胜率**: {win_rate:.0f}% | **均R**: {avg_r:.2f} | "
                f"**最强板块**: {top_sector[0]}({top_sector[1]*100:+.1f}%) | "
                f"**市场宽度**: {breadth_pct:.0f}%{breadth_label}\n\n"
                f"本轮扫描未触发交易信号，系统持续监控中。"
            )
            await send_serverchan(config.serverchan_key, title, content)
            print(f"[{now}] 无操作 {env_label} {market_mode}")

        # ==================== 每日净值快照 ====================
        # 重新计算持仓（交易可能已改变余额/持仓）
        net_shares_map, _, held_funds = _compute_holdings(db)
        holdings_value = 0
        for fc in held_funds:
            if fc in all_prices_map:
                holdings_value += net_shares_map[fc] * all_prices_map[fc][-1]
        total_assets = holdings_value + account.balance
        holdings_count = sum(1 for ns in net_shares_map.values() if ns > 0.0001)

        from models import DailySnapshot
        existing_snap = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == today).first()
        if not existing_snap:
            # 基准收益
            benchmark_prices = all_prices_map.get("000961", [])
            bench_ret = 0
            if len(benchmark_prices) >= 2:
                bench_ret = (benchmark_prices[-1] - benchmark_prices[-2]) / benchmark_prices[-2]

            # 历史最大回撤
            prev_snaps = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(60).all()
            peak = total_assets
            for s in prev_snaps:
                peak = max(peak, s.total_assets)
            dd = (total_assets - peak) / peak if peak > 0 else 0
            hist_max_dd = min(dd, min((s.max_drawdown or 0) for s in prev_snaps)) if prev_snaps else dd

            # 累计收益
            cum_ret = (total_assets - INITIAL_BALANCE) / INITIAL_BALANCE
            bench_cum = 0
            if prev_snaps and prev_snaps[0].benchmark_cumulative is not None:
                bench_cum = prev_snaps[0].benchmark_cumulative + bench_ret
            else:
                bench_cum = bench_ret

            # 策略当日收益
            prev_total = prev_snaps[0].total_assets if prev_snaps else INITIAL_BALANCE
            daily_ret = (total_assets - prev_total) / prev_total if prev_total > 0 else 0

            db.add(DailySnapshot(
                snapshot_date=today,
                total_assets=round(total_assets, 2),
                balance=round(account.balance, 2),
                holdings_value=round(holdings_value, 2),
                holdings_count=holdings_count,
                daily_return=round(daily_ret, 6),
                cumulative_return=round(cum_ret, 6),
                max_drawdown=round(hist_max_dd, 6),
                benchmark_return=round(bench_ret, 6),
                benchmark_cumulative=round(bench_cum, 6),
            ))
            db.commit()
            print(f"[{now}] 净值快照: 总资产={total_assets:.2f} 累计={cum_ret*100:.2f}% 最大回撤={hist_max_dd*100:.2f}%")

        # ==================== 行为指纹更新 + 异常检测 ====================
        try:
            from services.evolution import update_behavior_fingerprints, detect_anomalies
            update_behavior_fingerprints()
            anomalies = detect_anomalies()
            if anomalies:
                for a in anomalies:
                    print(f"[{now}] 异常告警: {a['detail']} (z={a['z_score']})")
                    if a["severity"] == "critical":
                        await send_serverchan(config.serverchan_key, "⚠️ 执行层异常", a["detail"])
        except Exception as e:
            print(f"[{now}] 行为检测异常: {e}")
    except Exception as e:
        # 扫描失败告警：确保异常不会被静默吞掉
        error_msg = f"扫描异常: {type(e).__name__}: {e}"
        print(f"[{datetime.now()}] {error_msg}")
        try:
            config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
            if config and config.serverchan_key:
                await send_serverchan(config.serverchan_key, "⚠️ 扫描异常", error_msg)
        except Exception:
            pass
    finally:
        db.close()


def _load_price_data(db, fund_universe: list[str]) -> tuple[dict[str, list[float]], dict[str, str]]:
    """加载价格数据和基金名称，返回 (价格字典, 名称字典)"""
    prices_map = {}
    names_map = {}
    for code in fund_universe:
        fund = db.query(Fund).filter(Fund.code == code).first()
        names_map[code] = fund.name if fund and fund.name else code
        prices = [r.nav for r in db.query(FundNav.nav)
                  .filter(FundNav.fund_code == code)
                  .order_by(FundNav.date.asc()).all()]
        if len(prices) >= 20:
            prices_map[code] = prices
    return prices_map, names_map


def _compute_holdings(db) -> tuple[dict[str, float], dict[str, float], list[str]]:
    """计算当前持仓：返回 (份额字典, 成本字典, 持仓代码列表)
    只计算已确认的交易，pending 买入不计入持仓。"""
    _auto_confirm_trades(db)
    all_trades = db.query(VirtualTrade).all()
    net_shares = {}
    cost_basis = {}
    for t in all_trades:
        # 买入且未确认 → 不计入持仓
        if t.trade_type == "buy" and t.status == "pending":
            continue
        if t.trade_type == "buy":
            net_shares[t.fund_code] = net_shares.get(t.fund_code, 0) + t.shares
            cost_basis[t.fund_code] = cost_basis.get(t.fund_code, 0) + t.amount
        else:
            if t.fund_code in net_shares and net_shares[t.fund_code] > 0:
                sell_ratio = t.shares / (net_shares[t.fund_code] + t.shares) if (net_shares[t.fund_code] + t.shares) > 0 else 0
                cost_basis[t.fund_code] = cost_basis.get(t.fund_code, 0) * (1 - sell_ratio)
            net_shares[t.fund_code] = net_shares.get(t.fund_code, 0) - t.shares
    held = [fc for fc, ns in net_shares.items() if ns > 0.0001]
    return net_shares, cost_basis, held


async def post_market_analysis():
    """盘后 AI 分析报告（18:05，数据更新后）"""
    if not _is_trading_day(date.today()):
        print(f"[{datetime.now()}] 非交易日，跳过盘后分析")
        return
    from database import SessionLocal
    db = SessionLocal()
    try:
        config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
        if not config or not config.enabled or not config.serverchan_key:
            return

        ai_report = await ai_daily_analysis(db)
        if ai_report:
            title = "AI 策略分析报告"
            content = f"##   AI 策略分析 ({date.today().isoformat()})\n\n{ai_report}"
            await send_serverchan(config.serverchan_key, title, content)
            print(f"[{datetime.now()}] AI分析已推送")
        else:
            print(f"[{datetime.now()}] AI分析无结果（未配置 API Key 或无数据）")
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化定时任务"""
    # 每日18:00更新基金数据（收盘后）
    scheduler.add_job(
        update_all_funds,
        CronTrigger(hour=18, minute=0),
        id="update_funds_daily",
        name="每日更新基金数据",
        replace_existing=True
    )
    # 盘前分析：8:30（环境感知 + 板块强度 + 持仓概况）
    scheduler.add_job(
        pre_market_analysis,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="pre_market_analysis",
        name="盘前分析",
        replace_existing=True,
    )
    # 早盘扫描：9:30（T-1净值信号 → T日收盘成交）
    scheduler.add_job(
        market_monitor,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30),
        id="market_monitor_morning",
        name="早盘扫描",
        replace_existing=True,
    )
    # 午盘扫描：14:50（T-1净值信号 → T日收盘成交，14:55前截止）
    scheduler.add_job(
        market_monitor,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=50),
        id="market_monitor_afternoon",
        name="午盘扫描",
        replace_existing=True,
    )
    # 盘后 AI 分析（周一到周五 18:05，数据更新后）
    scheduler.add_job(
        post_market_analysis,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=5),
        id="post_market_analysis",
        name="盘后AI分析",
        replace_existing=True,
    )
    # 心跳：每 30 分钟写入时间戳，供外部监控检测服务存活
    def _write_heartbeat():
        import pathlib
        heartbeat_path = pathlib.Path(__file__).parent / ".heartbeat"
        heartbeat_path.write_text(str(int(datetime.now().timestamp())))

    scheduler.add_job(_write_heartbeat, CronTrigger(minute="0,30"), id="heartbeat", name="心跳", replace_existing=True)
    _write_heartbeat()  # 启动时立即写一次

    scheduler.start()
    print("定时任务调度器已启动")

    # 启动通知：告知用户系统已上线
    try:
        from database import SessionLocal
        db = SessionLocal()
        config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
        if config and config.enabled and config.serverchan_key:
            jobs = [f"- {job.name} ({job.next_run_time.strftime('%m-%d %H:%M') if job.next_run_time else '未调度'})"
                    for job in scheduler.get_jobs()]
            content = f"##   系统启动通知\n\n**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n**定时任务**:\n" + "\n".join(jobs)
            await send_serverchan(config.serverchan_key, "系统已启动", content)
            print("启动通知已发送")
        db.close()
    except Exception as e:
        print(f"启动通知发送失败: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时停止调度器"""
    scheduler.shutdown()
    print("定时任务调度器已停止")

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from auth import APIKeyMiddleware
app.add_middleware(APIKeyMiddleware)


@app.get("/api/fund/{code}")
async def get_fund_info(code: str, db: Session = Depends(get_db)):
    """获取基金基本信息。"""
    code = validate_fund_code(code)
    fund = db.query(Fund).filter(Fund.code == code).first()
    if not fund:
        raise HTTPException(status_code=404, detail="未找到该基金，请先查询")
    return {"code": fund.code, "name": fund.name}


@app.post("/api/fund/{code}/fetch")
async def fetch_fund(code: str, db: Session = Depends(get_db)):
    """拉取基金净值数据。"""
    code = validate_fund_code(code)
    try:
        result = await fetch_fund_nav(code, db)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取数据失败: {str(e)}")


@app.get("/api/fund/{code}/metrics", response_model=FundMetrics)
async def get_metrics(code: str, db: Session = Depends(get_db)):
    """计算并返回基金指标。"""
    code = validate_fund_code(code)
    nav_count = db.query(FundNav).filter(FundNav.fund_code == code).count()
    if nav_count == 0:
        raise HTTPException(status_code=400, detail="请先拉取基金数据")
    try:
        return calculate_metrics(code, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/fund/{code}/nav")
async def get_nav_history(code: str, db: Session = Depends(get_db)):
    """获取净值历史数据。"""
    code = validate_fund_code(code)
    navs = (
        db.query(FundNav)
        .filter(FundNav.fund_code == code)
        .order_by(asc(FundNav.date))
        .all()
    )
    if not navs:
        raise HTTPException(status_code=400, detail="请先拉取基金数据")
    return [
        {
            "date": n.date.isoformat(),
            "nav": n.nav,
            "acc_nav": n.acc_nav,
            "daily_return": n.daily_return,
        }
        for n in navs
    ]


@app.get("/api/fund/{code}/report", response_class=HTMLResponse)
async def get_report(code: str, db: Session = Depends(get_db)):
    """生成并返回 HTML 报告。"""
    code = validate_fund_code(code)
    navs = (
        db.query(FundNav)
        .filter(FundNav.fund_code == code)
        .order_by(asc(FundNav.date))
        .all()
    )
    if not navs:
        raise HTTPException(status_code=400, detail="请先拉取基金数据")

    fund = db.query(Fund).filter(Fund.code == code).first()
    metrics = calculate_metrics(code, db)

    nav_points = [
        NavPoint(date=n.date, nav=n.nav, acc_nav=n.acc_nav, daily_return=n.daily_return)
        for n in navs
    ]

    report_data = FundReportData(
        info=FundInfo(code=code, name=fund.name if fund else ""),
        metrics=FundMetrics(**metrics),
        nav_history=nav_points,
    )

    # 保存报告记录
    report = FundReport(
        fund_code=code,
        annualized_return=metrics["annualized_return"],
        max_drawdown=metrics["max_drawdown"],
        sharpe_ratio=metrics["sharpe_ratio"],
        volatility=metrics["volatility"],
        start_date=metrics["start_date"],
        end_date=metrics["end_date"],
    )
    db.add(report)
    db.commit()

    html = generate_html_report(report_data)
    return HTMLResponse(content=html)


@app.get("/api/fund/{code}/cycle")
async def get_cycle_analysis(code: str, db: Session = Depends(get_db)):
    """获取基金强弱周期分析。"""
    code = validate_fund_code(code)
    navs = (
        db.query(FundNav)
        .filter(FundNav.fund_code == code)
        .order_by(asc(FundNav.date))
        .all()
    )
    if not navs:
        raise HTTPException(status_code=400, detail="请先拉取基金数据")

    prices = [n.nav for n in navs]
    cycle = calculate_cycle_strength(prices)
    annual_ret = calculate_annual_return(prices)

    return {
        **cycle,
        "annual_return": annual_ret,
        "show_warning": annual_ret > 20,
    }


@app.get("/api/fund/{code}/macro")
async def get_macro_clock(code: str, db: Session = Depends(get_db)):
    """获取美林时钟经济阶段分析。"""
    code = validate_fund_code(code)
    nav_count = db.query(FundNav).filter(FundNav.fund_code == code).count()
    if nav_count == 0:
        raise HTTPException(status_code=400, detail="请先拉取基金数据")

    metrics = calculate_metrics(code, db)
    clock = get_merrill_clock_stage(metrics["annualized_return"], metrics["volatility"])
    return clock


@app.get("/api/fund/{code}/holdings")
async def get_fund_holdings(code: str, db: Session = Depends(get_db)):
    """获取基金底层资产分析。"""
    code = validate_fund_code(code)
    fund = db.query(Fund).filter(Fund.code == code).first()
    if not fund:
        raise HTTPException(status_code=404, detail="未找到该基金")

    analysis = infer_fund_type(fund.name or "")
    return analysis


# ==================== 虚拟交易 ====================


@app.post("/api/portfolio/init")
async def init_portfolio(body: PortfolioInit, db: Session = Depends(get_db)):
    """初始化或重置虚拟账户。"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if account:
        account.balance = body.balance
    else:
        account = VirtualAccount(id=1, balance=body.balance)
        db.add(account)
    # 清空交易记录
    db.query(VirtualTrade).delete()
    db.commit()
    return {"balance": body.balance}


@app.get("/api/portfolio/account")
async def get_account(db: Session = Depends(get_db)):
    """查询账户余额。"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        return {"balance": None, "initialized": False}
    return {"balance": account.balance, "initialized": True}


@app.post("/api/portfolio/buy")
async def buy_fund(body: PortfolioBuy, db: Session = Depends(get_db)):
    """买入基金（按金额）。"""
    code = validate_fund_code(body.fund_code)
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="买入金额必须大于0")

    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        raise HTTPException(status_code=400, detail="请先初始化账户")
    if account.balance < body.amount:
        raise HTTPException(status_code=400, detail="余额不足")

    # 获取最新净值
    latest_nav = (
        db.query(FundNav)
        .filter(FundNav.fund_code == code)
        .order_by(FundNav.date.desc())
        .first()
    )
    if not latest_nav:
        raise HTTPException(status_code=400, detail="未找到该基金净值数据，请先查询")

    fund = db.query(Fund).filter(Fund.code == code).first()
    fund_name = fund.name if fund else ""

    shares = body.amount / latest_nav.nav
    account.balance -= body.amount
    after_15 = datetime.now().hour >= 15
    confirm_dt = _next_trading_day(date.today(), after_15)

    trade = VirtualTrade(
        fund_code=code,
        fund_name=fund_name,
        trade_type="buy",
        trade_label="手动",
        shares=shares,
        nav=latest_nav.nav,
        amount=body.amount,
        status="pending",
        confirm_date=confirm_dt,
    )
    db.add(trade)
    db.commit()

    return {
        "fund_code": code,
        "fund_name": fund_name,
        "shares": round(shares, 4),
        "nav": latest_nav.nav,
        "amount": body.amount,
        "balance": round(account.balance, 2),
        "status": "pending",
        "confirm_date": confirm_dt.isoformat(),
        "trade_label": "手动",
    }


@app.post("/api/portfolio/sell")
async def sell_fund(body: PortfolioSell, db: Session = Depends(get_db)):
    """卖出基金（全部份额）。"""
    code = validate_fund_code(body.fund_code)

    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        raise HTTPException(status_code=400, detail="请先初始化账户")

    # 计算持有份额（只计已确认的买入）
    _auto_confirm_trades(db)
    buys = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.fund_code == code, VirtualTrade.trade_type == "buy", VirtualTrade.status == "confirmed")
        .all()
    )
    sells = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.fund_code == code, VirtualTrade.trade_type == "sell")
        .all()
    )
    total_shares = sum(t.shares for t in buys) - sum(t.shares for t in sells)
    if total_shares <= 0:
        raise HTTPException(status_code=400, detail="未持有该基金（如有待确认买入，需等T+1确认后方可卖出）")

    latest_nav = (
        db.query(FundNav)
        .filter(FundNav.fund_code == code)
        .order_by(FundNav.date.desc())
        .first()
    )
    if not latest_nav:
        raise HTTPException(status_code=400, detail="未找到净值数据")

    sell_amount = total_shares * latest_nav.nav
    account.balance += sell_amount

    fund = db.query(Fund).filter(Fund.code == code).first()
    trade = VirtualTrade(
        fund_code=code,
        fund_name=fund.name if fund else "",
        trade_type="sell",
        shares=total_shares,
        nav=latest_nav.nav,
        amount=sell_amount,
        status="confirmed",
    )
    db.add(trade)
    db.commit()

    return {
        "fund_code": code,
        "shares": round(total_shares, 4),
        "nav": latest_nav.nav,
        "amount": round(sell_amount, 2),
        "balance": round(account.balance, 2),
    }


@app.get("/api/portfolio/holdings")
async def get_holdings(db: Session = Depends(get_db)):
    """查询持仓列表。"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        return {"balance": 0, "holdings": [], "total_value": 0, "total_cost": 0, "total_pnl": 0, "pending_trades": []}

    _auto_confirm_trades(db)
    trades = db.query(VirtualTrade).all()

    # 分离已确认和待确认的买入
    pending_buy_trades = [t for t in trades if t.trade_type == "buy" and t.status == "pending"]

    # 按基金汇总（只计已确认交易）
    fund_map: dict[str, dict] = {}
    for t in trades:
        if t.trade_type == "buy" and t.status == "pending":
            continue
        if t.fund_code not in fund_map:
            fund_map[t.fund_code] = {"fund_name": t.fund_name, "buy_shares": 0, "sell_shares": 0, "buy_amount": 0}
        entry = fund_map[t.fund_code]
        if t.trade_type == "buy":
            entry["buy_shares"] += t.shares
            entry["buy_amount"] += t.amount
        else:
            entry["sell_shares"] += t.shares

    holdings = []
    total_value = 0
    total_cost = 0
    latest_nav_date = None
    for code, info in fund_map.items():
        net_shares = info["buy_shares"] - info["sell_shares"]
        if net_shares <= 0.0001:
            continue
        latest_nav_row = (
            db.query(FundNav)
            .filter(FundNav.fund_code == code)
            .order_by(FundNav.date.desc())
            .first()
        )
        latest_nav = latest_nav_row.nav if latest_nav_row else 0
        nav_date = latest_nav_row.date.isoformat() if latest_nav_row else ""
        if latest_nav_row and (latest_nav_date is None or latest_nav_row.date > latest_nav_date):
            latest_nav_date = latest_nav_row.date
        market_value = net_shares * latest_nav
        cost = info["buy_amount"]
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0

        holdings.append({
            "fund_code": code,
            "fund_name": info["fund_name"] or "",
            "shares": round(net_shares, 4),
            "cost": round(cost, 2),
            "latest_nav": latest_nav,
            "nav_date": nav_date,
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        total_value += market_value
        total_cost += cost

    # 待确认交易列表
    pending_list = []
    for t in pending_buy_trades:
        pending_list.append({
            "fund_code": t.fund_code,
            "fund_name": t.fund_name or "",
            "trade_label": t.trade_label or "",
            "amount": round(t.amount, 2),
            "nav": t.nav,
            "shares": round(t.shares, 4),
            "confirm_date": t.confirm_date.isoformat() if t.confirm_date else "",
        })

    nav_date_str = latest_nav_date.isoformat() if latest_nav_date else ""
    nav_stale = latest_nav_date < date.today() if latest_nav_date else True

    return {
        "balance": round(account.balance, 2),
        "holdings": holdings,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
        "nav_date": nav_date_str,
        "nav_stale": nav_stale,
        "pending_trades": pending_list,
    }


@app.get("/api/portfolio/history")
async def get_trade_history(db: Session = Depends(get_db)):
    """查询交易记录。"""
    trades = (
        db.query(VirtualTrade)
        .order_by(VirtualTrade.trade_date.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": t.id,
            "fund_code": t.fund_code,
            "fund_name": t.fund_name,
            "trade_type": t.trade_type,
            "shares": round(t.shares, 4),
            "nav": t.nav,
            "amount": round(t.amount, 2),
            "trade_date": t.trade_date.isoformat() if t.trade_date else "",
            "status": t.status or "confirmed",
            "confirm_date": t.confirm_date.isoformat() if t.confirm_date else "",
        }
        for t in trades
    ]


@app.get("/api/ai-trading/board")
async def get_ai_trading_board(db: Session = Depends(get_db)):
    """AI 交易看板：收益率、持仓、交易记录"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        return {"initialized": False, "balance": 0, "total_assets": 0, "total_return_pct": 0, "holdings": [], "trades": []}

    _auto_confirm_trades(db)
    initial_balance = 100000.0
    trades = db.query(VirtualTrade).order_by(VirtualTrade.trade_date.asc()).all()

    # 计算持仓（只计已确认交易）
    fund_map: dict[str, dict] = {}
    for t in trades:
        if t.trade_type == "buy" and t.status == "pending":
            continue
        if t.fund_code not in fund_map:
            fund_map[t.fund_code] = {"fund_name": t.fund_name, "buy_shares": 0, "sell_shares": 0, "buy_amount": 0, "sell_amount": 0}
        entry = fund_map[t.fund_code]
        if t.trade_type == "buy":
            entry["buy_shares"] += t.shares
            entry["buy_amount"] += t.amount
        else:
            entry["sell_shares"] += t.shares
            entry["sell_amount"] += t.amount

    holdings = []
    holdings_value = 0
    latest_nav_date = None  # 追踪最新净值日期
    for code, info in fund_map.items():
        net_shares = info["buy_shares"] - info["sell_shares"]
        if net_shares <= 0.0001:
            continue
        latest_nav_row = db.query(FundNav).filter(FundNav.fund_code == code).order_by(FundNav.date.desc()).first()
        latest_nav = latest_nav_row.nav if latest_nav_row else 0
        nav_date = latest_nav_row.date.isoformat() if latest_nav_row else ""
        if latest_nav_row and (latest_nav_date is None or latest_nav_row.date > latest_nav_date):
            latest_nav_date = latest_nav_row.date
        market_value = net_shares * latest_nav
        cost = info["buy_amount"]
        pnl = market_value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        holdings.append({
            "fund_code": code,
            "fund_name": info["fund_name"] or "",
            "shares": round(net_shares, 4),
            "cost": round(cost, 2),
            "market_value": round(market_value, 2),
            "latest_nav": latest_nav,
            "nav_date": nav_date,
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        holdings_value += market_value

    # 待确认金额
    pending_value = sum(t.amount for t in trades if t.status == "pending" and t.trade_type == "buy")

    total_assets = account.balance + holdings_value
    total_return_pct = ((total_assets - initial_balance) / initial_balance) * 100

    # 净值时效性：判断数据是否为今天
    today_date = date.today()
    nav_date_str = latest_nav_date.isoformat() if latest_nav_date else ""
    nav_stale = latest_nav_date < today_date if latest_nav_date else True

    # 交易记录（最近50笔）
    recent_trades = db.query(VirtualTrade).order_by(VirtualTrade.trade_date.desc()).limit(50).all()
    trade_list = []
    for t in recent_trades:
        trade_list.append({
            "fund_code": t.fund_code,
            "fund_name": t.fund_name or "",
            "trade_type": t.trade_type,
            "trade_label": t.trade_label or "",
            "amount": round(t.amount, 2),
            "nav": t.nav,
            "shares": round(t.shares, 4),
            "trade_date": t.trade_date.strftime("%m-%d %H:%M") if t.trade_date else "",
            "status": t.status or "confirmed",
            "confirm_date": t.confirm_date.isoformat() if t.confirm_date else "",
        })

    return {
        "initialized": True,
        "balance": round(account.balance, 2),
        "holdings_value": round(holdings_value, 2),
        "pending_value": round(pending_value, 2),
        "total_assets": round(total_assets, 2),
        "initial_balance": initial_balance,
        "total_pnl": round(total_assets - initial_balance, 2),
        "total_return_pct": round(total_return_pct, 2),
        "trade_count": len(trades),
        "nav_date": nav_date_str,
        "nav_stale": nav_stale,
        "holdings": holdings,
        "trades": trade_list,
    }


@app.post("/api/ai-trading/cancel/{trade_id}")
async def cancel_trade(trade_id: int, db: Session = Depends(get_db)):
    """撤销待确认的买入交易"""
    trade = db.query(VirtualTrade).filter(VirtualTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="交易不存在")
    if trade.status != "pending":
        raise HTTPException(status_code=400, detail="只能撤销待确认的交易")
    if trade.trade_type != "buy":
        raise HTTPException(status_code=400, detail="只能撤销买入交易")

    # 退还金额到账户
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if account:
        account.balance += trade.amount

    # 删除对应的 TradeRecord（pending 状态的）
    db.query(TradeRecord).filter(
        TradeRecord.fund_code == trade.fund_code,
        TradeRecord.trade_type == "buy",
        TradeRecord.status == "pending",
        TradeRecord.amount == trade.amount,
        TradeRecord.trade_date == trade.trade_date,
    ).delete()

    db.delete(trade)
    db.commit()

    return {"success": True, "refunded": round(trade.amount, 2), "balance": round(account.balance, 2)}


@app.get("/api/ai-trading/suggestions")
async def get_trading_suggestions(db: Session = Depends(get_db)):
    """AI 交易建议：基于当前市场信号生成买入/卖出建议"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        return {"suggestions": []}

    suggestions = []

    # 加载价格数据
    all_prices = {}
    for code in FUND_UNIVERSE:
        prices = [r.nav for r in db.query(FundNav.nav)
                  .filter(FundNav.fund_code == code)
                  .order_by(FundNav.date.asc()).all()]
        if len(prices) >= 20:
            all_prices[code] = prices

    # 计算当前持仓（只计已确认交易）
    _auto_confirm_trades(db)
    trades = db.query(VirtualTrade).all()
    net_shares = {}
    for t in trades:
        if t.trade_type == "buy" and t.status == "pending":
            continue
        sign = 1 if t.trade_type == "buy" else -1
        net_shares[t.fund_code] = net_shares.get(t.fund_code, 0) + t.shares * sign

    for code in FUND_UNIVERSE:
        if code not in all_prices:
            continue
        prices = all_prices[code]
        fund = db.query(Fund).filter(Fund.code == code).first()
        fund_name = fund.name if fund and fund.name else code
        sector = FUND_SECTOR.get(code, "其他")
        rsi = calculate_rsi(prices)
        close = prices[-1]

        ns = net_shares.get(code, 0)
        held = ns > 0.0001

        if len(prices) < 60:
            continue

        ma20 = sum(prices[-20:]) / 20
        ma60 = sum(prices[-60:]) / 60
        prev_ma20 = sum(prices[-21:-1]) / 20 if len(prices) >= 21 else ma20
        golden_cross = close > ma20 and prices[-2] <= prev_ma20
        trend = close > ma20 > ma60 > 0 and 50 <= rsi <= 68
        oversold = rsi < 30

        action = "hold"
        amount = 0
        reason = ""
        confidence = 50

        if oversold and not held:
            action = "买入"
            amount = min(5000, account.balance - MIN_CASH_RESERVE)
            reason = f"RSI={rsi:.0f} 超卖，{sector}板块存在反弹机会"
            confidence = 75
        elif golden_cross:
            action = "买入"
            amount = min(5000, account.balance - MIN_CASH_RESERVE)
            reason = f"20日均线金叉确认，{sector}趋势转多"
            confidence = 80
        elif trend and (not held or ns * close < MAX_POSITION_VALUE):
            action = "买入"
            amount = min(3000, account.balance - MIN_CASH_RESERVE)
            reason = f"趋势确认买入，RSI={rsi:.0f}处于健康区间"
            confidence = 70
        elif rsi > 72 and held:
            action = "卖出"
            amount = round(ns * close, 0)
            reason = f"RSI={rsi:.0f}超买，建议止盈"
            confidence = 65

        if action != "hold" and amount > 0:
            suggestions.append({
                "fundCode": code,
                "fundName": fund_name,
                "action": action,
                "amount": round(amount, 0),
                "reason": reason,
                "confidence": confidence,
            })

    suggestions.sort(key=lambda x: x["confidence"], reverse=True)
    return {"suggestions": suggestions[:8]}


@app.get("/api/ai-trading/fund-picks")
async def get_fund_picks(db: Session = Depends(get_db)):
    """AI 精选基金推荐：基于多因子评分排名"""
    picks = []

    for code in FUND_UNIVERSE:
        navs = db.query(FundNav).filter(FundNav.fund_code == code) \
            .order_by(FundNav.date.asc()).all()
        if len(navs) < 60:
            continue

        prices = [n.nav for n in navs]
        fund = db.query(Fund).filter(Fund.code == code).first()
        fund_name = fund.name if fund and fund.name else code
        sector = FUND_SECTOR.get(code, "其他")

        # 多因子评分
        rsi = calculate_rsi(prices)
        cycle = calculate_cycle_strength(prices)
        annual_ret = calculate_annual_return(prices)
        industry = calculate_industry_score(prices)
        fund_type = infer_fund_type(fund_name)

        base_score = industry["score"]
        if cycle["status"] == "weak":
            base_score += 10
        elif cycle["status"] == "strong":
            base_score -= 10
        if annual_ret > 30:
            base_score -= 10

        score = max(0, min(100, base_score))

        risk_map = {"极低": "低", "低": "低", "中": "中", "中高": "中", "高": "高"}
        risk = risk_map.get(fund_type["risk_level"], "中")

        picks.append({
            "code": code,
            "name": fund_name,
            "type": fund_type["fund_type"],
            "sector": sector,
            "reason": cycle["signals"][0] if cycle["signals"] else "综合表现良好",
            "score": round(score, 1),
            "risk": risk,
            "expectedReturn": f"年化{max(0, round(annual_ret * 0.7))}-{round(annual_ret * 1.2)}%" if annual_ret > 0 else "待观察",
            "tags": [sector, fund_type["fund_type"]],
        })

    picks.sort(key=lambda x: x["score"], reverse=True)
    return {"picks": picks[:10]}


@app.get("/api/ai-trading/environment")
async def get_environment_status(db: Session = Depends(get_db)):
    """获取当前环境感知状态"""
    prices = [r.nav for r in db.query(FundNav.nav)
              .filter(FundNav.fund_code == "000961")
              .order_by(FundNav.date.asc()).all()]
    if len(prices) < 80:
        return {"available": False, "message": "数据不足，需要至少80个交易日"}

    env = sense_environment(prices)
    return {
        "available": True,
        "vol_state": env.vol_state.value,
        "trend_state": env.trend_state.value,
        "environment": env.environment.value,
        "strategy": env.strategy,
        "position_coeff": env.position_coeff,
        "atr_20": env.atr_20,
        "atr_60": env.atr_60,
        "adx": env.adx,
        "plus_di": env.plus_di,
        "minus_di": env.minus_di,
    }


@app.get("/api/ai-trading/risk-status")
async def get_risk_status(db: Session = Depends(get_db)):
    """获取当前风控状态"""
    from services.risk_manager import get_risk_summary
    summary = get_risk_summary(db, date.today())
    return summary


@app.get("/api/ai-trading/r-distribution")
async def get_r_distribution(db: Session = Depends(get_db)):
    """获取 R 乘数分布分析"""
    trades = db.query(TradeRecord.r_multiple).filter(
        TradeRecord.r_multiple.isnot(None)
    ).order_by(TradeRecord.trade_date.desc()).limit(100).all()
    r_values = [t.r_multiple for t in trades if t.r_multiple is not None]
    return analyze_r_distribution(r_values)


@app.get("/api/ai-trading/dual-cycle")
async def get_dual_cycle(db: Session = Depends(get_db)):
    """获取双周期状态矩阵"""
    prices = [r.nav for r in db.query(FundNav.nav)
              .filter(FundNav.fund_code == "000961")
              .order_by(FundNav.date.asc()).all()]
    if len(prices) < 80:
        return {"available": False}
    result = analyze_dual_cycle(prices)
    return {
        "available": True,
        "long_cycle": result.long_cycle.value,
        "short_cycle": result.short_cycle.value,
        "long_ema": result.long_ema,
        "short_ema": result.short_ema,
        "adx": result.adx,
        "rsi": result.rsi,
        "allowed_strategy": result.allowed_strategy,
        "cell_expectation": result.cell_expectation,
    }


@app.get("/api/ai-trading/equity-curve")
async def get_equity_curve(db: Session = Depends(get_db)):
    """获取净值曲线数据（策略 vs 基准）"""
    from models import DailySnapshot
    snaps = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.asc()).all()
    if not snaps:
        return {"available": False, "data": []}
    return {
        "available": True,
        "data": [
            {
                "date": s.snapshot_date.isoformat(),
                "total_assets": s.total_assets,
                "daily_return": s.daily_return,
                "cumulative_return": s.cumulative_return,
                "max_drawdown": s.max_drawdown,
                "benchmark_return": s.benchmark_return,
                "benchmark_cumulative": s.benchmark_cumulative,
                "holdings_count": s.holdings_count,
            }
            for s in snaps
        ],
    }


# ==================== 红队测试 & 执行层熔断 API ====================

@app.post("/api/evolution/candidates/{candidate_id}/evaluate")
async def evaluate_strategy(candidate_id: int):
    """完整评估：过拟合检测 + 红队压力测试"""
    from services.evolution import run_full_evaluation
    result = run_full_evaluation(candidate_id)
    return result


@app.post("/api/evolution/candidates/{candidate_id}/stress-test")
async def stress_test_strategy(candidate_id: int):
    """红队压力测试"""
    from services.evolution import red_team_stress_test
    return red_team_stress_test(candidate_id)


@app.post("/api/evolution/candidates/{candidate_id}/overfit-check")
async def check_overfit(candidate_id: int):
    """过拟合检测"""
    from services.evolution import overfit_detection
    return overfit_detection(candidate_id)


@app.get("/api/evolution/circuit-breaker")
async def get_circuit_breaker():
    """执行层行为熔断状态"""
    from services.evolution import check_execution_circuit_breaker
    return check_execution_circuit_breaker()


@app.get("/api/evolution/stress-scenarios")
async def get_stress_scenarios():
    """获取红队测试场景列表"""
    from services.evolution import STRESS_SCENARIOS
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in STRESS_SCENARIOS.items()
    ]


# ============ 关注列表 & 推送配置 ============

@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    """获取关注列表"""
    items = db.query(WatchlistFund).order_by(WatchlistFund.created_at.desc()).all()
    return [{"fund_code": i.fund_code, "fund_name": i.fund_name, "enabled": i.enabled} for i in items]


@app.post("/api/watchlist")
async def add_to_watchlist(body: WatchlistItem, db: Session = Depends(get_db)):
    """添加基金到关注列表"""
    code = validate_fund_code(body.fund_code)
    existing = db.query(WatchlistFund).filter(WatchlistFund.fund_code == code).first()
    if existing:
        raise HTTPException(status_code=400, detail="已在关注列表中")
    # 自动拉取基金数据
    fund = db.query(Fund).filter(Fund.code == code).first()
    fund_name = body.fund_name or (fund.name if fund else code)
    if not fund:
        try:
            result = await fetch_fund_nav(code, db)
            fund = db.query(Fund).filter(Fund.code == code).first()
            fund_name = fund.name if fund and fund.name else fund_name
        except Exception:
            pass
    item = WatchlistFund(fund_code=code, fund_name=fund_name)
    db.add(item)
    db.commit()
    return {"fund_code": code, "fund_name": fund_name}


@app.delete("/api/watchlist/{code}")
async def remove_from_watchlist(code: str, db: Session = Depends(get_db)):
    """从关注列表移除"""
    code = validate_fund_code(code)
    item = db.query(WatchlistFund).filter(WatchlistFund.fund_code == code).first()
    if not item:
        raise HTTPException(status_code=404, detail="不在关注列表中")
    db.delete(item)
    db.commit()
    return {"removed": code}


@app.put("/api/watchlist/{code}")
async def update_watchlist_item(code: str, body: WatchlistUpdate, db: Session = Depends(get_db)):
    """更新关注项（启用/暂停）"""
    code = validate_fund_code(code)
    item = db.query(WatchlistFund).filter(WatchlistFund.fund_code == code).first()
    if not item:
        raise HTTPException(status_code=404, detail="不在关注列表中")
    if body.enabled is not None:
        item.enabled = body.enabled
    db.commit()
    return {"fund_code": code, "enabled": item.enabled}


@app.get("/api/notification/config")
async def get_notification_config(db: Session = Depends(get_db)):
    """获取推送配置"""
    config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
    if not config:
        return {"serverchan_key": "", "enabled": False, "check_interval_minutes": 60}
    return {
        "serverchan_key": config.serverchan_key or "",
        "enabled": bool(config.enabled),
        "check_interval_minutes": config.check_interval_minutes,
    }


@app.put("/api/notification/config")
async def update_notification_config(body: NotificationSettings, db: Session = Depends(get_db)):
    """更新推送配置"""
    config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
    if not config:
        config = NotificationConfig(id=1)
        db.add(config)
    if body.serverchan_key is not None:
        config.serverchan_key = body.serverchan_key
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.check_interval_minutes is not None:
        config.check_interval_minutes = body.check_interval_minutes
    db.commit()
    return {"ok": True}


@app.post("/api/notification/test")
async def test_notification(db: Session = Depends(get_db)):
    """测试推送"""
    config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
    if not config or not config.serverchan_key:
        raise HTTPException(status_code=400, detail="请先配置 Server酱 Key")
    result = await send_serverchan(config.serverchan_key, "测试推送", "基金分析系统推送测试成功！")
    if result.get("code") == 0:
        return {"ok": True, "message": "推送成功，请检查微信"}
    return {"ok": False, "message": f"推送失败: {result}"}


@app.post("/api/admin/update-all")
async def trigger_update_all(db: Session = Depends(get_db)):
    """手动触发更新所有基金数据"""
    funds = db.query(Fund).all()
    results = []
    for fund in funds:
        try:
            result = await fetch_fund_nav(fund.code, db)
            results.append({"code": fund.code, "name": fund.name, "status": "success", "count": result["count"]})
        except Exception as e:
            results.append({"code": fund.code, "name": fund.name, "status": "error", "message": str(e)})
    return {"updated": len(results), "results": results}


@app.get("/api/admin/scheduler-status")
async def get_scheduler_status():
    """获取定时任务状态"""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {"running": scheduler.running, "jobs": jobs}


@app.post("/api/admin/pre-market")
async def trigger_pre_market():
    """手动触发盘前分析"""
    await pre_market_analysis()
    return {"status": "ok", "message": "盘前分析已执行"}


@app.post("/api/admin/ai-analysis")
async def trigger_ai_analysis():
    """手动触发 AI 策略分析"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        report = await ai_daily_analysis(db)
        if report:
            return {"status": "ok", "report": report}
        return {"status": "no_data", "message": "无数据或未配置 DEEPSEEK_API_KEY"}
    finally:
        db.close()


@app.get("/api/admin/backtest")
async def run_backtest_api(start: str = "2025-01-01", end: str = "2026-05-25", version: str = "v5"):
    """执行策略回测。参数：start=开始日期, end=结束日期, version=v5|v6|fused|compare"""
    from datetime import date as dt_date
    try:
        s = dt_date.fromisoformat(start)
        e = dt_date.fromisoformat(end)
        db = next(get_db())
        try:
            if version == "compare":
                from services.backtest import run_backtest as do_v5, run_backtest_fused
                r5 = do_v5(db, s, e)
                rf = run_backtest_fused(db, s, e)
                return {
                    "v5": {k: r5[k] for k in ["total_return", "annualized_return", "max_drawdown",
                                                "sharpe_ratio", "win_rate", "total_trades", "avg_equity_ratio"]},
                    "fused": {k: rf[k] for k in ["total_return", "annualized_return", "max_drawdown",
                                                  "sharpe_ratio", "win_rate", "total_trades", "avg_equity_ratio",
                                                  "r_distribution", "env_distribution"]},
                }
            elif version == "fused":
                from services.backtest import run_backtest_fused
                result = run_backtest_fused(db, s, e)
            elif version == "v6":
                from services.backtest import run_backtest_v6
                result = run_backtest_v6(db, s, e)
            else:
                from services.backtest import run_backtest as do_backtest
                result = do_backtest(db, s, e)
            return result
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e)}


# ==================== 策略进化系统 API ====================

@app.get("/api/evolution/candidates")
async def get_strategy_candidates(status: str = None, limit: int = 20):
    """获取候选策略列表"""
    from services.evolution import list_candidates
    return list_candidates(status=status, limit=limit)


@app.post("/api/evolution/candidates/{candidate_id}/approve")
async def approve_strategy(candidate_id: int, notes: str = "", trial_days: int = 14):
    """审核通过候选策略"""
    from services.evolution import approve_candidate
    try:
        c = approve_candidate(candidate_id, notes=notes, trial_days=trial_days)
        return {"status": "approved", "id": c.id, "trial_end": c.trial_end.isoformat()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/evolution/candidates/{candidate_id}/reject")
async def reject_strategy(candidate_id: int, notes: str = ""):
    """拒绝候选策略"""
    from services.evolution import reject_candidate
    try:
        c = reject_candidate(candidate_id, notes=notes)
        return {"status": "rejected", "id": c.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/evolution/anomalies")
async def get_anomalies(resolved: int = 0, limit: int = 20):
    """获取行为异常告警"""
    from services.evolution import get_anomaly_alerts
    return get_anomaly_alerts(resolved=resolved, limit=limit)


@app.post("/api/evolution/anomalies/{alert_id}/resolve")
async def resolve_anomaly(alert_id: int, db: Session = Depends(get_db)):
    """标记异常已处理"""
    from models import AnomalyAlert
    alert = db.query(AnomalyAlert).filter(AnomalyAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="告警不存在")
    alert.resolved = 1
    db.commit()
    return {"status": "resolved", "id": alert_id}


@app.post("/api/evolution/update-fingerprints")
async def update_fingerprints():
    """更新行为指纹"""
    from services.evolution import update_behavior_fingerprints
    update_behavior_fingerprints()
    return {"status": "updated"}


@app.post("/api/evolution/detect-anomalies")
async def run_anomaly_detection():
    """运行异常检测"""
    from services.evolution import detect_anomalies
    anomalies = detect_anomalies()
    return {"anomalies": anomalies, "count": len(anomalies)}


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """系统健康检查端点"""
    import pathlib
    status = {"status": "ok", "timestamp": datetime.now().isoformat()}

    # 检查调度器
    status["scheduler"] = {
        "running": scheduler.running,
        "job_count": len(scheduler.get_jobs())
    }

    # 检查数据库
    try:
        db.execute("SELECT 1")
        status["database"] = "ok"
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"

    # 检查心跳
    heartbeat_path = pathlib.Path(__file__).parent / ".heartbeat"
    if heartbeat_path.exists():
        try:
            ts = int(heartbeat_path.read_text().strip())
            age_min = (datetime.now().timestamp() - ts) / 60
            status["heartbeat"] = {
                "last_ts": ts,
                "age_minutes": round(age_min, 1),
                "stale": age_min > 60
            }
            if age_min > 60:
                status["status"] = "degraded"
        except Exception:
            status["heartbeat"] = {"error": "无法读取"}
    else:
        status["heartbeat"] = {"error": "文件不存在"}

    # 检查最近交易
    try:
        recent_trade = db.query(TradeRecord).order_by(TradeRecord.created_at.desc()).first()
        if recent_trade:
            status["last_trade"] = {
                "time": str(recent_trade.created_at),
                "fund": recent_trade.fund_name,
                "action": recent_trade.trade_type
            }
    except Exception:
        pass

    return status


# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "out")


@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    file_path = os.path.join(FRONTEND_DIR, full_path)
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return HTMLResponse("<h1>基金分析系统</h1><p>前端文件未找到，请先构建前端。</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
