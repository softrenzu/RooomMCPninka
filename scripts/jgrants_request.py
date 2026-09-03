from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from pypdf import PdfReader

from jgrants_sync import (
    DATA_DIR,
    REQUEST_PATH,
    detail_object,
    get_detail,
    now_info,
    read_json,
    search_subsidies,
    strip_attachment_data,
    write_json,
)

ATTACHMENT_KEYS = ("application_guidelines", "outline_of_grant", "application_form")


def extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    chunks = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        chunks.append(f"\n\n--- page {page_no} ---\n{text}")
    return "".join(chunks).strip() + "\n"


def normalize_attachments(value):
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def extract_attachments(detail_response: dict, subsidy_id: str) -> dict:
    item = detail_object(detail_response)
    summary = {"subsidy_id": subsidy_id, "files": []}
    if not item:
        return summary

    out_dir = DATA_DIR / "request_text" / subsidy_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for key in ATTACHMENT_KEYS:
        attachments = normalize_attachments(item.get(key))
        for index, attachment in enumerate(attachments, start=1):
            name = str(attachment.get("name") or "")
            data = attachment.get("data")
            entry = {"type": key, "index": index, "original_name": name}
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
                    text_path = out_dir / f"{key}_{index}.txt"
                    text_path.write_text(text, encoding="utf-8", newline="\n")
                    entry["status"] = "text_extracted"
                    entry["text_path"] = str(text_path.relative_to(DATA_DIR.parent)).replace("\\", "/")
                    entry["characters"] = len(text)
                except Exception as exc:
                    entry["status"] = "pdf_extract_error"
                    entry["error"] = str(exc)
            else:
                entry["status"] = "binary_not_extracted"
                entry["bytes"] = len(raw)
            summary["files"].append(entry)
    return summary


def process_request() -> dict:
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
    status = {"started_at": now_info(), "errors": []}
    try:
        result = process_request()
        status["request"] = {
            "mode": result.get("request", {}).get("mode", "search"),
            "status": "ok",
        }
    except Exception as exc:
        status["errors"].append({"phase": "request", "error": str(exc)})
    status["finished_at"] = now_info()
    write_json(DATA_DIR / "last_request_run.json", status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 1 if status["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
