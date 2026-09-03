import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from classify_all import classify, fmt_dt, parse_dt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
snap = json.loads((DATA / "latest.json").read_text(encoding="utf-8"))
now = datetime.now(ZoneInfo("Asia/Tokyo"))
rows = []
for item in snap.get("items", []):
    status, reason, reason_type = classify(item, {})
    d = parse_dt(item.get("acceptance_end_datetime"))
    rows.append({
        "判定": status,
        "締切": fmt_dt(item.get("acceptance_end_datetime")),
        "残日数": round((d-now).total_seconds()/86400,1) if d else "",
        "補助金_公募名": item.get("title", ""),
        "対象地域": item.get("target_area_search", ""),
        "従業員条件": item.get("target_number_of_employees", ""),
        "上限額円": item.get("subsidy_max_limit", ""),
        "判定理由": reason,
        "理由区分": reason_type,
        "JグランツID": item.get("id", ""),
        "URL": f"https://www.jgrants-portal.go.jp/subsidy/{item.get('id','')}",
    })
rows.sort(key=lambda r: (r["締切"] or "9999", r["補助金_公募名"]))
for i,r in enumerate(rows,1): r["No"] = i
fields = ["No","判定","締切","残日数","補助金_公募名","対象地域","従業員条件","上限額円","判定理由","理由区分","JグランツID","URL"]
with (DATA/"eligibility_quick.csv").open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
md=["# Jグランツ全件申請可否 一次判定（一覧APIベース）","",f"生成日時: {datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M JST')}","","|No|判定|締切|公募名|地域|上限額円|理由|ID|","|---:|:---:|---|---|---|---:|---|---|"]
def esc(v): return str(v if v is not None else "").replace("|","｜").replace("\n"," ")
for r in rows:
    md.append(f"|{r['No']}|{r['判定']}|{esc(r['締切'])}|{esc(r['補助金_公募名'])}|{esc(r['対象地域'])}|{esc(r['上限額円'])}|{esc(r['判定理由'])}|{esc(r['JグランツID'])}|")
(DATA/"eligibility_quick.md").write_text("\n".join(md)+"\n",encoding="utf-8")
counts={k:sum(1 for r in rows if r['判定']==k) for k in ['○','△','×']}
urgent=[r for r in rows if r['判定']!='×' and isinstance(r['残日数'],float) and r['残日数']<=7]
(DATA/"eligibility_quick_summary.json").write_text(json.dumps({"count":len(rows),"counts":counts,"urgent_non_x_count":len(urgent),"urgent_non_x":urgent[:100]},ensure_ascii=False,indent=2),encoding="utf-8")
print({"count":len(rows),"counts":counts})
