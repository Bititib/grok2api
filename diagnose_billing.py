"""VPS 计费数据诊断脚本 — 找出 key 归因异常的根因。

在 VPS 上运行:
    cd /path/to/grok2api
    python diagnose_billing.py

或直接指定 DB 路径:
    python diagnose_billing.py --db-path /path/to/data/billing.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="诊断 billing 数据")
    parser.add_argument("--db-path", default="./data/billing.db", help="billing.db 路径")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    print("=" * 80)
    print("📊 诊断 1: API Keys 总览 (api_keys 表)")
    print("=" * 80)
    rows = conn.execute(
        "SELECT name, SUBSTR(key,1,16) as key_prefix, balance, total_charged, status "
        "FROM api_keys ORDER BY total_charged DESC"
    ).fetchall()
    print(f"{'Name':>20s}  {'Key Prefix':>18s}  {'Balance':>12s}  {'Charged':>12s}  {'Status':>8s}")
    print("-" * 80)
    for r in rows:
        print(f"{r[0]:>20s}  {r[1]:>18s}  {r[2]:>12.4f}  {r[3]:>12.4f}  {r[4]:>8s}")

    print()
    print("=" * 80)
    print("📊 诊断 2: Usage Logs 按 key_name 分布")
    print("=" * 80)
    rows = conn.execute(
        "SELECT key_name, COUNT(*) as cnt, SUM(cost) as total_cost, "
        "MIN(datetime(created_at/1000, 'unixepoch')) as first_at, "
        "MAX(datetime(created_at/1000, 'unixepoch')) as last_at "
        "FROM usage_logs GROUP BY key_name ORDER BY cnt DESC"
    ).fetchall()
    if rows:
        print(f"{'Key Name':>20s}  {'Count':>7s}  {'Total Cost':>12s}  {'First':>20s}  {'Last':>20s}")
        print("-" * 90)
        for r in rows:
            print(f"{r[0]:>20s}  {r[1]:>7d}  {r[2]:>12.6f}  {r[3]:>20s}  {r[4]:>20s}")
    else:
        print("  (usage_logs 表为空)")

    print()
    print("=" * 80)
    print("📊 诊断 3: Usage Logs 按 api_key (前16字符) 分布")
    print("=" * 80)
    rows = conn.execute(
        "SELECT SUBSTR(api_key,1,16) as kp, key_name, COUNT(*) as cnt, SUM(cost) as total_cost "
        "FROM usage_logs GROUP BY kp, key_name ORDER BY cnt DESC"
    ).fetchall()
    if rows:
        print(f"{'API Key Prefix':>18s}  {'Key Name':>15s}  {'Count':>7s}  {'Total Cost':>12s}")
        print("-" * 60)
        for r in rows:
            print(f"{r[0]:>18s}  {r[1]:>15s}  {r[2]:>7d}  {r[3]:>12.6f}")
    else:
        print("  (usage_logs 表为空)")

    print()
    print("=" * 80)
    print("📊 诊断 4: 数据一致性检查")
    print("   比较 api_keys.total_charged vs usage_logs.SUM(cost)")
    print("=" * 80)
    rows = conn.execute("""
        SELECT
            ak.name,
            SUBSTR(ak.key, 1, 16) as key_prefix,
            ak.total_charged,
            COALESCE(ul.log_cost, 0) as log_cost,
            COALESCE(ul.log_count, 0) as log_count,
            ak.total_charged - COALESCE(ul.log_cost, 0) as diff
        FROM api_keys ak
        LEFT JOIN (
            SELECT api_key, SUM(cost) as log_cost, COUNT(*) as log_count
            FROM usage_logs GROUP BY api_key
        ) ul ON ak.key = ul.api_key
        ORDER BY ak.total_charged DESC
    """).fetchall()
    print(f"{'Name':>20s}  {'Key Prefix':>18s}  {'Charged':>10s}  {'Log Cost':>10s}  {'Logs':>6s}  {'Diff':>10s}  {'Status'}")
    print("-" * 100)
    for r in rows:
        flag = "⚠️ 不一致!" if abs(r[5]) > 0.001 else "✅"
        print(f"{r[0]:>20s}  {r[1]:>18s}  {r[2]:>10.4f}  {r[3]:>10.4f}  {r[4]:>6d}  {r[5]:>10.4f}  {flag}")

    print()
    print("=" * 80)
    print("📊 诊断 5: cost=0 但 video_seconds>0 的记录统计")
    print("=" * 80)
    row = conn.execute(
        "SELECT COUNT(*), SUM(video_seconds) FROM usage_logs "
        "WHERE cost = 0 AND video_seconds > 0 AND status = 'success'"
    ).fetchone()
    print(f"  需要修复的记录: {row[0]} 条")
    print(f"  涉及视频总秒数: {row[1] or 0} 秒")
    if row[0] > 0:
        # 按默认720p费率估算
        estimated = (row[1] or 0) * 0.03
        print(f"  按720p费率估算应收: ${estimated:.4f}")

    print()
    print("=" * 80)
    print("📊 诊断 6: 最近 5 条非 test1 的 usage_logs (如果有的话)")
    print("=" * 80)
    rows = conn.execute(
        "SELECT datetime(created_at/1000, 'unixepoch'), key_name, model, endpoint, cost "
        "FROM usage_logs WHERE key_name != 'test1' ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    if rows:
        for r in rows:
            print(f"  {r[0]}  key={r[1]}  model={r[2]}  endpoint={r[3]}  cost={r[4]:.6f}")
    else:
        print("  (没有非 test1 的 usage_logs)")

    conn.close()
    print()
    print("🔚 诊断完成。请将以上输出发给我，我来分析根因。")


if __name__ == "__main__":
    main()
