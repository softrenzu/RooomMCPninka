from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "search.json"
REQUEST_PATH = ROOT / "request.json"
API_V1 = "https://api.jgrants-portal.go.jp/exp/v1/public"
API_V2 = "https://api.jgrants-portal.go.jp/exp/v2/public"
USER_AGENT = "rooomtech-jgrants-monitor/1.0 (+https://github.com/softrenzu/RooomMCPninka)"
ATTACHMENT_KEYS = ("application_guidelines", "outline_of_grant", "application_form")

DATA_DIR.mkdir(parents=True, exist_ok=True)


def now_info() -> dict[str, str]:
    utc = datetime.now(timezone.utc)
    tokyo = utc.astimezone(ZoneInfo("Asia/Tokyo"))
    return {
        "utc": utc.isoformat(),
        "tokyo": tokyo.isoformat(),
    }


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def api_get(url: str, params: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    last_error: Exception | None = None
    for attempt in range(retries):
        # 公開APIの利用上限 10 req/sec に余裕を持たせる。
        time.sleep(0.13)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(f"JグランツAPI取得失敗: {url}: {last_error}")


def validate_search(params: dict[str, Any]) -> dict[str, Any]:
    keyword = str(params.get("keyword", "")).strip()
    if not (2 <= len(keyword) <= 255):
        raise ValueError("keyword は2〜255文字で指定してください")

    acceptance = int(params.get("acceptance", 1))
    if acceptance not in (0, 1):
        raise ValueError("acceptance は0または1です")

    sort = str(params.get("sort", "created_date"))
    if sort not in {"created_date", "acceptance_start_datetime", "acceptance_end_datetime"}:
        raise ValueError("sort が不正です")

    order = str(params.get("order", "DESC")).upper()
    if order not in {"ASC", "DESC"}:
        raise ValueError("order が不正です")

    clean: dict[str, Any] = {
        "keyword": keyword,
        "acceptance": acceptance,
        "sort": sort,
        "order": order,
    }
    for key in ("use_purpose", "industry", "target_number_of_employees", "target_area_search"):
        value = params.get(key)
        if value:
            clean[key] = str(value)
    return clean


def search_subsidies(params: dict[str, Any]) -> dict[str, Any]:
    clean = validate_search(params)
    return api_get(f"{API_V1}/subsidies", clean)


def get_detail(subsidy_id: str) -> dict[str, Any]:
    subsidy_id = str(subsidy_id).strip()
    if not subsidy_id or len(subsidy_id) > 18 or not re.fullmatch(r"[A-Za-z0-9]+", subsidy_id):
        raise ValueError("補助金IDが不正です")
    return api_get(f"{API_V2}/subsidies/id/{urllib.parse.quote(subsidy_id, safe='')}")


def strip_attachment_data(value: Any) -> Any:
    if isinstance(value, list):
        return [strip_attachment_data(v) for v in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "data" and "name" in value:
                result[key] = "<base64 omitted>"
            else:
                result[key] = strip_attachment_data(item)
        return result
    return value


def detail_object(response: dict[str, Any]) -> dict[str, Any] | None:
    result = response.get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return result[0]
    return None


def extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    chunks: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n\n--- page {page_no} ---\n{text}")
    return "".join(chunks).strip() + "\n"


def extract_attachments(detail_response: dict[str, Any], subsidy_id: str) -> dict[str, Any]:
    item = detail_object(detail_response)
    summary: dict[str, Any] = {"subsidy_id": subsidy_id, "files": []}
    if not item:
        return summary

    out_dir = DATA_DIR / "request_text" / subsidy_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for key in ATTACHMENT_KEYS:
        attachment = item.get(key)
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "")
        data = attachment.get("data")
        entry: dict[str, Any] = {"type": key, "original_name": name}
        if not isinstance(data, str) or not data:
            entry["status"] = "no_data"
            summary["files"].append(entry)
            continue

        try:
            raw = base64.b64decode(data, validate=False)
        except Exception as exc:
            entry["status"] = "decode_error"
            entry["error"] = str(exc)
            summary["files"].append(entry)
            continue

        suffix = Path(name).suffix.lower()
        if suffix == ".pdf" or raw.startswith(b"%PDF"):
            try:
                text = extract_pdf_text(raw)
                text_path = out_dir / f"{key}.txt"
                text_path.write_text(text, encoding="utf-8", newline="\n")
                entry["status"] = "text_extracted"
                entry["text_path"] = str(text_path.relative_to(ROOT)).replace(os.sep, "/")
                entry["characters"] = len(text)
            except Exception as exc:
                entry["status"] = "pdf_extract_error"
                entry["error"] = str(exc)
        else:
            entry["status"] = "binary_not_extracted"
            entry["bytes"] = len(raw)
        summary["files"].append(entry)

    return summary


def snapshot() -> dict[str, Any]:
    config = read_json(CONFIG_PATH, {}) or {}
    keywords = config.get("keywords") or ["事業"]
    base_params = {
        "acceptance": config.get("acceptance", 1),
        "sort": config.get("sort", "created_date"),
        "order": config.get("order", "DESC"),
    }

    merged: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    successful_queries = 0

    for keyword in keywords:
        params = dict(base_params)
        params["keyword"] = keyword
        try:
            response = search_subsidies(params)
            successful_queries += 1
            for item in response.get("result", []) or []:
                if not isinstance(item, dict):
                    continue
                subsidy_id = str(item.get("id") or "").strip()
                if not subsidy_id:
                    continue
                if subsidy_id not in merged:
                    merged[subsidy_id] = dict(item)
                    merged[subsidy_id]["matched_keywords"] = []
                merged[subsidy_id]["matched_keywords"].append(keyword)
        except Exception as exc:
            errors.append({"keyword": str(keyword), "error": str(exc)})

    if successful_queries == 0:
        raise RuntimeError(f"すべてのJグランツ検索が失敗しました: {errors}")

    items = list(merged.values())
    items.sort(
        key=lambda x: (
            str(x.get("acceptance_end_datetime") or "9999"),
            str(x.get("title") or ""),
        )
    )

    seen_path = DATA_DIR / "seen_ids.json"
    seen_data = read_json(seen_path, {"ids": []}) or {"ids": []}
    seen_ids = set(seen_data.get("ids") or [])
    new_items = [item for item in items if item.get("id") not in seen_ids]
    seen_ids.update(str(item.get("id")) for item in items if item.get("id"))

    generated = now_info()
    latest = {
        "generated_at": generated,
        "source": "Jグランツ（jGrants）公開API / デジタル庁",
        "api": f"{API_V1}/subsidies",
        "acceptance": base_params["acceptance"],
        "keywords": keywords,
        "count": len(items),
        "successful_queries": successful_queries,
        "query_errors": errors,
        "items": items,
    }
    new_data = {
        "generated_at": generated,
        "count": len(new_items),
        "items": new_items,
    }

    write_json(DATA_DIR / "latest.json", latest)
    write_json(DATA_DIR / "new.json", new_data)
    write_json(seen_path, {"updated_at": generated, "ids": sorted(seen_ids)})
    write_csv(DATA_DIR / "latest.csv", items)
    return latest


def write_csv(path: Path, items: list[dict[str, Any]]) -> None:
    fields = [
        "id",
        "title",
        "institution_name",
        "target_area_search",
        "subsidy_max_limit",
        "acceptance_start_datetime",
        "acceptance_end_datetime",
        "target_number_of_employees",
        "matched_keywords",
    ]
    # Windows 11 / Excel で日本語を安全に開けるようUTF-8 BOM付き。
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            row = dict(item)
            if isinstance(row.get("matched_keywords"), list):
                row["matched_keywords"] = " / ".join(row["matched_keywords"])
            writer.writerow(row)


def process_request() -> dict[str, Any] | None:
    if not REQUEST_PATH.exists():
        return None
    request = read_json(REQUEST_PATH, {}) or {}
    mode = str(request.get("mode", "search")).strip().lower()
    generated = now_info()

    if mode == "search":
        response = search_subsidies(request)
        result = {
            "generated_at": generated,
            "request": request,
            "source": "Jグランツ（jGrants）公開API / デジタル庁",
            "response": response,
        }
    elif mode == "detail":
        subsidy_id = str(request.get("id", "")).strip()
        raw = get_detail(subsidy_id)
        extraction = None
        if bool(request.get("extract_attachments", False)):
            extraction = extract_attachments(raw, subsidy_id)
        result = {
            "generated_at": generated,
            "request": request,
            "source": "Jグランツ（jGrants）公開API / デジタル庁",
            "response": strip_attachment_data(raw),
            "attachment_extraction": extraction,
        }
    elif mode == "detail_batch":
        ids = request.get("ids") or []
        if not isinstance(ids, list) or not ids or len(ids) > 20:
            raise ValueError("detail_batch の ids は1〜20件の配列にしてください")
        responses = []
        for subsidy_id in ids:
            raw = get_detail(str(subsidy_id))
            responses.append(strip_attachment_data(raw))
        result = {
            "generated_at": generated,
            "request": request,
            "source": "Jグランツ（jGrants）公開API / デジタル庁",
            "responses": responses,
        }
    else:
        raise ValueError(f"未対応mode: {mode}")

    write_json(DATA_DIR / "query_result.json", result)
    return result


def main() -> int:
    status: dict[str, Any] = {
        "started_at": now_info(),
        "snapshot": None,
        "request": None,
        "errors": [],
    }
    try:
        latest = snapshot()
        status["snapshot"] = {"count": latest["count"], "query_errors": latest["query_errors"]}
    except Exception as exc:
        status["errors"].append({"phase": "snapshot", "error": str(exc)})

    try:
        req = process_request()
        if req is not None:
            status["request"] = {"mode": req.get("request", {}).get("mode", "search"), "status": "ok"}
    except Exception as exc:
        status["errors"].append({"phase": "request", "error": str(exc)})

    status["finished_at"] = now_info()
    write_json(DATA_DIR / "last_run.json", status)

    if status["errors"]:
        print(json.dumps(status, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
