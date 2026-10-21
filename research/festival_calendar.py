#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田亩星链·节日事件日历（零依赖，cron 每天跑）
逻辑：检查未来 7 天内是否有节日（硬编码 2026-08~2027-12），
有则输出推送草稿（节日+历史规律引用）；无节日则静默（stdout 空）。
规律来源：预测可行性报告_2026-08-16.md（2020-2026 KIFA 指数 7 年验证）
用法：python3 festival_calendar.py   （cron no_agent：stdout 非空即推送）
"""
import datetime

# 节日表（阳历固定 + 农历换算硬编码，2027 由 lunarcalendar 计算）
FESTIVALS = {
    # 阳历固定
    (1, 1): ("元旦", "+9.2%前涨(71%)，节前4天见顶"),
    (2, 14): ("情人节", "2月全月最旺(+51.8%)，节前一周启动"),
    (3, 8): ("妇女节", "前7天平均+75.1%(86%上涨)，节前5天见顶"),
    (5, 20): ("5.20", "⚠️反向铁律：节后7天7年7跌(平均-50.6%)，别压货"),
    (9, 10): ("教师节", "前7天+11.5%(67%)，节后+19.9%(67%)"),
    (10, 1): ("国庆", "无稳定规律(33%)，不参考"),
    (12, 25): ("圣诞", "前弱(+6.8%)后强(+14.2%,83%)"),
    # 农历节日（已换算阳历）
    (2026, 8, 19): ("七夕", "前7天平均+77.2%，7年7涨(100%)，节前4-5天见顶🔥"),
    (2026, 9, 25): ("中秋", "前7天+35.4%(83%)，节前后1天见顶"),
    (2027, 2, 6): ("春节", "节前+14.3%(67%)，节后+49.4%(83%)延续到元宵"),
    (2027, 8, 8): ("七夕", "前7天平均+77.2%，7年7涨(100%)，节前4-5天见顶🔥"),
    (2027, 9, 15): ("中秋", "前7天+35.4%(83%)，节前后1天见顶"),
    # 母亲节=5月第2个周日、父亲节=6月第3个周日（每年算）
}
# 2026/2027 母亲节、父亲节
for y in (2026, 2027):
    for m, n, name, note in ((5, 2, "母亲节", "前7天平均+33.9%，7年7涨(100%)，节前4天见顶🔥"),
                             (6, 3, "父亲节", "前7天+20.9%(86%)，节前2天见顶")):
        d = datetime.date(y, m, 1)
        first_sun = d + datetime.timedelta(days=(6 - d.weekday()) % 7)
        FESTIVALS[(first_sun.month, first_sun.day)] = (name, note)


def main():
    today = datetime.date.today()
    upcoming = []
    for key, (name, note) in FESTIVALS.items():
        if len(key) == 3:  # (年,月,日)
            y, mm, dd = key
            if y != today.year:
                continue
        else:  # (月,日)
            mm, dd = key
        # 计算今年的日期
        try:
            fday = datetime.date(today.year, mm, dd)
        except ValueError:
            continue
        delta = (fday - today).days
        if 0 <= delta <= 7:
            upcoming.append((delta, name, note))
    upcoming.sort()
    if not upcoming:
        return  # 静默
    lines = ["🌸 田亩·节日事件日历", ""]
    for delta, name, note in upcoming:
        when = "今天" if delta == 0 else f"还有{delta}天"
        lines.append(f"📅 {name}（{when}）")
        lines.append(f"   {note}")
    lines.append("")
    lines.append("（规律来自2020-2026年KIFA指数统计，仅供参考，非买卖指令）")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
