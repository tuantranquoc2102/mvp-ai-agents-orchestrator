#!/usr/bin/env python3
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path


REQUIRED_ENV = (
    "CLAUDE_CODE_ENABLE_TELEMETRY",
    "OTEL_METRICS_EXPORTER",
    "OTEL_LOGS_EXPORTER",
    "OTEL_LOG_TOOL_DETAILS",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_RESOURCE_ATTRIBUTES",
    "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE",
)


def build_env_block(user_name: str, team: str, bearer_token: str) -> dict[str, str]:
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_LOG_TOOL_DETAILS": "1",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.techvify.dev",
        "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer {bearer_token}",
        "OTEL_RESOURCE_ATTRIBUTES": f"user.name={user_name},team={team}",
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative",
    }


def normalize(label: str, raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned != raw:
        print(f"NOTE: normalized {label} {raw!r} -> {cleaned!r}")
    return cleaned


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: python3 install.py <user_name> <team> <bearer_token>", file=sys.stderr)
        print("Example: python3 install.py kyle.nguyen tc abc123def456...", file=sys.stderr)
        return 1

    user_name = normalize("user_name", sys.argv[1])
    team = normalize("team", sys.argv[2])
    bearer_token = sys.argv[3].strip()
    if not user_name:
        print("ERROR: user_name argument is empty.", file=sys.stderr)
        return 1
    if not team:
        print("ERROR: team argument is empty.", file=sys.stderr)
        return 1
    if not bearer_token:
        print("ERROR: bearer_token argument is empty.", file=sys.stderr)
        return 1

    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing settings if present, else start fresh.
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                print(f"ERROR: {settings_path} exists but is not a JSON object", file=sys.stderr)
                return 1
        except json.JSONDecodeError as exc:
            print(f"ERROR: {settings_path} is not valid JSON: {exc}", file=sys.stderr)
            print("Fix the JSON manually or back it up and rerun.", file=sys.stderr)
            return 1
    else:
        settings = {}

    # Merge our env keys into any existing env block; preserve unrelated keys.
    existing_env = settings.get("env", {})
    if not isinstance(existing_env, dict):
        existing_env = {}
    existing_env.update(build_env_block(user_name, team, bearer_token))
    settings["env"] = existing_env

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    # Verify
    parsed = json.loads(settings_path.read_text(encoding="utf-8"))
    env = parsed.get("env", {})
    missing = [k for k in REQUIRED_ENV if k not in env]
    if missing:
        print(f"ERROR: post-write verification failed; missing keys: {missing}", file=sys.stderr)
        return 1

    print(f"OK: updated {settings_path}")
    print(f"    OS: {platform.system()} {platform.release()}")
    print(f"    user.name = {user_name}")
    print(f"    team = {team}")
    print(f"    bearer token (last 8 chars): ...{bearer_token[-8:]}")
    print(f"    {len(REQUIRED_ENV)} required env keys all present")
    print()
    print("IMPORTANT: quit any running 'claude' sessions, open a fresh terminal,")
    print("then run 'claude' to start emitting telemetry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
