import json
import sys

from jgrants_sync import now_info, snapshot, write_json, DATA_DIR


def main() -> int:
    status = {"started_at": now_info(), "errors": []}
    try:
        latest = snapshot()
        status["snapshot"] = {
            "count": latest["count"],
            "query_errors": latest["query_errors"],
        }
    except Exception as exc:
        status["errors"].append({"phase": "snapshot", "error": str(exc)})
    status["finished_at"] = now_info()
    write_json(DATA_DIR / "last_snapshot_run.json", status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 1 if status["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
