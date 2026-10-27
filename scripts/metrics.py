"""Parse pgbench output and individual transaction logs; no third-party packages."""

import math
import re


def parse_pgbench(text):
    patterns = {
        "transactions": r"^number of transactions actually processed:\s*(\d+)",
        "failed": r"^number of failed transactions:\s*(\d+)",
        "avg_ms": r"^latency average\s*=\s*([0-9.]+)\s*ms",
        "tps": r"^tps\s*=\s*([0-9.]+)",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise ValueError(f"missing pgbench metric: {key}")
        result[key] = float(match[1]) if key in ("avg_ms", "tps") else int(match[1])
    if result["failed"]:
        raise ValueError(f"pgbench reported failed transactions: {result['failed']}")
    if result["transactions"] < 1 or result["tps"] <= 0:
        raise ValueError("pgbench did not complete successful transactions")
    if not all(math.isfinite(result[key]) for key in ("avg_ms", "tps")):
        raise ValueError("non-finite pgbench metrics")
    return result


def read_latencies(paths):
    latencies = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                fields = line.split()
                if len(fields) < 6:
                    raise ValueError(f"malformed transaction log at {path.name}:{number}")
                try:
                    microseconds = int(fields[2])
                except ValueError as error:
                    raise ValueError(
                        f"failed, skipped or invalid transaction at {path.name}:{number}"
                    ) from error
                if microseconds < 0:
                    raise ValueError("negative transaction latency")
                latencies.append(microseconds / 1000)
    if not latencies:
        raise ValueError("no individual transaction samples")
    return sorted(latencies)


def percentile(sorted_values, fraction):
    """Nearest-rank percentile; caller supplies sorted values."""
    if not sorted_values or not 0 < fraction <= 1:
        raise ValueError("expected non-empty values and 0 < fraction <= 1")
    return sorted_values[math.ceil(len(sorted_values) * fraction) - 1]
