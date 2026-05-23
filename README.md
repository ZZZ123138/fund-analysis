# 基金分析系统

基金净值分析、指标计算与报告生成系统。

## 技术栈

- **前端**: Next.js 14 + React 18 + Recharts
- **后端**: FastAPI + SQLAlchemy + SQLite
- **数据源**: 天天基金 API

## 功能

- 输入基金代码，自动从天天基金拉取历史净值
- 计算核心指标：年化收益率、最大回撤、夏普比率、年化波动率
- 用 Recharts 绘制净值走势图
- 生成 HTML 分析报告
- 数据持久化到 SQLite

## 快速启动

### Windows

```bash
start.bat
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

### 手动启动

**后端:**

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**前端:**

```bash
cd frontend
npm install
npm run dev
```

打开浏览器访问 http://localhost:3000

## 项目结构

```
fund-analysis/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── database.py          # SQLite 配置
│   ├── models.py            # 数据模型
│   ├── schemas.py           # Pydantic Schema
│   ├── services/
│   │   ├── fund_data.py     # 天天基金数据抓取
│   │   ├── calculator.py    # 指标计算
│   │   └── report.py        # 报告生成
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx     # 主页面
│   │   │   ├── layout.tsx
│   │   │   └── globals.css
│   │   └── components/
│   │       ├── FundSearch.tsx
│   │       ├── MetricsCard.tsx
│   │       ├── FundChart.tsx
│   │       ├── FundInfo.tsx
│   │       └── ReportActions.tsx
│   ├── package.json
│   └── next.config.js
├── start.sh
├── start.bat
└── README.md
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/fund/{code}/fetch` | 拉取基金净值数据 |
| GET  | `/api/fund/{code}/metrics` | 获取计算指标 |
| GET  | `/api/fund/{code}/nav` | 获取净值历史 |
| GET  | `/api/fund/{code}/report` | 生成 HTML 报告 |

## 指标说明

- **年化收益率**: 按 252 个交易日折算的年化收益
- **最大回撤**: 净值从峰值到谷值的最大跌幅
- **夏普比率**: (年化收益 - 无风险利率) / 年化波动率，无风险利率默认 2.5%
- **年化波动率**: 日收益率标准差 × √252
