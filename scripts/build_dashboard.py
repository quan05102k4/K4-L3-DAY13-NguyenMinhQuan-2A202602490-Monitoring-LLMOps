"""Dựng dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

Output là một file HTML tĩnh (inline SVG, không phụ thuộc CDN) tự refresh theo
`refresh_seconds`. Chạy lại script (hoặc dùng --watch) để cập nhật dữ liệu.

    python scripts/build_dashboard.py            # ghi data/dashboard.html
    python scripts/build_dashboard.py --watch    # build lại mỗi refresh_seconds
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile
from scripts.validate_dashboard import load_dashboard_config

VN_TZ = timezone(timedelta(hours=7))


def load_events(path: Path) -> list[dict]:
    events = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            record["_ts"] = datetime.fromisoformat(record["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        events.append(record)
    return events


def minute_buckets(end: datetime, minutes: int) -> list[datetime]:
    last = end.replace(second=0, microsecond=0)
    return [last - timedelta(minutes=minutes - 1 - i) for i in range(minutes)]


def by_minute(events: list[dict], buckets: list[datetime]) -> list[list[dict]]:
    index = {bucket: i for i, bucket in enumerate(buckets)}
    grouped: list[list[dict]] = [[] for _ in buckets]
    for event in events:
        i = index.get(event["_ts"].replace(second=0, microsecond=0))
        if i is not None:
            grouped[i].append(event)
    return grouped


def compute(events: list[dict], buckets: list[datetime]) -> dict[str, dict]:
    """Mỗi panel: summary (theo aggregations của contract) + series theo phút."""
    sent = [e for e in events if e.get("event") == "response_sent"]
    received = [e for e in events if e.get("event") == "request_received"]
    failed = [e for e in events if e.get("event") == "request_failed"]
    tool = [e for e in events if e.get("tool_success") is not None]
    sent_m, recv_m, fail_m = (by_minute(x, buckets) for x in (sent, received, failed))

    def field(items: list[dict], name: str) -> list:
        return [e[name] for e in items if isinstance(e.get(name), (int, float))]

    def per_minute(groups, fn):
        return [fn(g) if g else None for g in groups]

    active_minutes = sum(1 for g in recv_m if g) or 1
    return {
        "latency": {
            "summary": {
                "p50": percentile(field(sent, "latency_ms"), 50),
                "p95": percentile(field(sent, "latency_ms"), 95),
                "p99": percentile(field(sent, "latency_ms"), 99),
                "ttft_p95": percentile(field(sent, "ttft_ms"), 95),
            },
            "series": {
                "P50": per_minute(sent_m, lambda g: percentile(field(g, "latency_ms"), 50)),
                "P95": per_minute(sent_m, lambda g: percentile(field(g, "latency_ms"), 95)),
                "P99": per_minute(sent_m, lambda g: percentile(field(g, "latency_ms"), 99)),
                "TTFT P95": per_minute(sent_m, lambda g: percentile(field(g, "ttft_ms"), 95)),
            },
        },
        "traffic": {
            "summary": {
                "count": len(received),
                "rate_per_minute": round(len(received) / active_minutes, 2),
            },
            "series": {"Requests/phút": [len(g) if g else None for g in recv_m]},
        },
        "errors": {
            "summary": {
                "error_rate_pct": round(len(failed) / len(received) * 100, 2) if received else 0.0,
                "tool_success_rate_pct": round(
                    sum(1 for e in tool if e["tool_success"]) / len(tool) * 100, 2
                ) if tool else 0.0,
                "count_by_value": dict(Counter(e.get("error_type") or "unknown" for e in failed)),
            },
            "series": {
                "Error rate %": [
                    round(len(f) / len(r) * 100, 2) if r else None for f, r in zip(fail_m, recv_m)
                ],
            },
        },
        "cost": {
            "summary": {"total": round(sum(field(sent, "cost_usd")), 4)},
            "series": {"USD/phút": per_minute(sent_m, lambda g: round(sum(field(g, "cost_usd")), 5))},
        },
        "tokens": {
            "summary": {
                "sum_by_field": max(sum(field(sent, "tokens_in")), sum(field(sent, "tokens_out"))),
                "tokens_in": sum(field(sent, "tokens_in")),
                "tokens_out": sum(field(sent, "tokens_out")),
            },
            "series": {
                "tokens_in": per_minute(sent_m, lambda g: sum(field(g, "tokens_in"))),
                "tokens_out": per_minute(sent_m, lambda g: sum(field(g, "tokens_out"))),
            },
        },
        "quality": {
            "summary": {"mean": round(mean(field(sent, "quality_score")), 3) if sent else 0.0},
            "series": {"Mean quality": per_minute(sent_m, lambda g: round(mean(field(g, "quality_score")), 3))},
        },
    }


def breached(value: float, threshold: dict) -> bool:
    return value > threshold["value"] if threshold["operator"] == "lte" else value < threshold["value"]


def fmt(value, unit: str) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items()) or "không có lỗi"
    if unit == "usd":
        return f"${value:,.4f}"
    if unit == "score_0_to_1":
        return f"{value:.3f}"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, int) else f"{value:,.2f}"


def fmt_tick(value: float, unit: str) -> str:
    if unit == "usd":
        return f"${value:.3f}"
    return f"{value:,.0f}" if value >= 10 else f"{value:.2f}".rstrip("0").rstrip(".")


def svg_chart(series: dict[str, list], buckets: list[datetime], threshold: dict, unit: str) -> str:
    width, height, left, right, top, bottom = 560, 200, 52, 12, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [v for vals in series.values() for v in vals if v is not None]
    y_max = max(values + [threshold["value"]] if values else [threshold["value"]]) * 1.1 or 1
    n = len(buckets)

    def x(i: int) -> float:
        return left + plot_w * i / max(1, n - 1)

    def y(v: float) -> float:
        return top + plot_h * (1 - v / y_max)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" class="chart">']
    for frac in (0, 0.5, 1):
        yy = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{left - 6}" y="{yy + 4:.1f}" class="tick" text-anchor="end">{fmt_tick(y_max * frac, unit)}</text>')
    for i in range(0, n, 10):
        parts.append(f'<text x="{x(i):.1f}" y="{height - 6}" class="tick" text-anchor="middle">{buckets[i].astimezone(VN_TZ):%H:%M}</text>')
    ty = y(threshold["value"])
    parts.append(f'<line x1="{left}" x2="{width - right}" y1="{ty:.1f}" y2="{ty:.1f}" class="threshold"/>')
    parts.append(f'<text x="{width - right}" y="{ty - 4:.1f}" class="tick" text-anchor="end">threshold {"≤" if threshold["operator"] == "lte" else "≥"} {fmt(threshold["value"], unit)}</text>')

    for slot, (name, vals) in enumerate(series.items(), start=1):
        segments, current = [], []
        for i, v in enumerate(vals):
            if v is None:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append((x(i), y(v), v, buckets[i]))
        if current:
            segments.append(current)
        for seg in segments:
            points = " ".join(f"{px:.1f},{py:.1f}" for px, py, _, _ in seg)
            parts.append(f'<polyline points="{points}" class="line s{slot}"/>')
            for px, py, v, b in seg:
                label = html.escape(f"{name} · {b.astimezone(VN_TZ):%H:%M} · {fmt(v, unit)}")
                parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" class="dot s{slot}"><title>{label}</title></circle>')
    parts.append("</svg>")
    return "".join(parts)


def render(config: dict, data: dict, buckets: list[datetime], source: Path, total_events: int) -> str:
    dash = config["dashboard"]
    now_vn = datetime.now(VN_TZ)
    cards = []
    for panel in dash["panels"]:
        pid, unit, threshold = panel["id"], panel["unit"], panel["threshold"]
        panel_data = data[pid]
        headline = panel_data["summary"][threshold["aggregation"]]
        has_data = any(v is not None for vals in panel_data["series"].values() for v in vals)
        bad = has_data and breached(headline, threshold)
        status = (
            '<span class="badge bad">▲ Vượt ngưỡng</span>' if bad
            else '<span class="badge ok">● Đạt</span>' if has_data
            else '<span class="badge idle">○ Chưa có dữ liệu</span>'
        )
        stats = "".join(
            f'<div class="stat"><span class="k">{html.escape(k)}</span><span class="v">{html.escape(fmt(v, unit))}</span></div>'
            for k, v in panel_data["summary"].items()
        )
        legend = "".join(
            f'<span class="key"><i class="swatch s{i}"></i>{html.escape(name)}</span>'
            for i, name in enumerate(panel_data["series"], start=1)
        ) if len(panel_data["series"]) > 1 else ""
        rows = "".join(
            "<tr><td>{}</td>{}</tr>".format(
                f"{b.astimezone(VN_TZ):%H:%M}",
                "".join(f"<td>{'' if vals[i] is None else html.escape(fmt(vals[i], unit))}</td>" for vals in panel_data["series"].values()),
            )
            for i, b in enumerate(buckets)
            if any(vals[i] is not None for vals in panel_data["series"].values())
        )
        header = "".join(f"<th>{html.escape(n)}</th>" for n in panel_data["series"])
        cards.append(f"""
