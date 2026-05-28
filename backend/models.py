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
    balance = Column(Float, nullable=False, default=100000.0)


class VirtualTrade(Base):
    __tablename__ = "virtual_trades"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, nullable=False)
    fund_name = Column(String, nullable=True)
    trade_type = Column(String, nullable=False)  # "buy" or "sell"
    trade_label = Column(String, nullable=True)  # "建仓"/"补仓"/"定投"/"手动"
    shares = Column(Float, nullable=False)
    nav = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    trade_date = Column(DateTime, server_default=func.now())
    status = Column(String, nullable=False, default="confirmed")  # pending / confirmed
    confirm_date = Column(Date, nullable=True)  # 份额确认日（T+1 交易日）

    # 复合索引：基金代码+交易类型
    __table_args__ = (
        Index('idx_fund_code_trade_type', 'fund_code', 'trade_type'),
    )


class WatchlistFund(Base):
    __tablename__ = "watchlist_funds"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, unique=True, index=True, nullable=False)
    fund_name = Column(String, nullable=True)
    enabled = Column(Integer, default=1)  # 1=启用, 0=暂停
    created_at = Column(DateTime, server_default=func.now())


class NotificationConfig(Base):
    __tablename__ = "notification_config"

    id = Column(Integer, primary_key=True, default=1)
    serverchan_key = Column(String, nullable=True)
    enabled = Column(Integer, default=0)  # 1=启用, 0=关闭
    check_interval_minutes = Column(Integer, default=60)


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


class SystemState(Base):
    """通用键值状态表，用于追踪定投日期、持仓最高净值等"""
    __tablename__ = "system_state"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StrategyState(Base):
    """每日环境状态快照"""
    __tablename__ = "strategy_state"

    id = Column(Integer, primary_key=True, index=True)
    state_date = Column(Date, nullable=False, index=True)
    vol_state = Column(String, nullable=False)
    trend_state = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    atr_20 = Column(Float, nullable=True)
    atr_60 = Column(Float, nullable=True)
    adx = Column(Float, nullable=True)
    plus_di = Column(Float, nullable=True)
    minus_di = Column(Float, nullable=True)
    active_strategy = Column(String, nullable=True)
    environment_coeff = Column(Float, nullable=True)
    account_drawdown = Column(Float, nullable=True)
    circuit_breaker_active = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_strategy_state_date', 'state_date', unique=True),
    )


class TradeRecord(Base):
    """增强交易记录：策略/环境/R乘数/退出原因"""
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, index=True)
    fund_code = Column(String, nullable=False, index=True)
    fund_name = Column(String, nullable=True)
    trade_type = Column(String, nullable=False)
    trade_label = Column(String, nullable=True)  # "建仓"/"补仓"/"定投"/"手动"
    shares = Column(Float, nullable=False)
    nav = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    trade_date = Column(DateTime, server_default=func.now())
    status = Column(String, nullable=False, default="confirmed")  # pending / confirmed
    confirm_date = Column(Date, nullable=True)
    strategy_name = Column(String, nullable=True)
    environment = Column(String, nullable=True)
    r_multiple = Column(Float, nullable=True)
    initial_risk = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)
    position_size_rationale = Column(String, nullable=True)

    __table_args__ = (
        Index('idx_trade_record_code_date', 'fund_code', 'trade_date'),
    )


class RiskState(Base):
    """风控状态：熔断/策略生命周期"""
    __tablename__ = "risk_state"

    id = Column(Integer, primary_key=True, index=True)
    state_date = Column(Date, nullable=False, index=True)
    daily_pnl = Column(Float, default=0.0)
    daily_pnl_pct = Column(Float, default=0.0)
    weekly_drawdown = Column(Float, default=0.0)
    total_drawdown = Column(Float, default=0.0)
    circuit_breaker_daily = Column(Integer, default=0)
    circuit_breaker_weekly = Column(Integer, default=0)
    circuit_breaker_total = Column(Integer, default=0)
    strategy_name = Column(String, nullable=True)
    consecutive_losses = Column(Integer, default=0)
    monthly_expected_value = Column(Float, nullable=True)
    months_negative = Column(Integer, default=0)
    strategy_status = Column(String, default="active")
    peak_assets = Column(Float, nullable=True)
    weekly_peak_assets = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index('idx_risk_state_date', 'state_date', unique=True),
    )


