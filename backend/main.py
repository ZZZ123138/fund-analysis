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
from sqlalchemy import asc
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import engine, get_db, Base
from models import Fund, FundNav, FundReport, VirtualAccount, VirtualTrade, WatchlistFund, NotificationConfig, SystemState
from constants import FUND_SECTOR, FUND_UNIVERSE, INITIAL_BALANCE, MAX_POSITION_VALUE, MIN_CASH_RESERVE, STOP_LOSS, TRAILING_TRIGGER, TRAILING_DRAWDOWN
from schemas import FundInfo, FundMetrics, NavPoint, FundReportData, ReportRequest, PortfolioInit, PortfolioBuy, PortfolioSell, WatchlistItem, WatchlistUpdate, NotificationSettings
from services.fund_data import fetch_fund_nav
from services.calculator import (
    calculate_metrics,
    calculate_cycle_strength,
    calculate_annual_return,
    calculate_rsi,
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


app = FastAPI(title="基金分析系统", version="1.0.0")


async def update_all_funds():
    """定时任务：更新所有基金数据"""
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

        # 计算持仓和收益
        all_trades_all = db.query(VirtualTrade).all()
        net_shares = {}
        cost_map = {}
        for t in all_trades_all:
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

        # 加载持仓
        all_trades = db.query(VirtualTrade).all()
        net_shares_map = {}
        for t in all_trades:
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
    """AI 自主交易 V5：定投 + 均线交叉趋势 + 止损止盈"""
    from database import SessionLocal
    db = SessionLocal()
    try:
        config = db.query(NotificationConfig).filter(NotificationConfig.id == 1).first()
        if not config or not config.enabled or not config.serverchan_key:
            return

        now = datetime.now()

        fund_universe = FUND_UNIVERSE

        # 确保数据存在
        for code in fund_universe:
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
        all_prices_map = {}
        fund_names = {}
        for code in fund_universe:
            fund = db.query(Fund).filter(Fund.code == code).first()
            fund_names[code] = fund.name if fund and fund.name else code
            prices = [r.nav for r in db.query(FundNav.nav)
                      .filter(FundNav.fund_code == code)
                      .order_by(FundNav.date.asc()).all()]
            if len(prices) >= 20:
                all_prices_map[code] = prices

        # 市场模式判断（用沪深300）
        benchmark_code = "000961"
        benchmark_prices = all_prices_map.get(benchmark_code, [])
        if len(benchmark_prices) >= 60:
            ma20_b = sum(benchmark_prices[-20:]) / 20
            ma60_b = sum(benchmark_prices[-60:]) / 60
            close_b = benchmark_prices[-1]
            market_mode = "trend" if (ma20_b > ma60_b and close_b > ma20_b) else "oscillation"
        else:
            market_mode = "oscillation"

        max_equity_ratio = 0.80 if market_mode == "trend" else 0.50

        # 组合状态
        all_trades = db.query(VirtualTrade).all()
        net_shares_map = {}
        cost_basis_map = {}  # 平均成本
        for t in all_trades:
            if t.trade_type == "buy":
                net_shares_map[t.fund_code] = net_shares_map.get(t.fund_code, 0) + t.shares
                cost_basis_map[t.fund_code] = cost_basis_map.get(t.fund_code, 0) + t.amount
            else:
                # 卖出时按比例减少成本
                if t.fund_code in net_shares_map and net_shares_map[t.fund_code] > 0:
                    sell_ratio = t.shares / (net_shares_map[t.fund_code] + t.shares) if (net_shares_map[t.fund_code] + t.shares) > 0 else 0
                    cost_basis_map[t.fund_code] = cost_basis_map.get(t.fund_code, 0) * (1 - sell_ratio)
                net_shares_map[t.fund_code] = net_shares_map.get(t.fund_code, 0) - t.shares

        holdings_value = 0
        held_funds = []
        for fc, ns in net_shares_map.items():
            if ns > 0.0001:
                nav_row = db.query(FundNav.nav).filter(FundNav.fund_code == fc).order_by(FundNav.date.desc()).first()
                if nav_row:
                    holdings_value += ns * nav_row[0]
                    held_funds.append(fc)

        total_assets = holdings_value + account.balance

        trades_done = []
        signals = []

        # ==================== 止损 / 止盈 ====================
        # 加载持仓状态（最高净值、均线状态）
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

            # --- 移动止盈：追踪最高净值 ---
            hn_key = f"highest_nav_{code}"
            prev_highest = float(state_map.get(hn_key, nav))
            current_highest = max(prev_highest, nav)
            hn_row = db.query(SystemState).filter(SystemState.key == hn_key).first()
            if hn_row:
                hn_row.value = str(current_highest)
            else:
                db.add(SystemState(key=hn_key, value=str(current_highest)))

            from_peak = (nav - current_highest) / current_highest if current_highest > 0 else 0
            trailing_active = pnl_pct >= TRAILING_TRIGGER

            # --- 均线死叉检测 ---
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
            sell_ratio = 0
            reason = ""

            # 1. 止损：亏损超过 7%
            if pnl_pct <= STOP_LOSS:
                should_sell, sell_ratio = True, 1.0
                reason = f"止损 {pnl_pct*100:.1f}%"
            # 2. 移动止盈：盈利超 5% 后从高点回撤 3%
            elif trailing_active and from_peak <= -TRAILING_DRAWDOWN:
                should_sell, sell_ratio = True, 1.0
                reason = f"止盈 {pnl_pct*100:.1f}% 从高点{from_peak*100:.1f}%"
            # 3. RSI 超买
            elif rsi > 72:
                should_sell, sell_ratio = True, 1.0
                reason = f"RSI={rsi:.0f} 超买"
            # 4. 均线死叉：跌破 20MA 且持仓盈利
            elif cur_ma == "below" and prev_ma == "above" and pnl_pct > 0:
                should_sell, sell_ratio = True, 1.0
                reason = f"跌破20MA 盈利{pnl_pct*100:.1f}%"

            if should_sell:
                sell_shares = ns * sell_ratio
                sell_amount = sell_shares * nav
                account.balance += sell_amount
                trade = VirtualTrade(
                    fund_code=code, fund_name=fund_names.get(code, code),
                    trade_type="sell", shares=sell_shares,
                    nav=nav, amount=sell_amount,
                )
                db.add(trade)
                trades_done.append({
                    "name": fund_names.get(code, code), "code": code,
                    "sector": FUND_SECTOR.get(code, "其他"),
                    "action": "卖出", "amount": round(sell_amount, 2),
                    "nav": nav, "reason": reason,
                })
                net_shares_map[code] -= sell_shares

        # ==================== 定投：每月第一次扫描买入宽基 ====================
        dca_key = f"dca_{now.strftime('%Y-%m')}"
        already_dca = db.query(SystemState).filter(SystemState.key == dca_key).first()

        dca_done = False
        if not already_dca and now.day <= 5:  # 每月前5天执行定投，且当月未执行过
            dca_funds = [c for c in fund_universe if FUND_SECTOR.get(c) == "宽基" and c in all_prices_map]
            for code in dca_funds:
                available = account.balance - MIN_CASH_RESERVE
                if available < 3000:
                    break
                ns = net_shares_map.get(code, 0)
                current_value = ns * all_prices_map[code][-1] if ns > 0 else 0
                if current_value >= MAX_POSITION_VALUE:
                    continue
                nav = all_prices_map[code][-1]
                buy_amount = min(5000, available)
                if buy_amount >= 2000:
                    shares = buy_amount / nav
                    account.balance -= buy_amount
                    trade = VirtualTrade(
                        fund_code=code, fund_name=fund_names.get(code, code),
                        trade_type="buy", shares=shares,
                        nav=nav, amount=buy_amount,
                    )
                    db.add(trade)
                    trades_done.append({
                        "name": fund_names.get(code, code), "code": code,
                        "sector": "宽基", "action": "定投",
                        "amount": round(buy_amount, 2), "nav": nav,
                        "reason": f"月度定投 {now.strftime('%Y-%m')}",
                    })
                    net_shares_map[code] = net_shares_map.get(code, 0) + shares
                    dca_done = True
            if dca_done:
                db.add(SystemState(key=dca_key, value=now.isoformat()))
                db.flush()

        # ==================== 战术买入（仅趋势市） ====================
        if market_mode == "trend":
            # 重新计算持仓
            holdings_value = 0
            for fc, ns in net_shares_map.items():
                if ns > 0.0001 and fc in all_prices_map:
                    holdings_value += ns * all_prices_map[fc][-1]
            total_assets = holdings_value + account.balance

            buy_candidates = []
            for code in fund_universe:
                if code not in all_prices_map:
                    continue
                prices = all_prices_map[code]
                if len(prices) < 60:
                    continue

                close = prices[-1]
                ma20_val = sum(prices[-20:]) / 20
                ma60_val = sum(prices[-60:]) / 60
                rsi = calculate_rsi(prices)

                # 前一天的均线状态
                prev_close = prices[-2] if len(prices) >= 2 else close
                prev_ma20 = sum(prices[-21:-1]) / 20 if len(prices) >= 21 else ma20_val

                golden_cross = (close > ma20_val) and (prev_close <= prev_ma20)
                trend_buy = (close > ma20_val > ma60_val > 0 and 50 <= rsi <= 68)

                if not golden_cross and not trend_buy:
                    continue
                if rsi > 68:
                    continue

                ns = net_shares_map.get(code, 0)
                current_value = ns * close if ns > 0 else 0
                if current_value >= MAX_POSITION_VALUE:
                    continue

                base = 5000 if golden_cross else 3000
                if current_value > 0:
                    remaining = MAX_POSITION_VALUE - current_value
                    if remaining <= 0:
                        continue
                    base = min(base, remaining, 3000)

                available_for_equity = total_assets * max_equity_ratio - holdings_value
                if available_for_equity <= 0:
                    break
                base = min(base, available_for_equity)

                available = account.balance - MIN_CASH_RESERVE
                buy_amount = min(base, available)

                if buy_amount >= 2000:
                    signal = "金叉" if golden_cross else "趋势"
                    buy_candidates.append({
                        "code": code, "amount": buy_amount,
                        "rsi": rsi, "signal": signal,
                    })

            buy_candidates.sort(key=lambda x: x["rsi"])
            for cand in buy_candidates:
                nav = all_prices_map[cand["code"]][-1]
                shares = cand["amount"] / nav
                account.balance -= cand["amount"]
                trade = VirtualTrade(
                    fund_code=cand["code"], fund_name=fund_names.get(cand["code"], cand["code"]),
                    trade_type="buy", shares=shares,
                    nav=nav, amount=cand["amount"],
                )
                db.add(trade)
                trades_done.append({
                    "name": fund_names.get(cand["code"], cand["code"]),
                    "code": cand["code"],
                    "sector": FUND_SECTOR.get(cand["code"], "其他"),
                    "action": "建仓" if net_shares_map.get(cand["code"], 0) <= 0 else "补仓",
                    "amount": round(cand["amount"], 2), "nav": nav,
                    "reason": f"{cand['signal']} RSI={cand['rsi']:.0f} {market_mode}",
                })
                net_shares_map[cand["code"]] = net_shares_map.get(cand["code"], 0) + shares

        db.commit()

        # ==================== 推送结果 ====================
        if trades_done:
            lines = [f"## AI交易报告 ({now.strftime('%H:%M')})\n"]
            lines.append(f"**市场模式**: {'趋势市' if market_mode=='trend' else '震荡市'} | **余额**: ¥{account.balance:,.2f}")

            buys = [t for t in trades_done if t["action"] in ("建仓", "补仓", "定投")]
            sells = [t for t in trades_done if t["action"] == "卖出"]
            if buys:
                lines.append(f"\n###   买入 {len(buys)} 笔")
                for t in buys:
                    lines.append(f"- {t['action']} {t['name']}({t['code']}) ¥{t['amount']:,.2f} {t['reason']}")
            if sells:
                lines.append(f"\n###   卖出 {len(sells)} 笔")
                for t in sells:
                    lines.append(f"- {t['action']} {t['name']}({t['code']}) ¥{t['amount']:,.2f} {t['reason']}")

            title = f"AI交易：{len(trades_done)}笔 {'趋势' if market_mode=='trend' else '震荡'}"
            content = "\n".join(lines)
            await send_serverchan(config.serverchan_key, title, content)
            print(f"[{now}] V5: {len(trades_done)}笔 {market_mode}")
        else:
            print(f"[{now}] V5: 无操作 {market_mode}")
    finally:
        db.close()


async def post_market_analysis():
    """盘后 AI 分析报告（18:05，数据更新后）"""
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
    # 开盘期间每小时监控基金信号（周一到周五 9:30-15:00）
    scheduler.add_job(
        market_monitor,
        CronTrigger(day_of_week="mon-fri", hour="9-14", minute=30),
        id="market_monitor",
        name="市场信号监控",
        replace_existing=True,
    )
    # 盘前分析（周一到周五 8:30）
    scheduler.add_job(
        pre_market_analysis,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="pre_market_analysis",
        name="盘前分析",
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
    scheduler.start()
    print("定时任务调度器已启动")


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

    trade = VirtualTrade(
        fund_code=code,
        fund_name=fund_name,
        trade_type="buy",
        shares=shares,
        nav=latest_nav.nav,
        amount=body.amount,
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
    }


@app.post("/api/portfolio/sell")
async def sell_fund(body: PortfolioSell, db: Session = Depends(get_db)):
    """卖出基金（全部份额）。"""
    code = validate_fund_code(body.fund_code)

    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        raise HTTPException(status_code=400, detail="请先初始化账户")

    # 计算持有份额
    buys = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.fund_code == code, VirtualTrade.trade_type == "buy")
        .all()
    )
    sells = (
        db.query(VirtualTrade)
        .filter(VirtualTrade.fund_code == code, VirtualTrade.trade_type == "sell")
        .all()
    )
    total_shares = sum(t.shares for t in buys) - sum(t.shares for t in sells)
    if total_shares <= 0:
        raise HTTPException(status_code=400, detail="未持有该基金")

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
        return {"balance": 0, "holdings": [], "total_value": 0, "total_cost": 0, "total_pnl": 0}

    trades = db.query(VirtualTrade).all()
    # 按基金汇总
    fund_map: dict[str, dict] = {}
    for t in trades:
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
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        total_value += market_value
        total_cost += cost

    return {
        "balance": round(account.balance, 2),
        "holdings": holdings,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
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
        }
        for t in trades
    ]


