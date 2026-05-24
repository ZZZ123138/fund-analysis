import os
import re
import asyncio
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
from models import Fund, FundNav, FundReport, VirtualAccount, VirtualTrade
from schemas import FundInfo, FundMetrics, NavPoint, FundReportData, ReportRequest, PortfolioInit, PortfolioBuy, PortfolioSell
from services.fund_data import fetch_fund_nav
from services.calculator import (
    calculate_metrics,
    calculate_cycle_strength,
    calculate_annual_return,
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
