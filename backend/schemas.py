from pydantic import BaseModel
from datetime import date
from typing import Optional


class FundInfo(BaseModel):
    code: str
    name: Optional[str] = None


class NavPoint(BaseModel):
    date: date
    nav: float
    acc_nav: Optional[float] = None
    daily_return: Optional[float] = None


class FundMetrics(BaseModel):
    fund_code: str
    fund_name: Optional[str] = None
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    volatility: float
    total_return: float
    trading_days: int
    start_date: date
    end_date: date


class FundReportData(BaseModel):
    info: FundInfo
    metrics: FundMetrics
    nav_history: list[NavPoint]


class ReportRequest(BaseModel):
    fund_code: str
