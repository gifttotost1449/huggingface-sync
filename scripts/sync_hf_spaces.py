#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download


def parse_tokens(raw: str):
    raw = raw.strip()
    if not raw:
        return []

    if "," in raw:
        parts = raw.split(",")
    else:
        parts = raw.split()

    tokens = [part.strip() for part in parts if part.strip()]
    return tokens


def parse_name_list(raw: str | None):
    if not raw:
        return set()
    return set(parse_tokens(raw))


def get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def load_accounts(raw: str):
    if not raw:
        raise ValueError(
            "需要提供 HF_ACCOUNTS_JSON，可为 JSON 或英文逗号分隔的 token 列表。"
        )

    raw = raw.strip()
    accounts = None
    if raw.startswith("{") or raw.startswith("["):
        data = json.loads(raw)
        if isinstance(data, dict) and "accounts" in data:
            accounts = data["accounts"]
        else:
            accounts = data
    else:
        tokens = parse_tokens(raw)
        accounts = tokens

    if not isinstance(accounts, list):
        raise ValueError(
            "HF_ACCOUNTS_JSON 必须是 JSON 数组、{\"accounts\": [...]} 或英文逗号分隔的 token 列表。"
        )
    if not accounts:
        raise ValueError("HF_ACCOUNTS_JSON 未提供任何账号或 token。")

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
            raise ValueError("账号配置必须是 token 字符串或对象。")

        if not token:
            raise ValueError("每个账号都必须包含 token。")

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


def resolve_account(api: HfApi, entry: dict, retries: int, retry_delay: float):
    whoami_name = None
    if not entry["username"] or not entry["folder"]:
        whoami = with_retries(
            lambda: api.whoami(token=entry["token"]),
            retries,
            retry_delay,
            "获取账号信息",
        )
        whoami_name = whoami.get("name") or whoami.get("user")

    author = entry["username"] or whoami_name
    if not author:
        raise ValueError("无法从 token 获取账号名称。")

    folder = entry["folder"] or author
    return author, safe_component(folder)


def sync_space(token: str, space_id: str, target_dir: Path, retries: int, retry_delay: float):
    with tempfile.TemporaryDirectory() as tmp_base:
        tmp_dir = Path(tmp_base) / "space"
        with_retries(
            lambda: snapshot_download(
                repo_id=space_id,
                repo_type="space",
                local_dir=str(tmp_dir),
                local_dir_use_symlinks=False,
                token=token,
            ),
            retries,
            retry_delay,
            f"下载 {space_id}",
        )

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        replace_dir_atomic(tmp_dir, target_dir)


def format_link(target_dir: Path, report_dir: Path) -> str:
    rel_path = os.path.relpath(target_dir, report_dir)
    return rel_path.replace(os.sep, "/")


def normalize_error(message: str) -> str:
    text = " ".join(str(message).splitlines()).strip()
    if len(text) > 160:
        return text[:157] + "..."
    return text


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds:.1f}s"


def format_bytes(size: int | None) -> str:
    if size is None:
        return "-"
    if size < 1024:
        return f"{size} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def format_timestamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo:
            value = value.astimezone(dt.timezone.utc)
        return value.strftime("%Y-%m-%d %H:%M:%S UTC")
    text = str(value).strip()
    return text or None


def collect_dir_stats(path: Path) -> tuple[int, int]:
    file_count = 0
    total_size = 0
    for root, _, files in os.walk(path):
        for name in files:
            file_count += 1
            file_path = Path(root) / name
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue
    return file_count, total_size


def replace_dir_atomic(source_dir: Path, target_dir: Path):
    backup_dir = target_dir.with_name(f"{target_dir.name}.bak")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if target_dir.exists():
        shutil.move(str(target_dir), str(backup_dir))
    try:
        shutil.move(str(source_dir), str(target_dir))
    except Exception:
        if target_dir.exists():
            shutil.rmtree(target_dir)
        if backup_dir.exists():
            shutil.move(str(backup_dir), str(target_dir))
        raise
    else:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)