class DailySnapshot(Base):
    """每日净值快照：用于绘制净值曲线和基准对比"""
    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, unique=True)
    total_assets = Column(Float, nullable=False)
    balance = Column(Float, nullable=False)
    holdings_value = Column(Float, nullable=False)
    holdings_count = Column(Integer, default=0)
    daily_return = Column(Float, nullable=True)       # 当日收益率
    cumulative_return = Column(Float, nullable=True)   # 累计收益率
    max_drawdown = Column(Float, nullable=True)        # 历史最大回撤
    benchmark_return = Column(Float, nullable=True)    # 基准(000961)当日收益
    benchmark_cumulative = Column(Float, nullable=True)  # 基准累计收益
    created_at = Column(DateTime, server_default=func.now())


class EnvironmentSnapshot(Base):
    """指标快照，用于调试和复盘"""
    __tablename__ = "environment_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    fund_code = Column(String, nullable=True)
    indicator_name = Column(String, nullable=False)
    indicator_value = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ==================== 策略进化系统 ====================

class StrategyCandidate(Base):
    """候选策略：由学习层生成，等待人工审核"""
    __tablename__ = "strategy_candidates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)                    # 策略名称
    description = Column(String, nullable=True)              # 自然语言描述
    strategy_type = Column(String, nullable=False)           # trend/oscillation/breakout/hybrid
    parameters = Column(String, nullable=False)              # JSON: 策略参数
    logic_code = Column(String, nullable=False)              # 策略逻辑（Python代码）
    source = Column(String, nullable=True)                   # 来源：paper/backtest/manual
    status = Column(String, default="pending")               # pending/approved/rejected/archived
    # 回测结果
    backtest_return = Column(Float, nullable=True)
    backtest_sharpe = Column(Float, nullable=True)
    backtest_max_dd = Column(Float, nullable=True)
    backtest_win_rate = Column(Float, nullable=True)
    backtest_trades = Column(Integer, nullable=True)
    # 红队测试
    stress_test_pass = Column(Integer, default=0)            # 是否通过极端行情测试
    overfit_score = Column(Float, nullable=True)             # 过拟合评分（越低越好）
    robustness_score = Column(Float, nullable=True)          # 鲁棒性评分
    # 审核
    reviewer_notes = Column(String, nullable=True)           # 审核备注
    approved_by = Column(String, nullable=True)              # 审核人
    approved_at = Column(DateTime, nullable=True)
    trial_start = Column(Date, nullable=True)                # 试炼期开始
    trial_end = Column(Date, nullable=True)                  # 试炼期结束
    trial_capital = Column(Float, default=10000.0)           # 试炼资金上限
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class BehaviorFingerprint(Base):
    """执行层行为指纹：记录策略正常行为模式"""
    __tablename__ = "behavior_fingerprints"

    id = Column(Integer, primary_key=True, index=True)
    strategy_name = Column(String, nullable=False)
    metric_name = Column(String, nullable=False)             # avg_trade_size, trade_freq, sector_dist...
    metric_mean = Column(Float, nullable=False)
    metric_std = Column(Float, nullable=False)
    sample_count = Column(Integer, default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_fingerprint_strategy', 'strategy_name', 'metric_name', unique=True),
    )


class AnomalyAlert(Base):
    """异常告警：执行层行为偏离检测"""
    __tablename__ = "anomaly_alerts"

    id = Column(Integer, primary_key=True, index=True)
    alert_date = Column(DateTime, server_default=func.now())
    strategy_name = Column(String, nullable=True)
    anomaly_type = Column(String, nullable=False)            # size_spike, freq_spike, sector_drift, new_fund
    metric_name = Column(String, nullable=False)
    expected_value = Column(Float, nullable=True)
    actual_value = Column(Float, nullable=True)
    z_score = Column(Float, nullable=True)                   # 偏离标准差倍数
    severity = Column(String, default="warning")             # warning/critical
    action_taken = Column(String, nullable=True)             # logged/paused/halted
    resolved = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
