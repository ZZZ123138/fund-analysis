from sqlalchemy import Column, Integer, String, Float, Date, DateTime
from sqlalchemy.sql import func
from database import Base


class Fund(Base):
    __tablename__ = "funds"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class FundNav(Base):
    __tablename__ = "fund_navs"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, index=True, nullable=False)
    date = Column(Date, nullable=False)
    nav = Column(Float, nullable=False)        # 单位净值
    acc_nav = Column(Float, nullable=True)     # 累计净值
    daily_return = Column(Float, nullable=True)  # 日收益率


class FundReport(Base):
    __tablename__ = "fund_reports"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, index=True, nullable=False)
    annualized_return = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    volatility = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