<section class="card">
  <header><h2>{html.escape(panel["title"])}</h2>{status}</header>
  <p class="meta">unit: <b>{html.escape(unit)}</b> · threshold: {html.escape(threshold["aggregation"])} {"≤" if threshold["operator"] == "lte" else "≥"} {threshold["value"]} · events: {html.escape(", ".join(panel["events"]))}</p>
  <div class="stats">{stats}</div>
  {svg_chart(panel_data["series"], buckets, threshold, unit)}
  <div class="legend">{legend}</div>
  <details><summary>Bảng dữ liệu theo phút</summary><table><tr><th>Phút</th>{header}</tr>{rows}</table></details>
  <p class="query"><code>{html.escape(panel["query"])}</code></p>
</section>""")

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{dash["refresh_seconds"]}">
<title>{html.escape(dash["title"])}</title>
<style>
:root {{ color-scheme: light; --surface:#f4f3f0; --card:#fcfcfb; --text:#0b0b0b; --muted:#52514e; --grid:#e3e2de;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#4a3aa7; --good:#008300; --bad:#c62828; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --surface:#111110; --card:#1a1a19; --text:#fff;
  --muted:#c3c2b7; --grid:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#9085e9; --good:#3fb950; --bad:#e66767; }} }}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:16px; background:var(--surface); color:var(--text); font:14px/1.45 system-ui, "Segoe UI", sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 16px; }}
.grid6 {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(min(100%, 520px), 1fr)); gap:16px; }}
.card {{ background:var(--card); border:1px solid var(--grid); border-radius:10px; padding:14px 16px; min-width:0; }}
.card header {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
h2 {{ font-size:15px; margin:0; }} .meta, .query {{ color:var(--muted); font-size:12px; margin:4px 0 8px; }}
.query code {{ word-break:break-all; }}
.badge {{ font-size:12px; font-weight:600; white-space:nowrap; }} .ok {{ color:var(--good); }} .bad {{ color:var(--bad); }} .idle {{ color:var(--muted); }}
.stats {{ display:flex; flex-wrap:wrap; gap:6px 18px; margin-bottom:6px; }}
.stat .k {{ display:block; color:var(--muted); font-size:11px; }} .stat .v {{ font-size:18px; font-weight:600; font-variant-numeric:tabular-nums; }}
.chart {{ width:100%; height:auto; display:block; }}
.grid {{ stroke:var(--grid); stroke-width:1; }} .tick {{ fill:var(--muted); font-size:10px; }}
.threshold {{ stroke:var(--bad); stroke-width:1.5; stroke-dasharray:5 4; }}
.line {{ fill:none; stroke-width:2; stroke-linejoin:round; }} .dot {{ stroke:var(--card); stroke-width:2; }}
.s1 {{ stroke:var(--s1); }} circle.s1, .swatch.s1 {{ fill:var(--s1); background:var(--s1); }}
.s2 {{ stroke:var(--s2); }} circle.s2, .swatch.s2 {{ fill:var(--s2); background:var(--s2); }}
.s3 {{ stroke:var(--s3); }} circle.s3, .swatch.s3 {{ fill:var(--s3); background:var(--s3); }}
.s4 {{ stroke:var(--s4); }} circle.s4, .swatch.s4 {{ fill:var(--s4); background:var(--s4); }}
circle.dot {{ stroke:var(--card); }}
.legend {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-top:4px; }}
.swatch {{ display:inline-block; width:14px; height:3px; border-radius:2px; vertical-align:middle; margin-right:5px; }}
details {{ margin-top:8px; font-size:12px; }} table {{ border-collapse:collapse; margin-top:6px; }}
td, th {{ padding:2px 10px 2px 0; text-align:right; font-variant-numeric:tabular-nums; }} th {{ color:var(--muted); font-weight:500; }}
</style></head><body>
<h1>{html.escape(dash["title"])}</h1>
<p class="sub">Time range: {dash["time_range_minutes"]} phút gần nhất ({buckets[0].astimezone(VN_TZ):%H:%M}–{buckets[-1].astimezone(VN_TZ):%H:%M} giờ VN) · refresh {dash["refresh_seconds"]}s · nguồn: {html.escape(source.as_posix())} ({total_events} events trong cửa sổ) · build lúc {now_vn:%Y-%m-%d %H:%M:%S}</p>
<div class="grid6">{"".join(cards)}</div>
</body></html>"""


