from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Index, text
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
    fund_code = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    nav = Column(Float, nullable=False)        # 单位净值
    acc_nav = Column(Float, nullable=True)     # 累计净值
    daily_return = Column(Float, nullable=True)  # 日收益率

    # 复合索引：基金代码+日期，提高查询性能
    __table_args__ = (
        Index('idx_fund_code_date', 'fund_code', 'date'),
    )


class VirtualAccount(Base):
    __tablename__ = "virtual_account"

    id = Column(Integer, primary_key=True, default=1)
    balance = Column(Float, nullable=False, default=1000000.0)


class VirtualTrade(Base):
    __tablename__ = "virtual_trades"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, nullable=False)
    fund_name = Column(String, nullable=True)
    trade_type = Column(String, nullable=False)  # "buy" or "sell"
    shares = Column(Float, nullable=False)
    nav = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    trade_date = Column(DateTime, server_default=func.now())

    # 复合索引：基金代码+交易类型
    __table_args__ = (
        Index('idx_fund_code_trade_type', 'fund_code', 'trade_type'),
    )


class FundReport(Base):
    __tablename__ = "fund_reports"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, nullable=False)
    annualized_return = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    volatility = Column(Float, nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
