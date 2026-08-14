#!/usr/bin/env python3
"""Notify IndexNow of the public discovery URLs without an account or secret."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "adapters" / "indexnow.json"
KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
SITE_PREFIX = "https://infotradescout.github.io/Selective-Intelligence/"


def load_config() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = config.get("key", "")
    if not KEY_RE.fullmatch(key):
        raise ValueError("IndexNow key must contain 8-128 letters, numbers, or dashes")
    if config.get("key_file") != f"{key}.txt":
        raise ValueError("IndexNow key filename does not match the configured key")
    if config.get("key_location") != SITE_PREFIX + config["key_file"]:
        raise ValueError("IndexNow key location is outside the published site path")
    endpoint = urlparse(config.get("endpoint", ""))
    if endpoint.scheme != "https" or not endpoint.netloc:
        raise ValueError("IndexNow endpoint must be an absolute HTTPS URL")
    urls = config.get("url_list")
    if not isinstance(urls, list) or not urls or len(urls) > 10_000:
        raise ValueError("IndexNow url_list must contain 1-10000 URLs")
    if len(urls) != len(set(urls)) or any(not url.startswith(SITE_PREFIX) for url in urls):
        raise ValueError("IndexNow URLs must be unique and remain under the verified site path")
    key_file = ROOT / "docs" / config["key_file"]
    if not key_file.exists() or key_file.read_text(encoding="utf-8").strip() != key:
        raise ValueError("Published IndexNow key file is missing or stale")
    return config


def payload(config: dict) -> dict:
    return {
        "host": config["host"],
        "key": config["key"],
        "keyLocation": config["key_location"],
        "urlList": config["url_list"],
    }


def verify_public_key(config: dict, timeout: float) -> None:
    with urllib.request.urlopen(config["key_location"], timeout=timeout) as response:
        body = response.read().decode("utf-8").strip()
        if response.status != 200 or body != config["key"]:
            raise RuntimeError("The public IndexNow key file is not live or does not match")


def submit(config: dict, timeout: float) -> int:
    verify_public_key(config, timeout)
    data = json.dumps(payload(config), separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        config["endpoint"],
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    if status not in {200, 202}:
        raise RuntimeError(f"IndexNow rejected the notification with HTTP {status}")
    receipt = {
        "status": status,
        "accepted": True,
        "url_count": len(config["url_list"]),
        "endpoint": config["endpoint"],
        "key_location": config["key_location"],
        "submitted_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "indexing_claimed": False,
    }
    print(json.dumps(receipt, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="validate and print the protocol payload without sending")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    config = load_config()
    if args.dry_run:
        print(json.dumps(payload(config), indent=2))
        return 0
    return submit(config, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
