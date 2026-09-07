#!/usr/bin/env python3
"""Load the exact audited SI refresh utility; never run unverified downloaded code."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import urllib.request

UTILITY_URL = "https://raw.githubusercontent.com/infotradescout/Selective-Intelligence/44b0c59ef908cbbae0a23f73719235b01cf75c07/tools/refresh_embedded_skill.py"
UTILITY_SHA256 = "0f503dab7fec84a1fa162a16fe880e31ee72c0fa5bc8769bdefc114a3195799b"
MAX_UTILITY = 65536


def main() -> int:
    try:
        request = urllib.request.Request(UTILITY_URL, headers={"User-Agent": "Selective-Intelligence-Refresh/1"})
        with urllib.request.urlopen(request, timeout=45) as response:
            content = response.read(MAX_UTILITY + 1)
        if len(content) > MAX_UTILITY or hashlib.sha256(content).hexdigest() != UTILITY_SHA256:
            raise ValueError("Refresh utility did not match its approved contents")
        namespace = {"__name__": "selective_intelligence_verified_refresh", "__file__": str(Path(__file__).absolute())}
        exec(compile(content, "verified-selective-intelligence-refresh", "exec"), namespace)
        return int(namespace["main"]())
    except (OSError, ValueError) as error:
        print("Selective Intelligence was not updated: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