@app.get("/api/ai-trading/board")
async def get_ai_trading_board(db: Session = Depends(get_db)):
    """AI 交易看板：收益率、持仓、交易记录"""
    account = db.query(VirtualAccount).filter(VirtualAccount.id == 1).first()
    if not account:
        return {"initialized": False, "balance": 0, "total_assets": 0, "total_return_pct": 0, "holdings": [], "trades": []}

    initial_balance = 100000.0
    trades = db.query(VirtualTrade).order_by(VirtualTrade.trade_date.asc()).all()

    # 计算持仓
    fund_map: dict[str, dict] = {}
    for t in trades:
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
    for code, info in fund_map.items():
        net_shares = info["buy_shares"] - info["sell_shares"]
        if net_shares <= 0.0001:
            continue
        latest_nav_row = db.query(FundNav).filter(FundNav.fund_code == code).order_by(FundNav.date.desc()).first()
        latest_nav = latest_nav_row.nav if latest_nav_row else 0
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
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })
        holdings_value += market_value

    total_assets = account.balance + holdings_value
    total_return_pct = ((total_assets - initial_balance) / initial_balance) * 100

    # 交易记录（最近50笔）
    recent_trades = db.query(VirtualTrade).order_by(VirtualTrade.trade_date.desc()).limit(50).all()
    trade_list = []
    for t in recent_trades:
        trade_list.append({
            "fund_code": t.fund_code,
            "fund_name": t.fund_name or "",
            "trade_type": t.trade_type,
            "amount": round(t.amount, 2),
            "nav": t.nav,
            "shares": round(t.shares, 4),
            "trade_date": t.trade_date.strftime("%m-%d %H:%M") if t.trade_date else "",
        })

    return {
        "initialized": True,
        "balance": round(account.balance, 2),
        "holdings_value": round(holdings_value, 2),
        "total_assets": round(total_assets, 2),
        "initial_balance": initial_balance,
        "total_pnl": round(total_assets - initial_balance, 2),
        "total_return_pct": round(total_return_pct, 2),
        "trade_count": len(trades),
        "holdings": holdings,
        "trades": trade_list,
    }


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

    # 计算当前持仓
    trades = db.query(VirtualTrade).all()
    net_shares = {}
    for t in trades:
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
async def run_backtest_api(start: str = "2025-01-01", end: str = "2026-05-25"):
    """执行策略回测。参数：start=开始日期, end=结束日期"""
    from services.backtest import run_backtest as do_backtest
    from datetime import date as dt_date
    try:
        s = dt_date.fromisoformat(start)
        e = dt_date.fromisoformat(end)
        db = next(get_db())
        try:
            result = do_backtest(db, s, e)
            return result
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e)}


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