def with_retries(action, retries: int, delay: float, label: str):
    attempt = 0
    while True:
        try:
            return action()
        except Exception as exc:
            attempt += 1
            if attempt > retries:
                raise
            wait = delay * (2 ** (attempt - 1))
            print(
                f"{label} 失败，{wait:.1f}s 后重试（{attempt}/{retries}）: {normalize_error(exc)}",
                file=sys.stderr,
            )
            time.sleep(wait)


def load_meta(meta_path: Path) -> dict:
    if not meta_path.exists():
        return {"accounts": {}}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"accounts": {}}
    if not isinstance(data, dict):
        return {"accounts": {}}
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
    return {"accounts": accounts}


def save_meta(meta_path: Path, data: dict):
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_space_info(space) -> dict:
    if isinstance(space, dict):
        last_modified = format_timestamp(space.get("lastModified") or space.get("last_modified"))
        sha = space.get("sha")
        private = space.get("private")
        status = space.get("status")
    else:
        last_modified = format_timestamp(
            getattr(space, "lastModified", None) or getattr(space, "last_modified", None)
        )
        sha = getattr(space, "sha", None)
        private = getattr(space, "private", None)
        status = getattr(space, "status", None)
    visibility = None
    if private is not None:
        visibility = "私有" if private else "公开"
    return {
        "last_modified": last_modified,
        "sha": sha,
        "visibility": visibility,
        "space_status": str(status) if status is not None else None,
    }


def matches_filter(space_id: str, space_name: str, filters: set[str]) -> bool:
    return space_id in filters or space_name in filters


def compute_change(prev: dict | None, sha: str | None, last_modified: str | None, file_count: int | None, size_bytes: int | None) -> str:
    if not prev:
        return "首次"
    prev_sha = prev.get("sha")
    if sha and prev_sha:
        return "有更新" if sha != prev_sha else "无变化"
    prev_last = prev.get("last_modified")
    if last_modified and prev_last:
        return "有更新" if last_modified != prev_last else "无变化"
    prev_count = prev.get("file_count")
    prev_size = prev.get("size_bytes")
    if (
        file_count is not None
        and size_bytes is not None
        and prev_count is not None
        and prev_size is not None
    ):
        if file_count == prev_count and size_bytes == prev_size:
            return "无变化"
        return "有更新"
    return "未知"


