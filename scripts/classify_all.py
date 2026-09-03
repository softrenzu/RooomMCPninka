import csv
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SRC = DATA / "latest.json"
OUT_CSV = DATA / "eligibility.csv"
OUT_MD = DATA / "eligibility.md"
OUT_SUMMARY = DATA / "eligibility_summary.json"
API = "https://api.jgrants-portal.go.jp/exp/v2/public/subsidies/id/{id}"
JST = ZoneInfo("Asia/Tokyo")

# ROOOMTECH株式会社の確認済み基本属性
PROFILE = {
    "head_office": "東京都国立市",
    "employees": 0,
    "capital_yen": 10000,
    "sme": True,
    "businesses": ["宿泊業", "民泊運営", "不動産", "AI", "IT", "DX", "Webシステム開発"],
    # 本店・施設の存在を確認済み。ただし各制度の「事業所」定義を満たすかは別途確認する。
    "known_prefectures": ["東京都", "京都府", "神奈川県", "愛知県"],
}

EXCLUDED_APPLICANT_PATTERNS = [
    (r"医療機関|病院|診療所|薬局|救命救急|歯科", "医療機関等向け"),
    (r"介護|福祉施設|障害福祉|訪問看護|老人ホーム", "介護・福祉事業者向け"),
    (r"保育所|幼稚園|認定こども園|学校法人|大学|高等学校|小学校|中学校", "教育・保育機関向け"),
    (r"農業者|農業法人|農林|畜産|酪農|園芸|水田|稲作|農地", "農業関係者向け"),
    (r"漁業者|水産業|漁船|養殖", "漁業・水産関係者向け"),
    (r"林業者|森林組合|木材産業", "林業関係者向け"),
    (r"酒類業|酒造|清酒|焼酎|ワイナリー|醸造", "酒類事業者向け"),
    (r"タクシー事業者|バス事業者|鉄道事業者|海運事業者|船舶事業者", "特定運輸事業者向け"),
    (r"地方公共団体|自治体向け|市町村向け|都道府県向け", "自治体等向け"),
    (r"商店街組合|商工会議所|商工会のみ|協同組合のみ", "特定団体向け"),
]

# ROOOMTECHの事業と直接つながりやすいテーマ
POSITIVE_PATTERNS = [
    r"AI|人工知能|生成AI|DX|デジタル|IT導入|システム|ソフトウェア|情報通信|サイバー",
    r"宿泊|旅館|ホテル|観光|インバウンド|民泊",
    r"省エネ|再エネ|太陽光|蓄電池|脱炭素|ゼロエミ|GX|環境|CO2|省CO2",
    r"中小企業|小規模事業者|スタートアップ|新事業|事業転換|販路|海外展開|知財|特許|研究開発|実証|設備導入|生産性|防災",
]

SPECIAL_CONDITION_PATTERNS = [
    (r"共同申請|共同提案|コンソーシアム|産学官|大学等と連携|複数者で", "共同体・連携要件の可能性"),
    (r"認定事業者|登録事業者|指定事業者|許可事業者|免許事業者", "認定・登録・許認可要件の可能性"),
    (r"創業.{0,12}(未満|以内)|設立.{0,12}(未満|以内)", "創業・設立年数要件の可能性"),
    (r"売上高.{0,20}(以上|以下)|課税所得|付加価値額|賃上げ", "財務・賃上げ等の追加要件"),
]


