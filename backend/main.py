import os
import re
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc

from database import engine, get_db, Base
from models import Fund, FundNav, FundReport
from schemas import FundInfo, FundMetrics, NavPoint, FundReportData, ReportRequest
from services.fund_data import fetch_fund_nav
from services.calculator import calculate_metrics
from services.report import generate_html_report

Base.metadata.create_all(bind=engine)

FUND_CODE_RE = re.compile(r"^\d{6}$")


def validate_fund_code(code: str) -> str:
    if not FUND_CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="基金代码必须为6位数字")
    return code


app = FastAPI(title="基金分析系统", version="1.0.0")

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
