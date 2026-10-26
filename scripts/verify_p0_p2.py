#!/usr/bin/env python3
"""Repeat the P0-P2 automated checks without printing private session data."""

from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run_tests() -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode == 0


def compile_backend() -> bool:
    files = [
        BACKEND / "app.py",
        BACKEND / "parser.py",
        BACKEND / "discovery.py",
        BACKEND / "models.py",
        BACKEND / "registry.py",
        BACKEND / "providers" / "base.py",
        BACKEND / "providers" / "vscode_chat.py",
    ]
    try:
        for path in files:
            py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        print(exc, file=sys.stderr)
        return False
    return True


def api_smoke_test(user_dir: Path) -> dict:
    sys.path.insert(0, str(BACKEND))
    original_argv = sys.argv
    sys.argv = [original_argv[0], "--vscode_user_dir", str(user_dir)]
    try:
        import app
    finally:
        sys.argv = original_argv
    client = app.app.test_client()
    home = client.get("/")
    sessions = client.get("/api/v2/sessions")
    diagnostics = client.get("/api/v2/diagnostics")
    remote = client.get(
        "/api/v2/diagnostics", environ_base={"REMOTE_ADDR": "10.0.0.2"}
    )
    payload = sessions.get_json() or {}
    items = payload.get("sessions", [])
    return {
        "home_status": home.status_code,
        "sessions_status": sessions.status_code,
        "diagnostics_status": diagnostics.status_code,
        "unauthenticated_remote_diagnostics_status": remote.status_code,
        "session_count": len(items),
        "providers": dict(Counter(item.get("provider", "unknown") for item in items)),
        "content_statuses": dict(
            Counter(item.get("content_status", "unknown") for item in items)
        ),
        "workspace_count": len(payload.get("workspaces", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-dir",
        type=Path,
        default=Path("~/.config/Code/User").expanduser(),
    )
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    tests_ok = True if args.skip_tests else run_tests()
    compile_ok = compile_backend()
    smoke = api_smoke_test(args.user_dir.expanduser())
    result = {"tests_ok": tests_ok, "compile_ok": compile_ok, "api": smoke}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    statuses_ok = (
        smoke["home_status"] == 200
        and smoke["sessions_status"] == 200
        and smoke["diagnostics_status"] == 200
        and smoke["unauthenticated_remote_diagnostics_status"] == 403
    )
    return 0 if tests_ok and compile_ok and statuses_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
