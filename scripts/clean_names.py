#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 品种名清理（别名映射 + 黑名单 + 花卉括号归一）

背景：省厅源是"图片 → RapidOCR"，必然有误识；前端 /quotes 直接读库，
      所以**修名的正解在采集/DB 层**，不在前端。
依据：9-11 源图人工核实（见 research/品种名对照表_v1.csv / .xlsx）

用法：
  python3 clean_names.py <db路径>            # 干跑（默认，只打印计划，不改库）
  python3 clean_names.py <db路径> --apply    # 真正执行（自动先备份 .bak_<日期>）

⚠️ 纪律：不确定的一律不改（篱蒿菜 / 茴蒿菜 保留原样，等人工确认）
"""
import os
import shutil
import sqlite3
import sys
import datetime

# ── 已确认的改名（9-11 源图核实：源图正确、我方 OCR 误识）──
RENAME_VEG = {
    '虹豆': '豇豆',        # 源图写「豇豆」
    '大莞要': '大芫荽',    # 源图写「大芫荽」
    '菏蒿菜': '茼蒿菜',    # 源图写「茼蒿菜」
}
# 源图本身就这么写 / 人工未确认 → 一律不动
HOLD_VEG = ['篱蒿菜', '茴蒿菜']
# 黑名单：表头、OCR 碎片（非品种）
DROP_VEG = ['易量（吨)', '易量（吨）', '一', '豆']


def norm_flower(name):
    s = (name or '').strip().replace('，', '').replace('（', '(').replace('）', ')')
    return s


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    db = sys.argv[1]
    apply = '--apply' in sys.argv
    if not os.path.exists(db):
        print(f'❌ 找不到库：{db}')
        return 1

    if apply:
        bak = f'{db}.bak_{datetime.date.today():%Y%m%d}_cleannames'
        if not os.path.exists(bak):
            shutil.copy2(db, bak)
            print(f'✅ 已备份 → {bak}')
        else:
            print(f'ℹ️ 备份已存在 → {bak}（跳过）')

    con = sqlite3.connect(db)
    c = con.cursor()
    plan = []

    # 1) 蔬菜改名
    for old, new in RENAME_VEG.items():
        rows = c.execute("SELECT substr(ts,1,10), name, price, qty FROM nync_veg_prices WHERE name=?", (old,)).fetchall()
        if not rows:
            continue
        # 目标名是否同日已有记录（会撞主键 ts+name）
        collide = 0
        for ts, _, _, _ in rows:
            if c.execute("SELECT 1 FROM nync_veg_prices WHERE ts=? AND name=?", (ts, new)).fetchone():
                collide += 1
        plan.append(('蔬菜改名', old, new, f'{len(rows)} 条（其中 {collide} 条目标名同日已存在 → 删除重复，保留目标行）'))

    # 2) 蔬菜剔除
    for name in DROP_VEG:
        rows = c.execute("SELECT substr(ts,1,10) FROM nync_veg_prices WHERE name=?", (name,)).fetchall()
        if rows:
            plan.append(('蔬菜剔除', name, '—', f'{len(rows)} 条（{rows[0][0]} ~ {rows[-1][0]}）'))

    # 3) 花卉括号归一（全角→半角）
    flower_groups = {}
    for (nm,) in c.execute("SELECT DISTINCT name FROM nync_flower_prices"):
        flower_groups.setdefault(norm_flower(nm), []).append(nm)
    for canon, raws in sorted(flower_groups.items()):
        for r in raws:
            if r != canon:
                n = c.execute("SELECT count(*) FROM nync_flower_prices WHERE name=?", (r,)).fetchone()[0]
                plan.append(('花卉归一', r, canon, f'{n} 条'))

    print('=' * 70)
    print(f'{"【干跑】" if not apply else "【执行】"}库：{db}')
    print('=' * 70)
    for kind, src, dst, note in plan:
        print(f'  [{kind}] {src} → {dst}   {note}')
    if not plan:
        print('  （无需改动）')
    print(f'\n保留不动（待人工确认）：{HOLD_VEG}')

    if apply:
        changed = 0
        # 改名：先删同日撞车的目标行，再 UPDATE
        for old, new in RENAME_VEG.items():
            rows = c.execute("SELECT ts FROM nync_veg_prices WHERE name=?", (old,)).fetchall()
            for (ts,) in rows:
                c.execute("DELETE FROM nync_veg_prices WHERE ts=? AND name=?", (ts, new))
            cur = c.execute("UPDATE nync_veg_prices SET name=? WHERE name=?", (new, old))
            changed += cur.rowcount
        for name in DROP_VEG:
            cur = c.execute("DELETE FROM nync_veg_prices WHERE name=?", (name,))
            changed += cur.rowcount
        for canon, raws in flower_groups.items():
            for r in raws:
                if r == canon:
                    continue
                rows = c.execute("SELECT ts FROM nync_flower_prices WHERE name=?", (r,)).fetchall()
                for (ts,) in rows:
                    c.execute("DELETE FROM nync_flower_prices WHERE ts=? AND name=?", (ts, canon))
                cur = c.execute("UPDATE nync_flower_prices SET name=? WHERE name=?", (canon, r))
                changed += cur.rowcount
        con.commit()
        print(f'\n✅ 共影响 {changed} 行，已提交')

    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
