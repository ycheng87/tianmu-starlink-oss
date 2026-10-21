#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 每周数据周报（零 token，no_agent 模式）
统计最近 7 天的采集情况：品种数、价格异动 TOP、天气、预警
用法: python3 weekly_report.py  由 cron 每周一 08:00 调用
"""
import sqlite3, os, datetime

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")

def main():
    c = sqlite3.connect(DB)
    today = datetime.date.today()
    week_ago = (today - datetime.timedelta(days=7)).isoformat()

    lines = ["📊 田亩星链 · 本周数据周报", "━━━━━━━━━━━━━━━"]

    # 1. 蔬菜采集概况
    veg_rows = c.execute(
        "SELECT ts, COUNT(DISTINCT variety) FROM veg_prices "
        "WHERE ts >= ? GROUP BY ts ORDER BY ts DESC", (week_ago,)).fetchall()
    if veg_rows:
        days = len(veg_rows)
        total_varieties = max(r[1] for r in veg_rows)
        latest_day = veg_rows[0][0]
        lines.append(f"🥬 蔬菜：本周采 {days} 天，覆盖 {total_varieties} 品种（最新 {latest_day}）")
    else:
        lines.append("🥬 蔬菜：本周无数据")

    # 2. 花卉
    fl_rows = c.execute(
        "SELECT COUNT(DISTINCT breed), MAX(ts) FROM flower_prices WHERE ts >= ?",
        (week_ago.replace("-", ""),)).fetchone()
    if fl_rows and fl_rows[0]:
        lines.append(f"🌹 花卉：{fl_rows[0]} 品种（最新 {fl_rows[1]}）")

    # 3. 天气
    w_rows = c.execute(
        "SELECT location, condition_text, temp_max FROM weather WHERE ts >= ?",
        (week_ago,)).fetchall()
    if w_rows:
        locs = len(set(r[0] for r in w_rows))
        lines.append(f"🌦️ 天气：{locs} 个地点持续记录")

    # 4. 本周预警
    alerts = c.execute(
        "SELECT type, title, detail FROM alerts WHERE ts >= ? ORDER BY id DESC LIMIT 10",
        (week_ago,)).fetchall()
    if alerts:
        lines.append("")
        lines.append("🔔 本周预警：")
        for t, title, detail in alerts[:5]:
            tag = "🌡️" if t == "weather" else "💰"
            lines.append(f"  {tag} {title}")
    else:
        lines.append("🔔 本周预警：无")

    # 5. 价格异动 TOP（本周最大涨跌幅）
    lines.append("")
    lines.append("📈 本周价格异动 TOP3：")
    rows = c.execute("""
        SELECT variety, market, price, change_pct FROM veg_prices
        WHERE ts = (SELECT MAX(ts) FROM veg_prices)
          AND change_pct IS NOT NULL
    """).fetchall() if False else []
    # veg_prices 没有 change_pct 列，从 alerts 取
    top = c.execute(
        "SELECT category, title, change_pct FROM alerts WHERE type='price' AND ts >= ? "
        "ORDER BY ABS(change_pct) DESC LIMIT 3", (week_ago,)).fetchall()
    if top:
        for cat, title, pct in top:
            lines.append(f"  {title}")
    else:
        lines.append("  （本周无超阈值波动）")

    lines.append("")
    lines.append("数据每天 12:00 自动采集，周末愉快 🌾")

    c.close()
    print("\n".join(lines))

if __name__ == "__main__":
    main()
