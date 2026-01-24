#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


def load_accounts(raw: str):
    if not raw:
        raise ValueError("HF_ACCOUNTS_JSON is required and must be valid JSON.")

    data = json.loads(raw)
    if isinstance(data, dict) and "accounts" in data:
        accounts = data["accounts"]
    else:
        accounts = data

    if not isinstance(accounts, list):
        raise ValueError("HF_ACCOUNTS_JSON must be a JSON array or {\"accounts\": [...]}.\n")

    normalized = []
    for item in accounts:
        if isinstance(item, str):
            token = item.strip()
            username = None
            folder = None
        elif isinstance(item, dict):
            token = (item.get("token") or item.get("api_key") or item.get("key") or "").strip()
            username = (item.get("username") or item.get("account") or item.get("user") or "").strip() or None
            folder = (item.get("folder") or "").strip() or None
        else:
            raise ValueError("Each account entry must be a token string or an object.")

        if not token:
            raise ValueError("Each account must include a token.")

        normalized.append(
            {
                "token": token,
                "username": username,
                "folder": folder,
            }
        )

    return normalized


def safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unknown"


def resolve_account(api: HfApi, entry: dict):
    whoami_name = None
    if not entry["username"] or not entry["folder"]:
        whoami = api.whoami(token=entry["token"])
        whoami_name = whoami.get("name") or whoami.get("user")

    author = entry["username"] or whoami_name
    if not author:
        raise ValueError("Unable to determine account name from token.")

    folder = entry["folder"] or author
    return author, safe_component(folder)


def sync_space(token: str, space_id: str, target_dir: Path):
    with tempfile.TemporaryDirectory() as tmp_base:
        tmp_dir = Path(tmp_base) / "space"
        snapshot_download(
            repo_id=space_id,
            repo_type="space",
            local_dir=str(tmp_dir),
            local_dir_use_symlinks=False,
            token=token,
        )

        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_dir), str(target_dir))


def format_link(target_dir: Path, report_dir: Path) -> str:
    rel_path = os.path.relpath(target_dir, report_dir)
    return rel_path.replace(os.sep, "/")


def normalize_error(message: str) -> str:
    text = " ".join(str(message).splitlines()).strip()
    if len(text) > 160:
        return text[:157] + "..."
    return text


def write_report(report_path: Path, root_dir: Path, records: list):
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(records)
    success_count = sum(1 for r in records if r["status"] == "success")
    empty_count = sum(1 for r in records if r["status"] == "empty")
    failure_count = sum(1 for r in records if r["status"] == "failed")

    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = []
    lines.append("# Sync Report")
    lines.append("")
    lines.append(f"- Generated at: {timestamp}")
    lines.append(f"- Root directory: `{root_dir.as_posix()}`")
    lines.append(
        f"- Total: {total} | Success: {success_count} | Empty: {empty_count} | Failed: {failure_count}"
    )
    lines.append("")
    lines.append("| Account | Space | Status | Synced Path |")
    lines.append("| --- | --- | --- | --- |")

    report_dir = report_path.parent
    for record in records:
        account = record["account"]
        space_id = record.get("space_id") or "-"
        status = record["status"]
        if status == "success":
            status_text = "Success"
        elif status == "empty":
            status_text = "No spaces"
        else:
            error = normalize_error(record.get("error") or "Unknown error")
            status_text = f"Failed: {error}"

        if record.get("target_dir"):
            link_path = format_link(record["target_dir"], report_dir)
            link_label = record["target_dir"].as_posix()
            link_text = f"[{link_label}]({link_path})"
        else:
            link_text = "-"

        lines.append(f"| {account} | {space_id} | {status_text} | {link_text} |")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Sync Hugging Face Spaces into this repository.")
    parser.add_argument(
        "--root",
        default=os.getenv("SYNC_ROOT", "spaces"),
        help="Root folder for synced spaces.",
    )
    parser.add_argument(
        "--report",
        default=os.getenv("SYNC_REPORT", "reports/latest.md"),
        help="Path to write the sync report.",
    )
    parser.add_argument(
        "--accounts-json",
        default=os.getenv("HF_ACCOUNTS_JSON") or os.getenv("HF_ACCOUNTS"),
        help="JSON string describing accounts (from env HF_ACCOUNTS_JSON).",
    )
    args = parser.parse_args()

    try:
        accounts = load_accounts(args.accounts_json)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 1

    api = HfApi()
    root_dir = Path(args.root)
    report_path = Path(args.report)
    records = []

    for entry in accounts:
        try:
            author, folder = resolve_account(api, entry)
            account_dir = root_dir / folder
        except Exception as exc:
            records.append(
                {
                    "account": entry.get("username") or "unknown",
                    "status": "failed",
                    "error": normalize_error(exc),
                    "target_dir": None,
                }
            )
            continue

        try:
            spaces = api.list_spaces(author=author, token=entry["token"])
        except Exception as exc:
            records.append(
                {
                    "account": author,
                    "status": "failed",
                    "error": f"Failed to list spaces: {normalize_error(exc)}",
                    "target_dir": None,
                }
            )
            continue

        if not spaces:
            records.append(
                {
                    "account": author,
                    "space_id": "-",
                    "status": "empty",
                    "target_dir": None,
                }
            )
            continue

        spaces_sorted = sorted(spaces, key=lambda s: (s.id or "").lower())
        for space in spaces_sorted:
            space_id = space.id or ""
            space_name = space_id.split("/", 1)[1] if "/" in space_id else space_id
            target_dir = account_dir / safe_component(space_name)
            try:
                sync_space(entry["token"], space_id, target_dir)
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "success",
                        "target_dir": target_dir,
                    }
                )
            except Exception as exc:
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "failed",
                        "error": normalize_error(exc),
                        "target_dir": target_dir,
                    }
                )

    write_report(report_path, root_dir, records)
    print(f"Sync report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