def build(config_path: Path, log_path: Path, out_path: Path, anchor_latest: bool) -> Path:
    config = load_dashboard_config(config_path)
    minutes = config["dashboard"]["time_range_minutes"]
    events = load_events(log_path)
    end = datetime.now(timezone.utc)
    if anchor_latest and events:
        end = max(e["_ts"] for e in events)
    buckets = minute_buckets(end, minutes)
    window = [e for e in events if buckets[0] <= e["_ts"] < buckets[-1] + timedelta(minutes=1)]
    data = compute(window, buckets)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(config, data, buckets, log_path, len(window)), encoding="utf-8")
    return out_path


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ structured log")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--logs", type=Path, default=Path("data/logs.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("data/dashboard.html"))
    parser.add_argument("--anchor-latest", action="store_true", help="Cửa sổ 60 phút kết thúc ở log mới nhất thay vì hiện tại")
    parser.add_argument("--watch", action="store_true", help="Build lại liên tục theo refresh_seconds")
    args = parser.parse_args()

    refresh = load_dashboard_config(args.config)["dashboard"]["refresh_seconds"]
    while True:
        out = build(args.config, args.logs, args.out, args.anchor_latest)
        print(f"Đã ghi {out} lúc {datetime.now(VN_TZ):%H:%M:%S}")
        if not args.watch:
            return 0
        time.sleep(refresh)


if __name__ == "__main__":
    raise SystemExit(main())
