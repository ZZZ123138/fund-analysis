import os
import base64
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, Markup
from schemas import FundReportData


TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")


def generate_html_report(data: FundReportData) -> str:
    """生成 HTML 格式的基金分析报告。"""
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    _ensure_template()

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("report.html")

    nav_points = data.nav_history
    dates = [p.date.strftime("%Y-%m-%d") for p in nav_points]
    navs = [p.nav for p in nav_points]

    # 构造净值走势 SVG
    chart_svg = Markup(_build_svg_chart(dates, navs))

    metrics = data.metrics
    return_pct = f"{metrics.annualized_return * 100:.2f}%"
    total_pct = f"{metrics.total_return * 100:.2f}%"
    dd_pct = f"{metrics.max_drawdown * 100:.2f}%"
    vol_pct = f"{metrics.volatility * 100:.2f}%"

    html = template.render(
        fund_code=data.info.code,
        fund_name=data.info.name or "未知",
        annualized_return=return_pct,
        total_return=total_pct,
        max_drawdown=dd_pct,
        sharpe_ratio=f"{metrics.sharpe_ratio:.4f}",
        volatility=vol_pct,
        trading_days=metrics.trading_days,
        start_date=metrics.start_date.strftime("%Y-%m-%d"),
        end_date=metrics.end_date.strftime("%Y-%m-%d"),
        chart_svg=chart_svg,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    return html


def _build_svg_chart(dates: list[str], navs: list[float]) -> str:
    """用纯 SVG 绘制净值走势图。"""
    if not navs:
        return "<p>暂无数据</p>"

    w, h = 700, 300
    pad_l, pad_r, pad_t, pad_b = 50, 20, 20, 40
    chart_w = w - pad_l - pad_r
    chart_h = h - pad_t - pad_b

    min_v = min(navs)
    max_v = max(navs)
    v_range = max_v - min_v if max_v != min_v else 1

    n = len(navs)
    step = chart_w / max(n - 1, 1)

    points = []
    for i, v in enumerate(navs):
        x = pad_l + i * step
        y = pad_t + chart_h - ((v - min_v) / v_range) * chart_h
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)

    # 填充区域
    first_x = pad_l
    last_x = pad_l + (n - 1) * step
    fill_points = f"{first_x},{pad_t + chart_h} " + polyline + f" {last_x},{pad_t + chart_h}"

    # X 轴标签（取 5 个）
    x_labels = ""
    indices = [int(i * (n - 1) / 4) for i in range(5)]
    for idx in indices:
        x = pad_l + idx * step
        label = dates[idx] if idx < len(dates) else ""
        x_labels += f'<text x="{x:.1f}" y="{h - 5}" text-anchor="middle" font-size="10" fill="#666">{label}</text>\n'

    # Y 轴标签
    y_labels = ""
    for i in range(5):
        y = pad_t + chart_h - i * chart_h / 4
        val = min_v + i * v_range / 4
        y_labels += f'<text x="{pad_l - 5}" y="{y:.1f}" text-anchor="end" font-size="10" fill="#666">{val:.4f}</text>\n'
        y_labels += f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" stroke="#eee" stroke-width="1"/>\n'

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet">
  <rect width="{w}" height="{h}" fill="white" rx="4"/>
  {y_labels}
  {x_labels}
  <polygon points="{fill_points}" fill="rgba(59,130,246,0.1)"/>
  <polyline points="{polyline}" fill="none" stroke="#3b82f6" stroke-width="2"/>
</svg>'''
    return svg


def _ensure_template():
    """确保报告模板存在。"""
    tpl_path = os.path.join(TEMPLATE_DIR, "report.html")
    if os.path.exists(tpl_path):
        return
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    tpl = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>基金分析报告 - {{ fund_code }}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; color: #1a1a2e; background: #f8fafc; padding: 40px; }
.container { max-width: 800px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); padding: 40px; }
h1 { font-size: 24px; margin-bottom: 8px; color: #1e3a5f; }
.subtitle { color: #64748b; font-size: 14px; margin-bottom: 32px; }
.section { margin-bottom: 28px; }
.section h2 { font-size: 16px; color: #3b82f6; border-left: 3px solid #3b82f6; padding-left: 10px; margin-bottom: 16px; }
.metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.metric-card { background: #f1f5f9; border-radius: 8px; padding: 16px; text-align: center; }
.metric-label { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.metric-value { font-size: 20px; font-weight: 700; }
.positive { color: #16a34a; }
.negative { color: #dc2626; }
.chart-container { margin: 16px 0; }
.info-table { width: 100%; border-collapse: collapse; }
.info-table td { padding: 8px 12px; border-bottom: 1px solid #f1f5f9; }
.info-table td:first-child { color: #64748b; width: 120px; }
.footer { text-align: center; color: #94a3b8; font-size: 12px; margin-top: 32px; padding-top: 16px; border-top: 1px solid #e2e8f0; }
</style>
</head>
<body>
<div class="container">
  <h1>基金分析报告</h1>
  <p class="subtitle">{{ fund_code }} - {{ fund_name }} | 生成时间: {{ generated_at }}</p>

  <div class="section">
    <h2>核心指标</h2>
    <div class="metrics">
      <div class="metric-card">
        <div class="metric-label">年化收益率</div>
        <div class="metric-value {{ 'positive' if annualized_return[0] != '-' else 'negative' }}">{{ annualized_return }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">最大回撤</div>
        <div class="metric-value negative">{{ max_drawdown }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">夏普比率</div>
        <div class="metric-value">{{ sharpe_ratio }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">总收益率</div>
        <div class="metric-value {{ 'positive' if total_return[0] != '-' else 'negative' }}">{{ total_return }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">年化波动率</div>
        <div class="metric-value">{{ volatility }}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">交易天数</div>
        <div class="metric-value">{{ trading_days }}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>净值走势</h2>
    <div class="chart-container">{{ chart_svg }}</div>
  </div>

  <div class="section">
    <h2>基本信息</h2>
    <table class="info-table">
      <tr><td>基金代码</td><td>{{ fund_code }}</td></tr>
      <tr><td>基金名称</td><td>{{ fund_name }}</td></tr>
      <tr><td>数据区间</td><td>{{ start_date }} ~ {{ end_date }}</td></tr>
      <tr><td>无风险利率</td><td>2.50%</td></tr>
    </table>
  </div>

  <div class="footer">本报告由基金分析系统自动生成，仅供参考，不构成投资建议。</div>
</div>
</body>
</html>'''
    with open(tpl_path, "w", encoding="utf-8") as f:
        f.write(tpl)
