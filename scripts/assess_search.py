"""Measure anonymous public search without collecting clicks or search analytics.

Uses only the standard library. First-pass timings do not prove a function cold
start; no deployment restart or cache clear is performed by this tool.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import http.client
import json
import math
from pathlib import Path
import statistics
import time
from urllib.parse import urlencode, urlsplit


DEFAULT_CASES = Path(__file__).parent / "data" / "search-evaluation.json"


def latency_summary(values):
    if not values:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    values = sorted(values)
    return {"count": len(values), "mean_ms": round(statistics.mean(values), 2),
            "p50_ms": round(statistics.median(values), 2),
            "p95_ms": round(values[math.ceil(len(values) * .95) - 1], 2), "max_ms": round(values[-1], 2)}


def expected_rank(results, expected):
    return next((index for index, row in enumerate(results, 1)
                 if any(all(row.get(key) == value for key, value in match.items()) for match in expected)), None)


class Client:
    def __init__(self, base, *, interval, timeout):
        self.url = urlsplit(base)
        if (self.url.scheme not in {"http", "https"} or not self.url.hostname or self.url.username
                or self.url.password or self.url.query or self.url.fragment or self.url.path not in {"", "/"}):
            raise ValueError("Site must be an http(s) origin without credentials or a path")
        factory = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
        self.connection = factory(self.url.hostname, self.url.port, timeout=timeout)
        self.interval, self.last_started = interval, 0

    def search(self, query):
        time.sleep(max(0, self.interval - (time.perf_counter() - self.last_started)))
        self.last_started = time.perf_counter()
        reused = self.connection.sock is not None
        start = time.perf_counter()
        status, error, payload, headers = None, None, {}, {}
        try:
            self.connection.request("GET", "/api/v1/search/unified?" + urlencode({"q": query, "limit": 20}),
                                    headers={"DNT": "1", "User-Agent": "gnu-jango-search-assessment/1.0"})
            response = self.connection.getresponse()
            status, headers = response.status, dict(response.getheaders())
            raw = response.read()
            elapsed = (time.perf_counter() - start) * 1000
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                error = "invalid_json"
            if status != 200:
                error = f"http_{status}"
            elif not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                error = "invalid_response"
        except (OSError, http.client.HTTPException) as exc:
            elapsed, error = (time.perf_counter() - start) * 1000, type(exc).__name__
            self.connection.close()
        return {"status": status, "error": error, "ms": round(elapsed, 2), "connection_reused": reused,
                "region": headers.get("X-Vercel-Id", headers.get("x-vercel-id", "")).split("::")[0],
                "payload": payload}

    def close(self):
        self.connection.close()


def run(dataset, *, repeats, interval, timeout, sites=None):
    clients = {name: Client(url, interval=interval, timeout=timeout) for name, url in dataset["sites"].items()
               if not sites or name in sites}
    cases = [case for case in dataset["cases"] if case["site"] in clients]
    if not cases:
        raise ValueError("No evaluation cases selected")
    samples = []
    try:
        for round_number in range(repeats + 1):
            for case in cases:
                sample = dict(clients[case["site"]].search(case["query"]))
                payload = sample.pop("payload")
                data = payload.get("data") if isinstance(payload, dict) else None
                meta = payload.get("meta") if isinstance(payload, dict) else None
                results = data.get("results") if isinstance(data, dict) else None
                if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
                    sample["error"], results = sample["error"] or "invalid_results", []
                rank = expected_rank(results, case["expected"])
                sample.update(case=case["id"], site=case["site"], category=case["category"], round=round_number,
                              rank=rank, hit_top3=not sample["error"] and rank is not None and rank <= 3,
                              total=meta.get("total") if isinstance(meta, dict) else None,
                              top3=[{key: row.get(key) for key in ("type", "title", "bo_table", "url")} for row in results[:3]])
                samples.append(sample)
    finally:
        for client in clients.values():
            client.close()
    first = [sample for sample in samples if sample["round"] == 0]
    groups = defaultdict(list)
    for sample in first:
        groups[sample["category"]].append(sample)
    quality = {name: {"cases": len(rows), "hits_top3": sum(row["hit_top3"] for row in rows),
                      "top3_rate": round(sum(row["hit_top3"] for row in rows) / len(rows), 4)}
               for name, rows in {"all": first, **groups}.items()}
    latency = {site: {phase: latency_summary([s["ms"] for s in samples if s["site"] == site
                    and (s["round"] == 0 if phase == "first_pass" else s["round"] > 0) and not s["error"]])
                     for phase in ("first_pass", "repeated")} for site in clients}
    return {"generated_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "sites": {name: dataset["sites"][name] for name in clients}, "repeats": repeats, "interval_seconds": interval,
            "cold_start_verified": False, "quality": quality, "latency": latency,
            "errors": sum(bool(sample["error"]) for sample in samples), "samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--site", action="append")
    parser.add_argument("--repeats", type=int, choices=range(11), default=3)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.interval < 0 or args.timeout <= 0:
        parser.error("interval must be nonnegative and timeout must be positive")
    dataset = json.loads(args.cases.read_text(encoding="utf-8-sig"))
    report = run(dataset, repeats=args.repeats, interval=args.interval, timeout=args.timeout, sites=args.site)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("quality", "latency", "errors")}, ensure_ascii=False, indent=2))
    return 0 if report["errors"] == 0 and all(q["top3_rate"] >= .8 for q in report["quality"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
