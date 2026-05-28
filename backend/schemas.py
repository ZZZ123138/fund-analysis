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


class PortfolioInit(BaseModel):
    balance: float


class PortfolioBuy(BaseModel):
    fund_code: str
    amount: float


class PortfolioSell(BaseModel):
    fund_code: str


class CycleAnalysis(BaseModel):
    rsi: float
    percentile: float
    ma_deviation: float
    status: str  # "strong" | "weak" | "neutral"
    annual_return: float
    show_warning: bool
    signals: list[str]


class MacroClock(BaseModel):
    stage: str
    stage_cn: str
    description: str
    advice: str


class FundTypeAnalysis(BaseModel):
    fund_type: str
    risk_level: str
    description: str
    characteristics: list[str]


class WatchlistItem(BaseModel):
    fund_code: str
    fund_name: Optional[str] = None


class WatchlistUpdate(BaseModel):
    enabled: Optional[int] = None


class NotificationSettings(BaseModel):
    serverchan_key: Optional[str] = None
    enabled: Optional[int] = None
    check_interval_minutes: Optional[int] = None


class EnvironmentStatus(BaseModel):
    available: bool
    vol_state: Optional[str] = None
    trend_state: Optional[str] = None
    environment: Optional[str] = None
    strategy: Optional[str] = None
    position_coeff: Optional[float] = None
    atr_20: Optional[float] = None
    atr_60: Optional[float] = None
    adx: Optional[float] = None
    plus_di: Optional[float] = None
    minus_di: Optional[float] = None
    message: Optional[str] = None


class RiskStatus(BaseModel):
    has_state: bool
    daily_pnl: Optional[float] = None
    daily_pnl_pct: Optional[float] = None
    weekly_drawdown: Optional[float] = None
    total_drawdown: Optional[float] = None
    consecutive_losses: Optional[int] = None
    strategy_status: Optional[str] = None
    circuit_breaker: Optional[dict] = None
