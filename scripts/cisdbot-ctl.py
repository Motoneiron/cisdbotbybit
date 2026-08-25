#!/usr/bin/env python3
"""CLI for CISD localhost control API (127.0.0.1:8765)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = os.environ.get("CISDBOT_CTL_URL", "http://127.0.0.1:8765")
DEFAULT_TOKEN_FILE = os.environ.get(
    "CISDBOT_CTL_TOKEN_FILE",
    "/opt/cisdbotbybit/.ctl_token",
)


def _load_token(path: str) -> str:
    if os.environ.get("CISDBOT_CTL_TOKEN"):
        return os.environ["CISDBOT_CTL_TOKEN"].strip()
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _req(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(err_body)
        except Exception:
            payload = {"error": err_body or str(e)}
        raise SystemExit(f"HTTP {e.code}: {payload.get('error', payload)}") from None
    except urllib.error.URLError as e:
        raise SystemExit(
            f"CTL недоступен ({url}): {e.reason}\n"
            f"Проверь: systemctl is-active cisdbot; journalctl -u cisdbot | grep CTL"
        ) from None


def main() -> int:
    p = argparse.ArgumentParser(description="CISD bot local control")
    p.add_argument(
        "command",
        choices=["status", "health", "start", "pause", "halt", "events", "token"],
    )
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    p.add_argument("-n", "--limit", type=int, default=20, help="events history limit")
    p.add_argument("--json", action="store_true", help="raw JSON")
    args = p.parse_args()

    if args.command == "token":
        print(_load_token(args.token_file))
        return 0

    token = _load_token(args.token_file)
    base = args.base.rstrip("/")

    if args.command == "status":
        data = _req("GET", f"{base}/api/status", token)
        print(data.get("text") if not args.json else json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "health":
        data = _req("GET", f"{base}/api/health", token)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "start":
        data = _req("POST", f"{base}/api/start", token, {})
        print(data.get("text") if not args.json else json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "pause":
        data = _req("POST", f"{base}/api/stop", token, {"mode": "pause"})
        print(data.get("text") if not args.json else json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "halt":
        data = _req("POST", f"{base}/api/stop", token, {"mode": "halt"})
        print(data.get("text") if not args.json else json.dumps(data, ensure_ascii=False, indent=2))
    elif args.command == "events":
        data = _req("GET", f"{base}/api/events/history?limit={args.limit}", token)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for ev in data.get("events") or []:
                print(f"#{ev['id']} [{ev.get('kind')}] {ev.get('text','').replace(chr(10), ' | ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
