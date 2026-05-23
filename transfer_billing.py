"""Transfer billing script — Move all usage logs from test1 to grok-Evai and correct balances.

Usage:
    python transfer_billing.py [--dry-run] [--db-path PATH]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Transfer billing logs from test1 to grok-Evai")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要修改的内容，不实际写入")
    parser.add_argument("--db-path", default="./data/billing.db", help="billing.db 路径")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"❌ 数据库不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Step 1: 查找 test1 和 grok-Evai 的信息
    test1 = conn.execute("SELECT key, name, balance, total_charged FROM api_keys WHERE name = 'test1'").fetchone()
    grok_evai = conn.execute("SELECT key, name, balance, total_charged FROM api_keys WHERE name = 'grok-Evai'").fetchone()

    if not test1:
        print("❌ 未找到名为 'test1' 的 API Key")
        conn.close()
        sys.exit(1)

    if not grok_evai:
        print("❌ 未找到名为 'grok-Evai' 的 API Key")
        conn.close()
        sys.exit(1)

    test1_key = test1["key"]
    evai_key = grok_evai["key"]

    print("🔑 目标 Key 信息:")
    print(f"  test1:     Key={test1_key[:12]}... 余额={test1['balance']:.4f} 已扣={test1['total_charged']:.4f}")
    print(f"  grok-Evai: Key={evai_key[:12]}... 余额={grok_evai['balance']:.4f} 已扣={grok_evai['total_charged']:.4f}")

    # 计算初始总额 (balance + total_charged = initial_limit)
    test1_init = test1["balance"] + test1["total_charged"]
    evai_init = grok_evai["balance"] + grok_evai["total_charged"]

    # 查阅要移动的日志数量和总金额
    to_move = conn.execute("SELECT COUNT(*) as count, SUM(cost) as total_cost FROM usage_logs WHERE api_key = ?", (test1_key,)).fetchone()
    move_count = to_move["count"] or 0
    move_cost = to_move["total_cost"] or 0.0

    print(f"\n📦 待迁移统计:")
    print(f"  需要将 {move_count} 条消费记录从 test1 转移到 grok-Evai")
    print(f"  转移的账单总金额: ${move_cost:.6f}")

    if move_count == 0:
        print("✅ test1 下已无消费记录，无需转移。")
        conn.close()
        return

    # 计算转移后的新账目
    # test1 新状态：扣除移出的金额
    new_test1_charged = test1["total_charged"] - move_cost
    new_test1_balance = test1_init - new_test1_charged

    # grok-Evai 新状态：加上移入的金额
    new_evai_charged = grok_evai["total_charged"] + move_cost
    new_evai_balance = evai_init - new_evai_charged

    print(f"\n📋 账目变化预测:")
    print("  test1:")
    print(f"    当前余额: {test1['balance']:.4f} → 转移后: {new_test1_balance:.4f}")
    print(f"    当前已扣: {test1['total_charged']:.4f} → 转移后: {new_test1_charged:.4f}")
    print("  grok-Evai:")
    print(f"    当前余额: {grok_evai['balance']:.4f} → 转移后: {new_evai_balance:.4f}")
    print(f"    当前已扣: {grok_evai['total_charged']:.4f} → 转移后: {new_evai_charged:.4f}")

    if args.dry_run:
        print(f"\n🔍 [DRY RUN] 以上为预览，未做任何修改。去掉 --dry-run 参数以执行转移。")
        conn.close()
        return

    confirm = input(f"\n⚠️  确认执行转移，将这些记录归入 grok-Evai？(y/N): ").strip().lower()
    if confirm != "y":
        print("❌ 已取消")
        conn.close()
        return

    # 1. 转移使用日志
    conn.execute("""
        UPDATE usage_logs 
        SET api_key = ?, key_name = 'grok-Evai' 
        WHERE api_key = ?
    """, (evai_key, test1_key))

    # 2. 更新 api_keys 状态
    conn.execute("""
        UPDATE api_keys 
        SET balance = ?, total_charged = ? 
        WHERE key = ?
    """, (new_test1_balance, new_test1_charged, test1_key))

    conn.execute("""
        UPDATE api_keys 
        SET balance = ?, total_charged = ? 
        WHERE key = ?
    """, (new_evai_balance, new_evai_charged, evai_key))

    conn.commit()
    print(f"\n✅ 转移成功！已转移 {move_count} 条记录到 grok-Evai，并重新修正了双方账户余额。")
    conn.close()

if __name__ == "__main__":
    main()
