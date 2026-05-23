"""Fix billing data script — recalculate cost for usage_logs with cost=0.

This script fixes historical usage_logs where the streaming billing bug caused
cost=0 to be recorded for video generation requests. It recalculates the cost
based on video_seconds and the pricing table, and updates the api_key's
total_charged and balance accordingly.

Usage:
    python fix_billing_data.py [--dry-run] [--db-path PATH]

Default db path: ./data/billing.db
"""

import argparse
import sqlite3
import sys
from pathlib import Path


# Video pricing rates (must match pricing.py)
VIDEO_RATE_480P = 0.02  # per second
VIDEO_RATE_720P = 0.03  # per second


def video_cost(seconds: int, resolution: str = "720p") -> float:
    rate = VIDEO_RATE_480P if resolution == "480p" else VIDEO_RATE_720P
    return round(seconds * rate, 4)


def main():
    parser = argparse.ArgumentParser(description="Fix billing data with cost=0")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要修改的内容，不实际写入")
    parser.add_argument("--db-path", default="./data/billing.db", help="billing.db 路径")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Step 1: 查找所有 cost=0 但 video_seconds > 0 的记录
    rows = conn.execute("""
        SELECT id, api_key, key_name, model, video_seconds, cost, endpoint
        FROM usage_logs
        WHERE cost = 0 AND video_seconds > 0 AND status = 'success'
        ORDER BY created_at
    """).fetchall()

    if not rows:
        print("✅ 没有需要修复的记录（没有 cost=0 且 video_seconds>0 的 usage log）")
        conn.close()
        return

    print(f"📊 找到 {len(rows)} 条需要修复的记录:\n")
    print(f"{'ID':>40s}  {'Key Name':>15s}  {'Model':>25s}  {'Seconds':>7s}  {'Old Cost':>10s}  {'New Cost':>10s}")
    print("-" * 120)

    # Group corrections by api_key
    key_corrections: dict[str, float] = {}  # api_key -> total cost to charge
    updates: list[tuple[float, str]] = []  # (new_cost, log_id)

    for row in rows:
        new_cost = video_cost(row["video_seconds"], "720p")  # default resolution
        print(f"{row['id']:>40s}  {row['key_name']:>15s}  {row['model']:>25s}  {row['video_seconds']:>7d}  {row['cost']:>10.6f}  {new_cost:>10.6f}")

        updates.append((new_cost, row["id"]))
        key_corrections[row["api_key"]] = key_corrections.get(row["api_key"], 0.0) + new_cost

    print(f"\n📋 需要修正的扣费汇总:")
    for api_key, total in key_corrections.items():
        # Get current balance
        kr = conn.execute("SELECT name, balance, total_charged FROM api_keys WHERE key = ?", (api_key,)).fetchone()
        if kr:
            new_balance = kr["balance"] - total
            new_charged = kr["total_charged"] + total
            print(f"  Key: {api_key[:12]}... ({kr['name']})")
            print(f"    当前余额: {kr['balance']:.4f} → 修正后: {new_balance:.4f}")
            print(f"    已消费:   {kr['total_charged']:.4f} → 修正后: {new_charged:.4f}")
            print(f"    补扣金额: {total:.4f}")
        else:
            print(f"  Key: {api_key[:12]}... (⚠️ 未找到对应 api_key 记录)")
            print(f"    补扣金额: {total:.4f}")

    if args.dry_run:
        print(f"\n🔍 [DRY RUN] 以上为预览，未做任何修改。去掉 --dry-run 参数以执行修复。")
        conn.close()
        return

    # Step 2: 执行修复
    confirm = input(f"\n⚠️  确认修复 {len(updates)} 条记录？(y/N): ").strip().lower()
    if confirm != "y":
        print("❌ 已取消")
        conn.close()
        return

    # Update usage_logs cost
    for new_cost, log_id in updates:
        conn.execute("UPDATE usage_logs SET cost = ? WHERE id = ?", (new_cost, log_id))

    # Update api_keys balance and total_charged
    for api_key, total in key_corrections.items():
        conn.execute(
            "UPDATE api_keys SET balance = balance - ?, total_charged = total_charged + ? WHERE key = ?",
            (total, total, api_key),
        )

    conn.commit()
    print(f"\n✅ 已修复 {len(updates)} 条 usage_logs 记录")
    print(f"✅ 已更新 {len(key_corrections)} 个 api_key 的余额")

    # Verify
    print(f"\n📊 修复后的 API Key 状态:")
    for api_key in key_corrections:
        kr = conn.execute("SELECT name, balance, total_charged FROM api_keys WHERE key = ?", (api_key,)).fetchone()
        if kr:
            print(f"  {kr['name']:>15s}  balance={kr['balance']:.4f}  charged={kr['total_charged']:.4f}")

    conn.close()


if __name__ == "__main__":
    main()
