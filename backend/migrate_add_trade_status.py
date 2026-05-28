"""迁移脚本：为 virtual_trades 和 trade_records 表添加 status / confirm_date 字段"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "fund_data.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()


def column_exists(table: str, column: str) -> bool:
    cur.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


# virtual_trades
if not column_exists("virtual_trades", "status"):
    cur.execute("ALTER TABLE virtual_trades ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
    print("Added status column to virtual_trades")
else:
    print("virtual_trades.status already exists")

if not column_exists("virtual_trades", "confirm_date"):
    cur.execute("ALTER TABLE virtual_trades ADD COLUMN confirm_date TEXT")
    print("Added confirm_date column to virtual_trades")
else:
    print("virtual_trades.confirm_date already exists")

# trade_records
if not column_exists("trade_records", "status"):
    cur.execute("ALTER TABLE trade_records ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed'")
    print("Added status column to trade_records")
else:
    print("trade_records.status already exists")

if not column_exists("trade_records", "confirm_date"):
    cur.execute("ALTER TABLE trade_records ADD COLUMN confirm_date TEXT")
    print("Added confirm_date column to trade_records")
else:
    print("trade_records.confirm_date already exists")

conn.commit()
conn.close()
print("Migration complete")
