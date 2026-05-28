"""迁移脚本：为 virtual_trades 和 trade_records 表添加 trade_label 字段"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "fund_data.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()


def column_exists(table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


# virtual_trades
if not column_exists("virtual_trades", "trade_label"):
    cur.execute("ALTER TABLE virtual_trades ADD COLUMN trade_label TEXT")
    print("Added trade_label column to virtual_trades")
else:
    print("virtual_trades.trade_label already exists")

# trade_records
if not column_exists("trade_records", "trade_label"):
    cur.execute("ALTER TABLE trade_records ADD COLUMN trade_label TEXT")
    print("Added trade_label column to trade_records")
else:
    print("trade_records.trade_label already exists")

conn.commit()
conn.close()
print("Migration complete")
