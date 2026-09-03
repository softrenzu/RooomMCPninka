import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from classify_all import classify, fmt_dt, parse_dt, PROFILE

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SRC = DATA / "latest.json"
OUT_CSV = DATA / "eligibility.csv"
OUT_MD = DATA / "eligibility.md"
OUT_SUMMARY = DATA / "eligibility_summary.json"
API = "https://api.jgrants-portal.go.jp/exp/v2/public/subsidies/id/{id}"
JST = ZoneInfo("Asia/Tokyo")

# 公式上限1秒10回より余裕を持たせて約7.5回/秒に制限
_rate_lock = threading.Lock()
_next_slot = 0.0

def rate_wait():
    global _next_slot
    with _rate_lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + 0.135
        wait = slot - now
    if wait > 0:
        time.sleep(wait)


def fetch_detail(item):
    sid = item.get("id", "")
    last_err = None
    for attempt in range(3):
        try:
            rate_wait()
            r = requests.get(API.format(id=sid), timeout=12, headers={"User-Agent": "RooomMCPninka/1.1"})
            if r.status_code == 429:
                time.sleep(1.0 + attempt)
                continue
            r.raise_for_status()
            data = r.json()
            result = data.get("result") or []
            return sid, (result[0] if result else {}), None
        except Exception as e:
            last_err = str(e)
            time.sleep(0.3 * (attempt + 1))
    return sid, {}, last_err


def esc(v):
    return str(v if v is not None else "").replace("|", "｜").replace("\n", " ")


def main():
    snap = json.loads(SRC.read_text(encoding="utf-8"))
    items = snap.get("items", [])
    by_id = {i.get("id", ""): i for i in items}
    details = {}
    errors = []

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch_detail, item) for item in items]
        for n, fut in enumerate(as_completed(futs), 1):
            sid, detail, err = fut.result()
            details[sid] = detail
            if err:
                errors.append({"id": sid, "error": err})
            if n % 50 == 0 or n == len(items):
                print(f"detail {n}/{len(items)} errors={len(errors)}", flush=True)

    now = datetime.now(JST)
    rows = []
    for item in items:
        sid = item.get("id", "")
        detail = details.get(sid, {})
        status, reason, reason_type = classify(item, detail)
        deadline = detail.get("acceptance_end_datetime") or item.get("acceptance_end_datetime")
        title = detail.get("title") or item.get("title") or ""
        area = detail.get("target_area_search") or item.get("target_area_search") or ""
        emp = detail.get("target_number_of_employees") or item.get("target_number_of_employees") or ""
        max_limit = detail.get("subsidy_max_limit")
        if max_limit in (None, ""):
            max_limit = item.get("subsidy_max_limit")
        url = detail.get("front_subsidy_detail_page_url") or f"https://www.jgrants-portal.go.jp/subsidy/{sid}"
        d = parse_dt(deadline)
        days = round((d - now).total_seconds()/86400, 1) if d else None
        rows.append({
            "No": 0,
            "判定": status,
            "締切": fmt_dt(deadline),
            "残日数": days,
            "補助金_公募名": title,
            "対象地域": area,
            "従業員条件": emp,
            "上限額円": max_limit if max_limit is not None else "",
            "判定理由": reason,
            "理由区分": reason_type,
            "JグランツID": sid,
            "URL": url,
        })

    rows.sort(key=lambda x: (x["締切"] or "9999", x["補助金_公募名"]))
    for i, r in enumerate(rows, 1): r["No"] = i
    fields = list(rows[0].keys()) if rows else []
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

    md = [
        "# Jグランツ全件申請可否 一次判定",
        "",
        f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M JST')}",
        "",
        "判定: ○=申請準備へ進める候補、△=公募要領の追加確認が必要、×=現時点で明確に対象外。",
        "",
        "|No|判定|締切|公募名|地域|上限額円|理由|JグランツID|",
        "|---:|:---:|---|---|---|---:|---|---|",
    ]
    for r in rows:
        md.append(f"|{r['No']}|{r['判定']}|{esc(r['締切'])}|{esc(r['補助金_公募名'])}|{esc(r['対象地域'])}|{esc(r['上限額円'])}|{esc(r['判定理由'])}|{esc(r['JグランツID'])}|")
    OUT_MD.write_text("\n".join(md)+"\n", encoding="utf-8")

    counts = {k: sum(1 for r in rows if r["判定"] == k) for k in ["○","△","×"]}
    urgent = [r for r in rows if r["判定"] != "×" and r["残日数"] is not None and r["残日数"] <= 7]
    summary = {
        "generated_at": datetime.now(JST).isoformat(),
        "source_count": len(items),
        "classified_count": len(rows),
        "counts": counts,
        "detail_api_errors": errors,
        "urgent_non_x_count": len(urgent),
        "urgent_non_x": urgent[:100],
        "profile": PROFILE,
        "note": "一次判定。○でも提出前に公募要領の応募資格・必要書類・重複受給・事業期間等を最終確認する。",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(rows), "counts": counts, "errors": len(errors)}, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