def write_report(
    report_path: Path,
    root_dir: Path,
    records: list,
    include_filters: set[str],
    exclude_filters: set[str],
    retries: int,
    retry_delay: float,
    space_sleep: float,
    run_seconds: float,
):
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total = len(records)
    success_count = sum(1 for r in records if r["status"] == "success")
    empty_count = sum(1 for r in records if r["status"] == "empty")
    skipped_count = sum(1 for r in records if r["status"] == "skipped")
    failure_count = sum(1 for r in records if r["status"] == "failed")

    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    report_dir = report_path.parent
    account_groups = defaultdict(list)
    for record in records:
        account_groups[record["account"]].append(record)

    accounts_sorted = sorted(account_groups.keys(), key=lambda name: name.lower())

    def record_sort_key(record: dict):
        space_id = record.get("space_id") or ""
        is_summary = space_id in ("", "-")
        return (0 if is_summary else 1, space_id.lower())

    def format_space_name(space_id: str) -> str:
        if "/" in space_id:
            return space_id.split("/", 1)[1]
        return space_id

    def format_target_link(target_dir: Path | None):
        if not target_dir:
            return "-", False
        if target_dir.exists():
            link_path = format_link(target_dir, report_dir)
            link_label = target_dir.as_posix()
            return f"[{link_label}]({link_path})", True
        return "-", False

    lines = []
    lines.append("# 同步报告")
    lines.append("")
    lines.append(f"- 生成时间: {timestamp}")
    lines.append(f"- 根目录: `{root_dir.as_posix()}`")
    lines.append(f"- 账号数: {len(accounts_sorted)}")
    lines.append(
        f"- 记录数: {total} | 成功: {success_count} | 空: {empty_count} | 跳过: {skipped_count} | 失败: {failure_count}"
    )
    lines.append(f"- 运行耗时: {format_duration(run_seconds)}")
    if include_filters:
        lines.append(f"- 仅同步: {', '.join(sorted(include_filters))}")
    if exclude_filters:
        lines.append(f"- 排除: {', '.join(sorted(exclude_filters))}")
    lines.append(
        f"- 重试策略: {retries} 次 | 初始间隔: {retry_delay:.1f}s | 单空间间隔: {space_sleep:.1f}s"
    )
    lines.append("- 说明: 同步目录为本仓库路径，点击可直接跳转。")
    lines.append("")
    lines.append("## 账号总览")
    lines.append("")
    lines.append("| 账号 | 记录数 | 成功 | 无 Space | 跳过 | 失败 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for account in accounts_sorted:
        group = account_groups[account]
        group_total = len(group)
        group_success = sum(1 for r in group if r["status"] == "success")
        group_empty = sum(1 for r in group if r["status"] == "empty")
        group_skipped = sum(1 for r in group if r["status"] == "skipped")
        group_failed = sum(1 for r in group if r["status"] == "failed")
        lines.append(
            f"| {account} | {group_total} | {group_success} | {group_empty} | {group_skipped} | {group_failed} |"
        )

    for account in accounts_sorted:
        lines.append("")
        lines.append(f"## 账号: {account}")
        lines.append("")
        lines.append("| Space | 状态 | 同步目录 | 详情 |")
        lines.append("| --- | --- | --- | --- |")
        group = sorted(account_groups[account], key=record_sort_key)
        for record in group:
            space_id = record.get("space_id") or "-"
            space_name = format_space_name(space_id)
            status = record["status"]
            link_text, link_exists = format_target_link(record.get("target_dir"))

            detail_parts = []
            if space_id not in ("", "-") and space_name != space_id:
                detail_parts.append(f"ID: {space_id}")
            if record.get("changed"):
                detail_parts.append(f"变更: {record['changed']}")
            if record.get("last_modified"):
                detail_parts.append(f"更新时间: {record['last_modified']}")
            if record.get("sha"):
                detail_parts.append(f"SHA: {record['sha'][:8]}")
            if record.get("file_count") is not None:
                detail_parts.append(f"文件: {record['file_count']}")
            if record.get("size_bytes") is not None:
                detail_parts.append(f"大小: {format_bytes(record['size_bytes'])}")
            if record.get("sync_seconds") is not None:
                detail_parts.append(f"耗时: {format_duration(record['sync_seconds'])}")
            if record.get("visibility"):
                detail_parts.append(f"可见性: {record['visibility']}")
            if record.get("space_status"):
                detail_parts.append(f"Space 状态: {record['space_status']}")

            if status == "success":
                status_text = "成功"
                detail = "<br>".join(detail_parts) if detail_parts else "-"
            elif status == "empty":
                status_text = "无 Space"
                detail = "该账号暂无 Space"
            elif status == "skipped":
                status_text = "跳过"
                reason = record.get("skip_reason") or "已跳过"
                detail_parts.insert(0, reason)
                detail = "<br>".join(detail_parts) if detail_parts else reason
            else:
                status_text = "失败"
                error = normalize_error(record.get("error") or "未知错误")
                if link_exists:
                    detail_parts.insert(0, f"错误: {error}")
                    detail_parts.append("目录可能为上次同步内容")
                    detail = "<br>".join(detail_parts)
                else:
                    detail_parts.insert(0, f"错误: {error}")
                    detail = "<br>".join(detail_parts)

            lines.append(f"| {space_name} | {status_text} | {link_text} | {detail} |")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="同步 Hugging Face Spaces 到本仓库。")
    default_retries = get_env_int("SYNC_RETRIES", 2)
    default_retry_delay = get_env_float("SYNC_RETRY_DELAY", 2.0)
    default_space_sleep = get_env_float("SYNC_SPACE_SLEEP", 0.0)
    parser.add_argument(
        "--root",
        default=os.getenv("SYNC_ROOT", "sync"),
        help="同步结果的根目录。",
    )
    parser.add_argument(
        "--report",
        default=os.getenv("SYNC_REPORT", "reports/latest.md"),
        help="同步报告输出路径。",
    )
    parser.add_argument(
        "--accounts-json",
        default=os.getenv("HF_ACCOUNTS_JSON") or os.getenv("HF_ACCOUNTS"),
        help="账号配置的 JSON 字符串，或英文逗号分隔的 token 列表。",
    )
    parser.add_argument(
        "--include",
        default=os.getenv("SYNC_INCLUDE", ""),
        help="仅同步指定 Space（可写 space 或 owner/space，英文逗号分隔）。",
    )
    parser.add_argument(
        "--exclude",
        default=os.getenv("SYNC_EXCLUDE", ""),
        help="排除指定 Space（可写 space 或 owner/space，英文逗号分隔）。",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=default_retries,
        help="失败重试次数。",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=default_retry_delay,
        help="重试初始间隔（秒）。",
    )
    parser.add_argument(
        "--space-sleep",
        type=float,
        default=default_space_sleep,
        help="每个 Space 同步后的等待时间（秒）。",
    )
    args = parser.parse_args()

    include_filters = parse_name_list(args.include)
    exclude_filters = parse_name_list(args.exclude)
    retries = max(0, args.retries)
    retry_delay = max(0.0, args.retry_delay)
    space_sleep = max(0.0, args.space_sleep)
    run_timer = time.perf_counter()

    try:
        accounts = load_accounts(args.accounts_json)
    except Exception as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 1

    api = HfApi()
    root_dir = Path(args.root)
    report_path = Path(args.report)
    meta_path = report_path.parent / "meta.json"
    meta = load_meta(meta_path)
    meta_accounts = meta["accounts"]
    records = []

    for entry in accounts:
        try:
            author, folder = resolve_account(api, entry, retries, retry_delay)
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
            spaces = with_retries(
                lambda: api.list_spaces(author=author, token=entry["token"]),
                retries,
                retry_delay,
                "获取 Space 列表",
            )
        except Exception as exc:
            records.append(
                {
                    "account": author,
                    "status": "failed",
                    "error": f"无法获取 Space 列表: {normalize_error(exc)}",
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
            space_info = extract_space_info(space)

            if include_filters and not matches_filter(space_id, space_name, include_filters):
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "skipped",
                        "skip_reason": "不在同步范围",
                        "target_dir": target_dir if target_dir.exists() else None,
                        **space_info,
                    }
                )
                if space_sleep > 0:
                    time.sleep(space_sleep)
                continue

            if exclude_filters and matches_filter(space_id, space_name, exclude_filters):
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "skipped",
                        "skip_reason": "已在排除列表",
                        "target_dir": target_dir if target_dir.exists() else None,
                        **space_info,
                    }
                )
                if space_sleep > 0:
                    time.sleep(space_sleep)
                continue

            sync_start = time.perf_counter()
            try:
                sync_space(entry["token"], space_id, target_dir, retries, retry_delay)
                sync_seconds = time.perf_counter() - sync_start
                file_count, size_bytes = collect_dir_stats(target_dir)
                prev_meta = meta_accounts.get(author, {}).get(space_id)
                changed = compute_change(
                    prev_meta,
                    space_info.get("sha"),
                    space_info.get("last_modified"),
                    file_count,
                    size_bytes,
                )
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "success",
                        "target_dir": target_dir,
                        "sync_seconds": sync_seconds,
                        "file_count": file_count,
                        "size_bytes": size_bytes,
                        "changed": changed,
                        **space_info,
                    }
                )
                account_meta = meta_accounts.setdefault(author, {})
                account_meta[space_id] = {
                    "space_id": space_id,
                    "sha": space_info.get("sha"),
                    "last_modified": space_info.get("last_modified"),
                    "file_count": file_count,
                    "size_bytes": size_bytes,
                    "synced_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                }
            except Exception as exc:
                sync_seconds = time.perf_counter() - sync_start
                records.append(
                    {
                        "account": author,
                        "space_id": space_id,
                        "status": "failed",
                        "error": normalize_error(exc),
                        "target_dir": target_dir,
                        "sync_seconds": sync_seconds,
                        **space_info,
                    }
                )
            if space_sleep > 0:
                time.sleep(space_sleep)

    run_seconds = time.perf_counter() - run_timer
    save_meta(meta_path, {"accounts": meta_accounts})
    write_report(
        report_path,
        root_dir,
        records,
        include_filters,
        exclude_filters,
        retries,
        retry_delay,
        space_sleep,
        run_seconds,
    )
    print(f"同步报告已写入 {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