def strip_html(s):
    if not s:
        return ""
    s = html.unescape(str(s))
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def as_text(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return " / ".join(as_text(x) for x in v)
    if isinstance(v, dict):
        return " / ".join(f"{k}:{as_text(val)}" for k, val in v.items())
    return str(v)


def parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None


def fmt_dt(s):
    d = parse_dt(s)
    return d.strftime("%Y-%m-%d %H:%M") if d else (s or "")


def geography(area):
    area = area or ""
    if "全国" in area or "東京都" in area or "関東・甲信越地方" in area:
        return "ok", "本店が東京都のため地域条件は一次通過"
    for p in PROFILE["known_prefectures"]:
        if p in area:
            return "check", f"{p}に関連施設はあるが、制度上の事業所要件を要確認"
    return "no", f"対象地域が{area or '不明'}で、確認済み本店・事業拠点条件に合わない"


def classify(item, detail_obj):
    title = as_text(detail_obj.get("title") or item.get("title"))
    detail = strip_html(detail_obj.get("detail"))
    catch = strip_html(detail_obj.get("subsidy_catch_phrase"))
    area = as_text(detail_obj.get("target_area_search") or item.get("target_area_search"))
    industry = as_text(detail_obj.get("industry"))
    purpose = as_text(detail_obj.get("use_purpose"))
    combined = " ".join([title, detail, catch, area, industry, purpose])

    geo, geo_reason = geography(area)
    if geo == "no":
        return "×", geo_reason, "地域"

    for pat, reason in EXCLUDED_APPLICANT_PATTERNS:
        # タイトルに明確に限定対象がある場合を強く除外。本文だけの場合は誤判定を避ける。
        if re.search(pat, title, re.I):
            return "×", reason, "対象者"

    # 公的機関・委託調査など、補助金というより公募案件のケース
    if re.search(r"調査業務|委託事業|委託先|受託者|企画競争|調達|請負", title):
        return "△", "補助金ではなく委託・調達型公募の可能性。受託要件を確認", "公募種別"

    positive = any(re.search(p, combined, re.I) for p in POSITIVE_PATTERNS)
    specials = []
    for pat, label in SPECIAL_CONDITION_PATTERNS:
        if re.search(pat, combined, re.I):
            specials.append(label)

    # 業種欄があり、ROOOMTECH関連業種が一切なく明確に別業種のみなら要確認
    if industry:
        related = any(x in industry for x in ["宿泊", "情報通信", "不動産", "サービス", "分類不能", "製造", "小売"])
        if not related and industry not in ["すべての業種", "全業種", "業種の制約なし"]:
            return "△", f"対象業種が「{industry}」。ROOOMTECHの業種該当性を要確認", "業種"

    if geo == "check":
        return "△", geo_reason, "地域"

    # 全国/東京で関連テーマが強く、本文に企業・中小企業・事業者等の一般応募者記載がある場合
    general_business = re.search(r"中小企業|小規模事業者|事業者|法人|企業|スタートアップ", combined)
    if positive and general_business and not specials:
        return "○", "基本属性と事業テーマが合致。公募要領の最終要件確認後に申請準備", "候補"

    if positive:
        reason = "事業テーマは関連するが、個別要件の確認が必要"
        if specials:
            reason += "（" + "、".join(dict.fromkeys(specials)) + "）"
        return "△", reason, "追加要件"

    return "△", "地域条件は通るが、ROOOMTECHとの事業適合性・応募者要件を詳細確認", "適合性"


def fetch_detail(sid):
    try:
        r = requests.get(API.format(id=sid), timeout=30, headers={"User-Agent": "RooomMCPninka/1.0"})
        r.raise_for_status()
        data = r.json()
        result = data.get("result") or []
        return (result[0] if result else {}), None
    except Exception as e:
        return {}, str(e)


def main():
    snap = json.loads(SRC.read_text(encoding="utf-8"))
    items = snap.get("items", [])
    rows = []
    errors = []
    now = datetime.now(JST)

    for idx, item in enumerate(items, 1):
        sid = item.get("id", "")
        detail, err = fetch_detail(sid)
        if err:
            errors.append({"id": sid, "error": err})
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
        days = round((d - now).total_seconds() / 86400, 1) if d else None
        rows.append({
            "No": idx,
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
        time.sleep(0.12)

    # 締切順を維持（latest.json自体が締切昇順）。念のためソート。
    rows.sort(key=lambda x: (x["締切"] or "9999", x["補助金_公募名"]))
    for i, row in enumerate(rows, 1):
        row["No"] = i

    fields = list(rows[0].keys()) if rows else []
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)

    def esc(s):
        return str(s if s is not None else "").replace("|", "｜").replace("\n", " ")
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
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    counts = {k: sum(1 for r in rows if r["判定"] == k) for k in ["○", "△", "×"]}
    urgent = [r for r in rows if r["判定"] != "×" and r["残日数"] is not None and r["残日数"] <= 7]
    summary = {
        "generated_at": datetime.now(JST).isoformat(),
        "source_count": len(items),
        "classified_count": len(rows),
        "counts": counts,
        "detail_api_errors": errors,
        "urgent_non_x_count": len(urgent),
        "urgent_non_x": urgent[:50],
        "profile": PROFILE,
        "note": "一次判定。○でも提出前に公募要領の応募資格・必要書類・重複受給・事業期間等を最終確認する。",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(rows), "counts": counts, "errors": len(errors)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
