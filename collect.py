#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
田亩星链 · 数据采集脚本（静默运行，零 token）
- 每天由 crontab 调用；失败自动跳过并记日志，不影响下次
- 数据源：农业农村部 pfsc.agri.cn（蔬菜，需 AES 解密）+ KIFA 花拍在线（花卉，尽力而为）
- 依赖：仅标准库；AES 解密优先用 pycryptodome（hermes venv 自带），缺失时回退 openssl
"""
import sqlite3, json, urllib.request, base64, os, datetime, subprocess, ssl

UNVERIFIED_SSL = ssl._create_unverified_context()  # KIFA 证书链不被系统信任，仅对其免验证

BASE = os.path.expanduser("~/tianmu_starlink")
DB = os.path.join(BASE, "data", "prices.db")
LOG = os.path.join(BASE, "data", "collect.log")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
AES_KEY = b"7s9K$pG2xQ8zR5mB7vA3sD9fH2jW40cV"

# 云南市场 ID（来自 pfsc 市场列表接口；元谋不报这些品种已移除）
MARKETS = {
    "王旗营": "90238B410A02082400BD630E77906355",
    "通海金山": "76E4F160C163936CE040A8C020017257",
}
# 昆明本地大棚快销品 + 常见品种（ID 来自品种树接口，已实测王旗营/通海报价）
# 品种库参考：会农通小程序「晋宁产区采购」公开清单（用户2026-08-01手工整理）
# 仅模仿其品种选择（本地实际种植），数据全部取自农业农村部官方免费接口，不窃取竞品数据
VEGETABLES = {"生菜": 81, "油麦菜": 87, "小白菜": 80, "芥菜": 88,
              "芹菜": 109, "香菜": 86, "菠菜": 82, "胡萝卜": 100,
              "蒜苗": 97, "韭黄": 127, "韭菜": 95, "西兰花": 130,
              "洋白菜": 1451, "茴香": 98, "小葱": 1454, "荷兰豆": 151}
KIFA_BREEDS = {"玫瑰": 111, "康乃馨": 112, "非洲菊": 120}


def to_iso(ts):
    """把 KIFA 的 8 位时间串(如 20260801)规范成 ISO 日期(2026-08-01)。已 ISO 则原样返回。"""
    s = str(ts)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def http(url, data=None, headers=None, timeout=20, unverified=False):
    req = urllib.request.Request(url, data=data,
                                 headers=headers or {"User-Agent": UA})
    ctx = UNVERIFIED_SSL if unverified else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def aes_decrypt(data_str):
    """pfsc 价格接口解密：IV=原串前16字符，其余 base64 解码为密文，AES-256-CBC/PKCS7"""
    iv = data_str[:16].encode("utf-8")
    ct = base64.b64decode(data_str[16:])
    try:
        from Crypto.Cipher import AES as A
        from Crypto.Util.Padding import unpad
        return unpad(A.new(AES_KEY, A.MODE_CBC, iv).decrypt(ct), 16).decode("utf-8")
    except ImportError:
        subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-K", AES_KEY.hex(),
                        "-iv", iv.hex(), "-in", "/dev/stdin", "-out", "/tmp/tms_pt.bin",
                        "-nopad"], input=ct, check=True)
        pt = open("/tmp/tms_pt.bin", "rb").read()
        return pt[:-pt[-1]].decode("utf-8")


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS veg_prices("
              "ts TEXT, market TEXT, variety TEXT, price REAL, "
              "PRIMARY KEY(ts, market, variety))")
    c.execute("CREATE TABLE IF NOT EXISTS flower_prices("
              "ts TEXT, breed TEXT, avg_price REAL, highest REAL, "
              "PRIMARY KEY(ts, breed))")
    c.execute("CREATE TABLE IF NOT EXISTS kifa_index("
              "ts TEXT, price_index_a REAL, price_index_q REAL, "
              "PRIMARY KEY(ts))")
    c.commit()
    return c


def fetch_pfsc(c):
    headers = {"User-Agent": UA, "Referer": "https://pfsc.agri.cn/",
               "Content-Type": "application/json"}
    n_ok = 0
    for mname, mid in MARKETS.items():
        for vname, vid in VEGETABLES.items():
            url = ("https://pfsc.agri.cn/price_portal/index/getMarketReportPriceChart"
                   f"?marketIDs={mid}&varietyID={vid}")
            try:
                enc = json.loads(http(url, data=b"{}", headers=headers)).get("data")
                if not enc:
                    log(f"  {mname}/{vname}: 该市场不报此品种")
                    continue
                d = json.loads(aes_decrypt(enc))
                date = d.get("date")
                for i, m in enumerate(d.get("x", [])):
                    c.execute("INSERT OR REPLACE INTO veg_prices VALUES(?,?,?,?,?)",
                              (date, m, vname, float(d["y"][i]), "批发"))
                c.commit()
                n_ok += 1
            except Exception as e:
                log(f"  {mname}/{vname} 失败: {e}")
    log(f"pfsc 蔬菜采集完成：成功 {n_ok} 组")


def fetch_kifa(c):
    headers = {"User-Agent": UA, "Referer": "https://www.kifaonline.com.cn/",
               "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    base = "https://www.kifaonline.com.cn/"
    try:
        rows = json.loads(http(base + "kIFAPriceIndex.do?method=getInfo&timeSetString="
                               + datetime.date.today().strftime("%Y%m") + "&tag=0",
                               headers=headers, unverified=True))
        n = 0
        for item in rows:
            for r in item.get("childs", []):
                c.execute("INSERT OR REPLACE INTO kifa_index VALUES(?,?,?)",
                          (to_iso(r["timeString"]), r.get("priceIndexA"), r.get("priceIndexQ")))
                n += 1
        c.commit()
        log(f"KIFA 价格指数：{n} 条")
    except Exception as e:
        log(f"KIFA 指数失败（可能被 WAF 拦，下次再试）: {e}")
    for bname, bid in KIFA_BREEDS.items():
        try:
            rows = json.loads(http(base + f"breedQuotation.do?method=getInfo&breed={bid}",
                                   headers=headers, unverified=True))
            for r in rows:
                c.execute("INSERT OR REPLACE INTO flower_prices VALUES(?,?,?,?)",
                          (to_iso(r["timeString"]), bname, r.get("avgPrice"), r.get("highestPrice")))
            c.commit()
            log(f"KIFA {bname}：{len(rows)} 条")
        except Exception as e:
            log(f"KIFA {bname} 失败（可能被 WAF 拦，下次再试）: {e}")


def main():
    import sys
    kifa_only = "--kifa-only" in sys.argv
    c = init_db()
    if kifa_only:
        # 仅补采 KIFA（价格指数 + 花卉），用于 19:30 等当天数据落库后的补采
        # 避免 12:00 采 KIFA 时当天拍卖数据未出、拿到前一天数据覆盖之前行的问题
        log("=== 采集开始（--kifa-only，仅 KIFA）===")
        fetch_kifa(c)
        log("=== 采集结束（--kifa-only）===")
        return
    log("=== 采集开始 ===")
    fetch_pfsc(c)
    fetch_kifa(c)
    log("=== 采集结束 ===")


if __name__ == "__main__":
    main()
