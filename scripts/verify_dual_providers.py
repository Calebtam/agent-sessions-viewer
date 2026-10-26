#!/usr/bin/env python3
"""Verify CodexProvider and CopilotCLIProvider without printing content."""

from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def source_digest(paths):
    digest = hashlib.sha256()
    count = 0
    for path in sorted(paths):
        if not path.is_file():
            continue
        count += 1
        digest.update(path.name.encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return count, digest.hexdigest()


def quiescent_files(paths, minimum_age_seconds=300):
    """Exclude sessions still being written by the current CLI conversation."""
    cutoff_ns = time.time_ns() - minimum_age_seconds * 1_000_000_000
    result = []
    for path in paths:
        try:
            if path.stat().st_mtime_ns <= cutoff_ns:
                result.append(path)
        except OSError:
            continue
    return result


def run_tests():
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def compile_sources():
    files = [
        BACKEND / "app.py",
        BACKEND / "models.py",
        BACKEND / "registry.py",
        BACKEND / "parser.py",
        *sorted((BACKEND / "providers").glob("*.py")),
        *sorted((BACKEND / "parsers").glob("*.py")),
    ]
    try:
        for path in files:
            py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--codex-root", type=Path, default=Path("~/.codex/sessions").expanduser()
    )
    parser.add_argument(
        "--copilot-root",
        type=Path,
        default=Path("~/.copilot/session-state").expanduser(),
    )
    args = parser.parse_args()
    codex_files = list(args.codex_root.expanduser().rglob("*.jsonl"))
    copilot_files = list(args.copilot_root.expanduser().glob("*/events.jsonl"))
    verified_codex_files = quiescent_files(codex_files)
    verified_copilot_files = quiescent_files(copilot_files)
    verified_files = {
        "codex": verified_codex_files,
        "copilot-cli": verified_copilot_files,
    }
    all_files = {"codex": codex_files, "copilot-cli": copilot_files}
    before = {
        key: source_digest(paths) for key, paths in verified_files.items()
    }
    tests_ok = True if args.skip_tests else run_tests()
    compile_ok = compile_sources()

    sys.path.insert(0, str(BACKEND))
    original_argv = sys.argv
    sys.argv = [
        original_argv[0],
        "--session_dir", str(args.codex_root),
        "--copilot_session_dir", str(args.copilot_root),
    ]
    try:
        import app
    finally:
        sys.argv = original_argv
    client = app.app.test_client()
    response = client.get("/api/v2/sessions")
    body = response.get_json() or {}
    sessions = body.get("sessions", [])
    private_fields = {"source_path", "source_id", "sourceFingerprint"}
    list_is_sanitized = all(
        private_fields.isdisjoint(item) for item in sessions
    )
    providers = Counter(item.get("provider") for item in sessions)
    detail_checks = {}
    for provider_id in ("codex", "copilot-cli"):
        item = next((x for x in sessions if x.get("provider") == provider_id), None)
        if item is None:
            detail_checks[provider_id] = {"status": None}
            continue
        detail = client.get("/api/v2/sessions/" + item["id"] + "?offset=0&limit=1")
        payload = detail.get_json() or {}
        detail_session = payload.get("session", {})
        detail_checks[provider_id] = {
            "status": detail.status_code,
            "total": payload.get("total"),
            "page_size": len(payload.get("turns", [])),
            "sanitized": private_fields.isdisjoint(detail_session),
        }
    remote = client.get(
        "/api/v2/sessions", environ_base={"REMOTE_ADDR": "10.0.0.2"}
    )
    copilot_page = client.get(
        "/api/v2/sessions?provider=copilot-cli&offset=0&limit=1"
    ).get_json() or {}
    pagination_ok = (
        len(copilot_page.get("sessions", [])) <= 1
        and copilot_page.get("offset") == 0
        and copilot_page.get("limit") == 1
        and copilot_page.get("total") == providers.get("copilot-cli", 0)
    )
    export_is_sanitized = False
    export_item = next(
        (item for item in sessions if item.get("provider") == "copilot-cli"), None
    )
    if export_item:
        exported = client.get(
            "/api/v2/export/" + export_item["id"] + "?format=json"
        )
        export_session = (exported.get_json() or {}).get("session", {})
        export_is_sanitized = (
            exported.status_code == 200
            and private_fields.isdisjoint(export_session)
        )
    codex_item = next(
        (item for item in sessions if item.get("provider") == "codex"), None
    )
    vscode_item = next(
        (item for item in sessions if item.get("provider") == "vscode-chat"), None
    )
    unauthorized_delete_status = None
    unsupported_delete_status = None
    if codex_item:
        unauthorized_delete_status = client.delete(
            "/api/v2/sessions/" + codex_item["id"],
            environ_base={"REMOTE_ADDR": "10.0.0.2"},
        ).status_code
    if vscode_item:
        unsupported_delete_status = client.delete(
            "/api/v2/sessions/" + vscode_item["id"]
        ).status_code
    delete_guards_ok = (
        unauthorized_delete_status == 403
        and unsupported_delete_status == 409
    )
    after = {
        key: source_digest(paths) for key, paths in verified_files.items()
    }
    result = {
        "tests_ok": tests_ok,
        "compile_ok": compile_ok,
        "list_status": response.status_code,
        "list_is_sanitized": list_is_sanitized,
        "pagination_ok": pagination_ok,
        "export_is_sanitized": export_is_sanitized,
        "delete_guards": {
            "ok": delete_guards_ok,
            "unauthorized_status": unauthorized_delete_status,
            "unsupported_provider_status": unsupported_delete_status,
        },
        "providers": dict(providers),
        "details": detail_checks,
        "remote_visible_sessions": len((remote.get_json() or {}).get("sessions", [])),
        "source_integrity": {
            key: {
                "file_count": len(all_files[key]),
                "checked_file_count": before[key][0],
                "active_file_count": len(all_files[key]) - before[key][0],
                "unchanged": before[key] == after[key],
            }
            for key in before
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    details_ok = all(
        value["status"] == 200 and value.get("sanitized")
        for value in detail_checks.values()
    )
    integrity_ok = all(value["unchanged"] for value in result["source_integrity"].values())
    return 0 if (
        tests_ok
        and compile_ok
        and response.status_code == 200
        and list_is_sanitized
        and pagination_ok
        and export_is_sanitized
        and delete_guards_ok
        and details_ok
        and integrity_ok
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
