#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链 · 每周数据周报（零 token）
统计最近 7 天的采集情况：蔬菜、KIFA拍卖价、多德品名价、天气、预警、异动
由 cron 每周一 08:00 调用
"""
import sqlite3, os, datetime

BASE = "/home/ubuntu/tianmu_starlink"
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

    # 2a. KIFA 拍卖价（单独一列；玫瑰/康乃馨 2 大品属正常，不算异常）
    kifa = c.execute(
        "SELECT breed, avg_price, ts FROM flower_prices "
        "WHERE ts = (SELECT MAX(ts) FROM flower_prices)").fetchall()
    if kifa:
        kifa_str = "、".join(f"{b} {p}元" for b, p, _ in kifa[:6])
        lines.append(f"🏛️ KIFA拍卖：{kifa_str}（{kifa[0][2]}）")
    else:
        lines.append("🏛️ KIFA拍卖：本周无数据")

    # 2b. 多德品名价（⚠️ 2026-08-16 已标记废弃源，供追溯不再采信）
    dn = c.execute(
        "SELECT COUNT(DISTINCT ts), COUNT(*), MAX(ts) FROM dounan_prices WHERE ts >= ?",
        (week_ago,)).fetchone()
    if dn and dn[0]:
        lines.append(f"💐 多德品名价：本周采 {dn[0]} 天/ {dn[1]} 条（废弃源·仅追溯，勿采信）")
    else:
        lines.append("💐 多德品名价：废弃源，已停采 #️⃣")

    # 3. 天气
    w_rows = c.execute(
        "SELECT location, condition_text, temp_max FROM weather WHERE ts >= ?",
        (week_ago,)).fetchall()
    if w_rows:
        locs = len(set(r[0] for r in w_rows))
        lines.append(f"🌦️ 天气：{locs} 个地点持续记录")
    else:
        lines.append("🌦️ 天气：本周无数据")

    # 4. 本周预警
    alerts = c.execute(
        "SELECT type, title, detail FROM alerts WHERE ts >= ? ORDER BY id DESC LIMIT 10",
        (week_ago,)).fetchall()
    if alerts:
        lines.append("")
        lines.append("🔔 本周预警：")
        for t, title, detail in alerts[:5]:
            tag = "🌡️" if t == "weather" else "💰"
            lines.append(f" {tag} {title}")
    else:
        lines.append("🔔 本周预警：无")

    # 5. 价格异动 TOP
    lines.append("")
    lines.append("📈 本周价格异动 TOP3：")
    top = c.execute(
        "SELECT category, title, change_pct FROM alerts WHERE type='price' AND ts >= ? "
        "ORDER BY ABS(change_pct) DESC LIMIT 3", (week_ago,)).fetchall()
    if top:
        for cat, title, pct in top:
            lines.append(f" {title}")
    else:
        lines.append(" （本周无超阈值波动）")

    lines.append("")
    lines.append("数据每天 12:00 自动采集，周末愉快 🌾")

    c.close()
    print("\n".join(lines))

if __name__ == "__main__":
    main()
