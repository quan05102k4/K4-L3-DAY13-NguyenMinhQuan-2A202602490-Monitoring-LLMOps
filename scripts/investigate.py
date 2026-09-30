"""Hỗ trợ bước Metrics -> Logs khi điều tra incident từ data/logs.jsonl.

1. Bảng theo phút (giờ VN): traffic, lỗi, latency P95, TTFT P95, cost, tokens_out, quality
   -> xác định metric bất thường và khoảng thời gian.
2. Breakdown theo feature -> feature nào bị ảnh hưởng.
3. Danh sách request bất thường kèm correlation_id -> dùng để tìm trace trên Langfuse
   (lọc Metadata correlation_id).

    python scripts/investigate.py
    python scripts/investigate.py --since 11:45 --until 12:10 --latency-ms 2000
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

VN_TZ = timezone(timedelta(hours=7))


def parse_clock(value: str | None, day: datetime) -> datetime | None:
    if not value:
        return None
    hour, minute = (int(part) for part in value.split(":"))
    return datetime.combine(day.date(), time(hour, minute), tzinfo=VN_TZ)


def default_latency_threshold() -> int:
    # Chỉ đọc ngưỡng từ file đề (nếu đã được release); không sửa file.
    path = REPO_ROOT / "config" / "challenge.json"
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["latency_threshold_ms"])
    except (OSError, ValueError, KeyError, TypeError):
        return 2000


def load(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            record["_vn"] = datetime.fromisoformat(record["ts"].replace("Z", "+00:00")).astimezone(VN_TZ)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        records.append(record)
    return records


def summarize(group: list[dict]) -> str:
    sent = [r for r in group if r.get("event") == "response_sent"]
    received = sum(1 for r in group if r.get("event") == "request_received")
    failed = sum(1 for r in group if r.get("event") == "request_failed")
    lat = [r["latency_ms"] for r in sent]
    ttft = [r["ttft_ms"] for r in sent]
    cost = mean(r["cost_usd"] for r in sent) if sent else 0.0
    tok = mean(r["tokens_out"] for r in sent) if sent else 0.0
    quality = mean(r["quality_score"] for r in sent) if sent else 0.0
    return (
        f"{received:>4} {failed:>4} {percentile(lat, 95):>8.0f} {percentile(ttft, 95):>6.0f} "
        f"{cost:>9.5f} {tok:>7.0f} {quality:>6.2f}"
    )


HEADER = f"{'req':>4} {'fail':>4} {'p95_ms':>8} {'ttft95':>6} {'avg_cost':>9} {'tok_out':>7} {'qual':>6}"


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Metrics -> Logs cho điều tra incident")
    parser.add_argument("--logs", type=Path, default=Path("data/logs.jsonl"))
    parser.add_argument("--since", help="HH:MM giờ VN")
    parser.add_argument("--until", help="HH:MM giờ VN")
    parser.add_argument("--latency-ms", type=int, default=None)
    parser.add_argument("--cost-usd", type=float, default=0.004)
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    records = load(args.logs)
    if not records:
        print(f"Không có log hợp lệ trong {args.logs}")
        return 1
    day = records[-1]["_vn"]
    since, until = parse_clock(args.since, day), parse_clock(args.until, day)
    records = [
        r for r in records
        if (since is None or r["_vn"] >= since) and (until is None or r["_vn"] < until + timedelta(minutes=1))
    ]
    latency_ms = args.latency_ms or default_latency_threshold()

    print("== 1. Metrics theo phút (giờ VN) ==")
    print(f"{'phút':<6} {HEADER}")
    by_minute: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_minute[r["_vn"].strftime("%H:%M")].append(r)
    for minute in sorted(by_minute):
        print(f"{minute:<6} {summarize(by_minute[minute])}")

    print("\n== 2. Theo feature ==")
    print(f"{'feature':<10} {HEADER}")
    by_feature: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("feature"):
            by_feature[r["feature"]].append(r)
    for feature in sorted(by_feature):
        print(f"{feature:<10} {summarize(by_feature[feature])}")

    print(f"\n== 3. Request bất thường (lỗi, latency > {latency_ms}ms, cost > {args.cost_usd}) ==")
    anomalies = []
    for r in records:
        reasons = []
        if r.get("event") == "request_failed":
            reasons.append(f"error={r.get('error_type')} tool={r.get('tool_name')} detail={r.get('payload', {}).get('detail')}")
        if r.get("event") == "response_sent":
            if r["latency_ms"] > latency_ms:
                reasons.append(f"latency={r['latency_ms']}ms ttft={r['ttft_ms']}ms")
            if r["cost_usd"] > args.cost_usd:
                reasons.append(f"cost={r['cost_usd']} tokens_out={r['tokens_out']}")
        if reasons:
            anomalies.append((r, "; ".join(reasons)))
    for r, reason in anomalies[: args.top]:
        print(f"{r['_vn']:%H:%M:%S} {r['correlation_id']} feature={r.get('feature')} {reason}")
    print(f"Tổng: {len(anomalies)} request bất thường. Mở trace Langfuse có metadata correlation_id tương ứng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
