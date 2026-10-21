#!/usr/bin/env bash
# 田亩星链 · 状态上报脚本
# detect.py 跑完后调用：把最新状态写入 data/health.json 并 push 到 Gitee。
# 用法: bash ~/tianmu_starlink/health_report.sh
set -euo pipefail

BASE="$HOME/tianmu_starlink"
DB="$BASE/data/prices.db"
HEALTH="$BASE/data/health.json"
LOG="$BASE/logs/detect.log"
DETECT_PY="$BASE/detect.py"

# ── 1. 跑 detect.py（幂等，同一天同品种会先删再写） ──
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> detect.py 开始" >> "$LOG"
if ! cd "$BASE" && python3 "$DETECT_PY" >> "$LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: detect.py 失败" >> "$LOG"
    python3 - "$HEALTH" "$(date '+%Y-%m-%d %H:%M:%S')" "detect_failed" <<'PY'
import json,sys,os
h={"detect_last_run":sys.argv[2],"alerts_last_ts":"ERROR","flower_last_date":"","veg_last_date":"","status":sys.argv[3]}
json.dump(h,open(sys.argv[1],"w"),ensure_ascii=False,indent=2)
PY
    exit 1
fi
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> detect.py 完成" >> "$LOG"

# ── 2. 生成 health.json ──
python3 - "$DB" "$HEALTH" "$(date '+%Y-%m-%d %H:%M:%S')" <<'PY'
import json,sys,sqlite3,datetime
from datetime import date, timedelta
db,out,run=sys.argv[1],sys.argv[2],sys.argv[3]
c=sqlite3.connect(db)
def one(q):
    try:
        return c.execute(q).fetchone()[0]
    except Exception:
        return None

def trading_days_between(d1, d2):
    """粗略估算两个日期之间的交易日数（跳过周末，不含法定节假日）。"""
    d1=date.fromisoformat(d1); d2=date.fromisoformat(d2)
    n=0; d=d1
    while d<d2:
        if d.weekday()<5:  # 周一~周五
            n+=1
        d+=timedelta(days=1)
    return n

today=date.today().isoformat()
flower_last=one("SELECT MAX(ts) FROM flower_prices") or ""
veg_last=one("SELECT MAX(ts) FROM veg_prices") or ""
# 花卉滞后检查：最新花卉日期与今天之间相隔的交易日数
flower_lag=0
flower_stale=""
if flower_last:
    try:
        flower_lag=trading_days_between(flower_last, today)
        # 康乃馨单独查（KIFA 延迟最明显的品种）
        carnation_last=one("SELECT MAX(ts) FROM flower_prices WHERE breed='康乃馨'") or ""
        c_lag=trading_days_between(carnation_last, today) if carnation_last else 0
        # 告警：花卉整体滞后>=2交易日，或康乃馨滞后>=3交易日
        if flower_lag>=2 or c_lag>=3:
            flower_stale=f"⚠️ 花卉数据滞后{flower_lag}交易日(康乃馨滞后{c_lag})"
    except Exception:
        flower_stale="⚠️ 花卉滞后计算异常"

# ⚠️ 多德品名价：废弃源(2026-08-16)价格变化检测。
#   对 dounan_prices 取最新两个交易日的 A 级价，按品名算日环比，
#   超过 ±10% 记为异常；同时识别连续多日价僵化(疑似采集不刷新)。
#   仅作健康观测输出到 health.json，不写 alerts、不采信此源。
duode_change=""
duode_big_count=0
duode_last_run=""
def duode_change_check():
    global duode_change, duode_big_count, duode_last_run
    try:
        dn_dates=[r[0] for r in c.execute(
            "SELECT DISTINCT ts FROM dounan_prices WHERE source LIKE '%废弃%' ORDER BY ts DESC LIMIT 2")]
        if len(dn_dates)<2:
            duode_change="多德废弃源·仅1天数据，无法比价"
            return
        d_old, d_new = dn_dates[1], dn_dates[0]
        duode_last_run=d_new
        # 取两日都有A级价的品名，算环比
        rows=c.execute("""
            SELECT a.name, a.price_a, b.price_a FROM
              (SELECT name, price_a FROM dounan_prices WHERE ts=? AND price_a IS NOT NULL) a
              JOIN (SELECT name, price_a FROM dounan_prices WHERE ts=? AND price_a IS NOT NULL) b
                ON a.name=b.name
        """,(d_old,d_new)).fetchall()
        big=[]
        for name,p_old,p_new in rows:
            if not p_old or not p_new or p_old==0:
                continue
            pct=(p_new-p_old)/p_old*100
            if abs(pct)>=10:
                big.append(f"{name} {pct:+.0f}%")
        duode_big_count=len(big)
        # 僵化检测：最新日 A 级价与上一交易日相比全无变化(>80% 品名价恒定)
        if rows and sum(1 for _,a,b in rows if a==b)/len(rows)>0.8:
            duode_change=f"⚠️ 多德价僵化({d_old}→{d_new} 超8成品名价恒定)"
        elif big:
            duode_change=f"多德波动: {len(big)}品名±10%+({','.join(big[:6])})"
        else:
            duode_change=f"多德价平稳({d_new} 无±10%品名)"
    except Exception as e:
        duode_change=f"多德检测异常:{e}"
duode_change_check()

health={
    "detect_last_run": run,
    "alerts_last_ts": one("SELECT MAX(ts) FROM alerts") or "",
    "flower_last_date": flower_last,
    "veg_last_date": veg_last,
    "flower_lag_days": flower_lag,
    "flower_stale": flower_stale,
    "duode_deprecated": True,
    "duode_last_date": duode_last_run,
    "duode_big_change_count": duode_big_count,
    "duode_change": duode_change,
    "status": "ok",
}
json.dump(health, open(out,"w"), ensure_ascii=False, indent=2)
print("health.json:", json.dumps(health, ensure_ascii=False))
PY

# ── 3. push 到 Gitee（提交 health.json + prices.db，不碰他人改动） ──
cd "$BASE"
# prices.db 供香港田亩双份核验重算涨跌幅(2026-08-14 小墨需求)：全量推(3.5MB 可接受)，
# 直接 add 原文件名，保证香港拉到的路径 = data/prices.db（勿改临时名，否则对方读不到）
git add data/health.json data/prices.db
# 强制 main 分支对应到 origin（远程为 origin）
if git diff --cached --quiet 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] health.json/prices.db 无变化，跳过提交" >> "$LOG"
else
    git commit -m "health: 状态上报+价格库 $(date +%F)（供双份核验）" >> "$LOG" 2>&1 || true
fi
# push 到 gitee：优先 gitee 别名，否则 origin
REMOTE="${GITEE_REMOTE:-gitee}"
git push "$REMOTE" main >> "$LOG" 2>&1 || git push origin main >> "$LOG" 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 状态上报完成" >> "$LOG"
