"""共享常量：基金分类、交易参数、费率"""

FUND_SECTOR = {
    "161725": "白酒", "012414": "白酒",
    "005827": "消费", "004868": "消费",
    "003834": "新能源", "001156": "新能源", "015016": "新能源",
    "320007": "科技", "008087": "科技",
    "001714": "医疗",
    "005267": "军工",
    "000961": "宽基", "001938": "宽基", "002021": "宽基", "006098": "宽基",
    "110011": "宽基", "007119": "宽基", "519736": "宽基", "001632": "宽基",
}

FUND_UNIVERSE = list(FUND_SECTOR.keys())

# 账户与仓位
INITIAL_BALANCE = 100000.0
MAX_POSITION_VALUE = 15000
MIN_CASH_RESERVE = 10000

# 止损止盈参数
STOP_LOSS = -0.07          # 止损 -7%（从买入价计算）
TRAILING_TRIGGER = 0.05    # 移动止盈触发 +5%
TRAILING_DRAWDOWN = 0.03   # 移动止盈回撤 -3%

# 费率模型（含滑点）
BUY_FEE = 0.0015 + 0.0005        # 申购费 0.15% + 滑点 0.05%
SELL_FEE_SHORT = 0.015 + 0.0005  # 赎回费 <7天 1.5% + 滑点
SELL_FEE_LONG = 0.005 + 0.0005   # 赎回费 7-365天 0.5% + 滑点
SELL_FEE_YEAR = 0.0025 + 0.0005  # 赎回费 >365天 0.25% + 滑点

# ==================== 环境感知参数 ====================
ATR_PERIOD_SHORT = 20
ATR_PERIOD_LONG = 60
ADX_PERIOD = 14
ADX_STRONG_THRESHOLD = 30      # ADX > 30 = 强趋势
ADX_WEAK_THRESHOLD = 20        # ADX 20-30 = 弱趋势, <20 = 无趋势
VOL_EXPANSION_RATIO = 1.2      # ATR(20)/ATR(60) > 1.2 = 波动扩张
VOL_CONTRACTION_RATIO = 0.8    # ATR(20)/ATR(60) < 0.8 = 波动收缩

# ==================== 策略参数 ====================
# 趋势策略
TREND_EMA_SHORT = 5
TREND_EMA_LONG = 20
TREND_ADX_MIN = 25
TREND_RSI_PULLBACK_LOW = 40
TREND_RSI_PULLBACK_HIGH = 60
TREND_DURATION_PERCENTILE = 80

# 震荡策略
OSC_RANGE_PERIOD = 20
OSC_RSI_OVERSOLD = 30
OSC_RSI_OVERBOUGHT = 70
OSC_STOP_ATR_MULTIPLE = 2.0

# 突破策略
BREAKOUT_RANGE_NARROW_DAYS = 10
BREAKOUT_BW_PERIOD = 20
BREAKOUT_BW_PERCENTILE = 20
BREAKOUT_RSI_SURGE = 5         # RSI 3天内激增>5点（成交量代理）
BREAKOUT_EXIT_DAYS = 3

# ==================== 仓位管理 ====================
RISK_PER_TRADE_PCT = 0.01      # 单笔风险 = 账户的 1%
ENV_STRONG_COEFF = 1.0
ENV_WEAK_COEFF = 0.7
ENV_NONE_COEFF = 0.3
DRAWDOWN_COEFF_THRESHOLD = 0.05
DRAWDOWN_COEFF_VALUE = 0.5
SINGLE_FUND_MAX_PCT = 0.20
SECTOR_MAX_PCT = 0.40              # 单板块最大占比 40%
MIN_TRADE_AMOUNT = 2000

# ==================== 退出管理 ====================
HARD_STOP_ATR_MULTIPLE = 3.0
TRAILING_STOP_ATR_MULTIPLE = 3.0
TRAILING_STOP_PCT = 0.15         # 固定百分比止盈：从高点回撤15%
TIME_STOP_BARS = 5
TRADE_COOLDOWN_DAYS = 3          # 同一基金退出后冷却期（天）
PARTIAL_PROFIT_1R = 0.30
PARTIAL_PROFIT_2R = 0.40
PARTIAL_PROFIT_3R = 0.30

# ==================== 风险控制 ====================
CIRCUIT_BREAKER_DAILY_LOSS = 0.02
CIRCUIT_BREAKER_WEEKLY_DD = 0.05
CIRCUIT_BREAKER_TOTAL_DD = 0.12
STRATEGY_MAX_CONSECUTIVE_LOSSES = 6
STRATEGY_MONTHLY_EV_THRESHOLD = 0.0
STRATEGY_ARCHIVE_MONTHS = 2

# ==================== R 分布监控 ====================
R_DIST_MIN_TRADES = 10          # 最少交易笔数才启用 R 分布分析
R_EXPECTATION_THRESHOLD = 0.05  # 期望值低于此值降权
R_SKEWNESS_THRESHOLD = -0.5     # 偏度低于此值视为凹性（反脆弱惩罚）
R_LEFT_TAIL_PCT = 0.25          # 左尾占比阈值（亏损交易中 R<-2 的比例）

# ==================== 双周期矩阵 ====================
LONG_CYCLE_EMA = 60             # 长周期 EMA（模拟周线方向）
SHORT_CYCLE_EMA = 20            # 短周期 EMA
LONG_TREND_BIAS_ADX = 20        # 长周期趋势确认 ADX 阈值（放宽：20→20）
PULLBACK_RSI_LOW = 30           # 回调入场 RSI 下限（放宽：35→30）
PULLBACK_RSI_HIGH = 65          # 回调入场 RSI 上限（放宽：55→65）
MATRIX_POSITIVE_CELLS = [       # 正期望单元格 (长周期, 短周期) → 策略
    ("trend_up", "pullback", "trend"),
    ("trend_up", "oversold", "oscillation"),
    ("trend_up", "neutral", "trend"),        # 新增：趋势中的中性状态也允许
    ("range", "oversold", "oscillation"),
    ("range", "pullback", "oscillation"),    # 新增：震荡中的回调也允许
]

# ==================== 突破质量过滤 ====================
BREAKOUT_CONFIRM_BARS = 3       # 突破后确认 K 线数
BREAKOUT_MAX_PULLBACK_PCT = 0.50  # 回调不超过实体 50%
BREAKOUT_RSI_HOLD_MIN = 50      # 确认期 RSI 不低于此值
THREE_DAY_EXIT_BARS = 3         # 三天法则：N 根 K 线无利润离场

# ==================== 交易硬约束 ====================
ORDER_CUTOFF_HOUR = 14          # 下单截止：14:55
ORDER_CUTOFF_MINUTE = 55
MIN_HOLD_DAYS_FOR_SELL = 7      # 赎回锁定：持有不足7天禁止卖出
QDII_NAV_DELAY_DAYS = 2         # QDII等品种净值延迟天数

# QDII 品种（净值 T+2 公布）
QDII_FUNDS = {"110011"}  # 易方达优质精选混合(QDII)

# 货基（节假日不自动扫入）
MONEY_MARKET_FUNDS = set()
