import httpx
import re
from datetime import date, datetime
from sqlalchemy.orm import Session
from models import Fund, FundNav


async def fetch_fund_nav(fund_code: str, db: Session) -> dict:
    """从天天基金抓取基金净值数据，优先用 API，失败则解析 JS。"""
    fund = db.query(Fund).filter(Fund.code == fund_code).first()
    if not fund:
        fund = Fund(code=fund_code)
        db.add(fund)

    # 先尝试 API
    nav_data = await _fetch_from_api(fund_code)
    if not nav_data:
        nav_data = await _fetch_from_js(fund_code)

    if not nav_data:
        raise ValueError(f"无法获取基金 {fund_code} 的数据，请检查基金代码是否正确")

    fund_name = nav_data.get("name", "")
    if fund_name:
        fund.name = fund_name
        db.commit()

    records = nav_data.get("records", [])
    if not records:
        raise ValueError(f"基金 {fund_code} 没有净值数据")

    _save_nav_records(db, fund_code, records)

    return {"code": fund_code, "name": fund_name, "count": len(records)}


async def _fetch_from_api(fund_code: str) -> dict | None:
    """通过天天基金 API 获取数据。"""
    url = "https://api.fund.eastmoney.com/f10/lsjz"
    params = {
        "fundCode": fund_code,
        "pageIndex": 1,
        "pageSize": 3000,
    }
    headers = {
        "Referer": "https://fundf10.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers=headers)
            data = resp.json()
            lsjz = data.get("Data", {}).get("LSJZList", [])
            if not lsjz:
                return None
            fund_name = data.get("FundName", "")
            records = []
            for item in lsjz:
                try:
                    d = datetime.strptime(item["FSRQ"], "%Y-%m-%d").date()
                    nav = float(item["DWJZ"])
                    acc = float(item["LJJZ"]) if item.get("LJJZ") else None
                    records.append({"date": d, "nav": nav, "acc_nav": acc})
                except (ValueError, KeyError):
                    continue
            records.sort(key=lambda x: x["date"])
            return {"name": fund_name, "records": records}
    except Exception:
        return None


async def _fetch_from_js(fund_code: str) -> dict | None:
    """备用方案：从基金详情页 JS 解析数据。"""
    url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            text = resp.text

            name_match = re.search(r'fS_name\s*=\s*"([^"]+)"', text)
            fund_name = name_match.group(1) if name_match else ""

            nav_match = re.search(r'Data_netWorthTrend\s*=\s*(\[.*?\]);', text, re.DOTALL)
            if not nav_match:
                return None

            import json
            nav_data = json.loads(nav_match.group(1))
            records = []
            for item in nav_data:
                try:
                    ts = item["x"] / 1000
                    d = datetime.fromtimestamp(ts).date()
                    nav = float(item["y"])
                    records.append({"date": d, "nav": nav, "acc_nav": None})
                except (ValueError, KeyError):
                    continue
            records.sort(key=lambda x: x["date"])
            return {"name": fund_name, "records": records}
    except Exception:
        return None


def _save_nav_records(db: Session, fund_code: str, records: list):
    """保存净值数据到数据库，避免重复。"""
    existing_dates = set()
    existing = db.query(FundNav.date).filter(FundNav.fund_code == fund_code).all()
    for (d,) in existing:
        existing_dates.add(d)

    new_records = []
    prev_nav = None
    for r in records:
        if r["date"] in existing_dates:
            prev_nav = r["nav"]
            continue
        daily_ret = None
        if prev_nav and prev_nav > 0:
            daily_ret = (r["nav"] - prev_nav) / prev_nav
        new_records.append(FundNav(
            fund_code=fund_code,
            date=r["date"],
            nav=r["nav"],
            acc_nav=r.get("acc_nav"),
            daily_return=daily_ret,
        ))
        prev_nav = r["nav"]

    if new_records:
        db.add_all(new_records)
        db.commit()
