"""Wait for the expected main revision on the two public search demo sites."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--attempts", type=int, default=15)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.revision) or not 1 <= args.attempts <= 30:
        parser.error("Expected a full commit SHA and 1..30 attempts")
    sites = json.loads((Path(__file__).parent / "data/search-evaluation.json").read_text(encoding="utf-8"))["sites"]
    pending = dict(sites)
    for attempt in range(args.attempts):
        for name, origin in list(pending.items()):
            # This file uses a fixed, reviewed dataset; never accept secret envs,
            # credentials or an arbitrary request-supplied destination.
            try:
                with urlopen(Request(origin + "/api/v1/status", headers={"DNT": "1", "Cache-Control": "no-cache"}), timeout=15) as response:
                    data = json.load(response)
                payload = data.get("data") if isinstance(data, dict) else None
                if isinstance(payload, dict) and payload.get("deployment_revision") == args.revision:
                    del pending[name]
            except (OSError, ValueError):
                pass
        if not pending:
            print("Expected deployment revision is live on both sites")
            return 0
        print("Waiting for release on: " + ", ".join(sorted(pending)))
        if attempt + 1 < args.attempts:
            time.sleep(20)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
