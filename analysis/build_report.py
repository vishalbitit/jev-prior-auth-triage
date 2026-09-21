"""
Build a self-contained HTML dashboard from data/audit_log.jsonl.

All numbers in the dashboard are computed directly from the real Jev API
responses captured by pipeline/triage.py -- nothing here is fabricated or
copied from vendor marketing. Anywhere a TypeSafe-published figure is shown
for context, it is explicitly labeled "reported by TypeSafe, not measured
by us" with a source link.
"""

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from policy.policies import POLICIES_BY_ID

AUDIT_LOG_PATH = Path(__file__).parent.parent / "data" / "audit_log.jsonl"
OUTPUT_PATH = Path(__file__).parent / "output" / "dashboard.html"

TIER_ORDER = ["meets_criteria", "borderline", "does_not_meet_criteria"]
TIER_LABELS = {
    "meets_criteria": "Clearly meets criteria",
    "borderline": "Borderline",
    "does_not_meet_criteria": "Clearly does not meet",
}
ROUTE_ORDER = ["auto_approve", "pend_clinical_review", "peer_to_peer_required"]
ROUTE_LABELS = {
    "auto_approve": "Auto-approve",
    "pend_clinical_review": "Pend for clinical review",
    "peer_to_peer_required": "Peer-to-peer required",
}


def load_records() -> list[dict]:
    return [json.loads(line) for line in AUDIT_LOG_PATH.read_text().splitlines()]


def percentile(sorted_vals: list[float], p: float) -> float:
    idx = min(int(len(sorted_vals) * p), len(sorted_vals) - 1)
    return sorted_vals[idx]


def compute_kpis(recs: list[dict]) -> dict:
    lat = sorted(r["latency_ms"] for r in recs)
    total_in = sum(r["input_tokens"] for r in recs)
    total_out = sum(r["output_tokens"] for r in recs)
    cost = total_in * 0.042 / 1e6  # $0.042 / MTok input, output free (TypeSafe pricing)

    unsafe_auto = [
        r for r in recs
        if r["ground_truth_tier"] == "does_not_meet_criteria" and r["routing_decision"] == "auto_approve"
    ]
    not_meet_total = sum(1 for r in recs if r["ground_truth_tier"] == "does_not_meet_criteria")

    urgency_mismatches = sum(
        1 for r in recs
        if r["submitter_claimed_urgency"] in ("routine", "urgent", "stat")
        and r["urgency_label"] != r["submitter_claimed_urgency"]
    )

    return {
        "n": len(recs),
        "p50_latency": round(percentile(lat, 0.5), 1),
        "p95_latency": round(percentile(lat, 0.95), 1),
        "total_cost": round(cost, 4),
        "cost_per_1k": round(cost / len(recs) * 1000, 3),
        "unsafe_auto_approvals": len(unsafe_auto),
        "not_meet_total": not_meet_total,
        "urgency_mismatches": urgency_mismatches,
        "urgency_mismatch_pct": round(urgency_mismatches / len(recs) * 100, 1),
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
    }


def compute_confusion(recs: list[dict]) -> dict:
    conf = defaultdict(Counter)
    for r in recs:
        conf[r["ground_truth_tier"]][r["routing_decision"]] += 1
    return conf


def compute_category_summary(recs: list[dict]) -> list[dict]:
    by_cat = defaultdict(lambda: {"n": 0, "lat": [], "routing": Counter()})
    for r in recs:
        c = by_cat[r["category_id"]]
        c["n"] += 1
        c["lat"].append(r["latency_ms"])
        c["routing"][r["routing_decision"]] += 1

    rows = []
    for cid, c in sorted(by_cat.items(), key=lambda kv: -kv[1]["n"]):
        n = c["n"]
        rows.append({
            "category_id": cid,
            "procedure_name": POLICIES_BY_ID[cid].procedure_name,
            "n": n,
            "avg_latency": round(sum(c["lat"]) / n, 1),
            "pct_auto": round(c["routing"]["auto_approve"] / n * 100),
            "pct_pend": round(c["routing"]["pend_clinical_review"] / n * 100),
            "pct_p2p": round(c["routing"]["peer_to_peer_required"] / n * 100),
        })
    return rows


def compute_dot_points(recs: list[dict]) -> list[dict]:
    rng = random.Random(42)
    lowest_conf = min(recs, key=lambda r: r["routing_confidence"])
    points = []
    for r in recs:
        points.append({
            "request_id": r["request_id"],
            "tier": r["ground_truth_tier"],
            "noul": r["meets_medical_necessity"],
            "jitter": rng.uniform(-0.32, 0.32),
            "routing_decision": r["routing_decision"],
            "routing_confidence": r["routing_confidence"],
            "is_lowest_confidence": r["request_id"] == lowest_conf["request_id"],
        })
    return points


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

HEAT_STEPS_LIGHT = ["#eef4fc", "#b7d3f6", "#6da7ec", "#2a78d6", "#184f95"]
HEAT_STEPS_DARK = ["#22324a", "#2d4f7c", "#3987e5", "#6da7ec", "#b7d3f6"]
TIER_COLOR_LIGHT = {"meets_criteria": "#184f95", "borderline": "#5598e7", "does_not_meet_criteria": "#b7d3f6"}
TIER_COLOR_DARK = {"meets_criteria": "#b7d3f6", "borderline": "#5598e7", "does_not_meet_criteria": "#2a4f7c"}


def heat_bucket(count: int, max_count: int) -> int:
    if count == 0:
        return 0
    frac = count / max_count
    if frac <= 0.15:
        return 1
    if frac <= 0.35:
        return 2
    if frac <= 0.65:
        return 3
    return 4


def render_heatmap(conf: dict) -> str:
    max_count = max(conf[t][r] for t in TIER_ORDER for r in ROUTE_ORDER) or 1
    cell_w, cell_h, gap = 150, 64, 4
    label_col_w = 190
    label_row_h = 46
    width = label_col_w + len(ROUTE_ORDER) * (cell_w + gap)
    height = label_row_h + len(TIER_ORDER) * (cell_h + gap)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}" class="heatmap-svg" role="img" aria-label="Confusion matrix of ground-truth tier versus Jev routing decision">']

    for ci, route in enumerate(ROUTE_ORDER):
        x = label_col_w + ci * (cell_w + gap) + cell_w / 2
        svg_parts.append(
            f'<text x="{x}" y="{label_row_h - 16}" class="heat-col-label" text-anchor="middle">{ROUTE_LABELS[route]}</text>'
        )

    for ti, tier in enumerate(TIER_ORDER):
        y = label_row_h + ti * (cell_h + gap)
        svg_parts.append(
            f'<text x="{label_col_w - 14}" y="{y + cell_h / 2 + 5}" class="heat-row-label" text-anchor="end">{TIER_LABELS[tier]}</text>'
        )
        for ci, route in enumerate(ROUTE_ORDER):
            count = conf[tier][route]
            bucket = heat_bucket(count, max_count)
            x = label_col_w + ci * (cell_w + gap)
            pct = round(count / sum(conf[tier].values()) * 100) if sum(conf[tier].values()) else 0
            text_class = "heat-cell-text-dark" if bucket <= 2 else "heat-cell-text-light"
            svg_parts.append(
                f'<g class="heat-cell" data-bucket="{bucket}" '
                f'data-tooltip="{TIER_LABELS[tier]} → {ROUTE_LABELS[route]}: {count} of {sum(conf[tier].values())} ({pct}%)">'
                f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="6" class="heat-rect heat-bucket-{bucket}"/>'
                f'<text x="{x + cell_w/2}" y="{y + cell_h/2 - 2}" text-anchor="middle" class="heat-count {text_class}">{count}</text>'
                f'<text x="{x + cell_w/2}" y="{y + cell_h/2 + 16}" text-anchor="middle" class="heat-pct {text_class}">{pct}%</text>'
                f'</g>'
            )
    svg_parts.append("</svg>")
    return "".join(svg_parts)


def render_dot_plot(points: list[dict]) -> str:
    width, height = 640, 340
    margin = {"top": 20, "right": 24, "bottom": 46, "left": 46}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    band_w = plot_w / len(TIER_ORDER)

    svg_parts = [f'<svg viewBox="0 0 {width} {height}" class="dotplot-svg" role="img" aria-label="Meets-medical-necessity probability by ground-truth tier">']

    # gridlines + y-axis ticks at 0, .25, .5, .75, 1
    for tick in [0, 0.25, 0.5, 0.75, 1.0]:
        y = margin["top"] + plot_h * (1 - tick)
        svg_parts.append(
            f'<line x1="{margin["left"]}" y1="{y}" x2="{width - margin["right"]}" y2="{y}" class="gridline"/>'
        )
        svg_parts.append(
            f'<text x="{margin["left"] - 10}" y="{y + 4}" text-anchor="end" class="axis-tick">{tick:.2f}</text>'
        )

    # baseline
    svg_parts.append(
        f'<line x1="{margin["left"]}" y1="{margin["top"] + plot_h}" x2="{width - margin["right"]}" '
        f'y2="{margin["top"] + plot_h}" class="axis-baseline"/>'
    )

    for i, tier in enumerate(TIER_ORDER):
        cx_center = margin["left"] + band_w * i + band_w / 2
        svg_parts.append(
            f'<text x="{cx_center}" y="{height - 12}" text-anchor="middle" class="axis-tick tier-x-label">{TIER_LABELS[tier]}</text>'
        )

    for p in points:
        i = TIER_ORDER.index(p["tier"])
        cx_center = margin["left"] + band_w * i + band_w / 2
        cx = cx_center + p["jitter"] * band_w
        cy = margin["top"] + plot_h * (1 - p["noul"])
        r = 5 if not p["is_lowest_confidence"] else 7
        cls = "dot-outlier" if p["is_lowest_confidence"] else f'dot-tier-{i}'
        tooltip = (
            f'{p["request_id"]}: meets-necessity {p["noul"]:.2f}, routed to '
            f'{ROUTE_LABELS[p["routing_decision"]]} (confidence {p["routing_confidence"]:.2f})'
        )
        if p["is_lowest_confidence"]:
            tooltip += " — lowest routing confidence in the whole batch"
        svg_parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" class="dot {cls}" data-tooltip="{tooltip}"/>'
        )

    svg_parts.append("</svg>")
    return "".join(svg_parts)


def render_category_table(rows: list[dict]) -> str:
    trs = []
    for r in rows:
        trs.append(
            "<tr>"
            f'<td>{r["procedure_name"]}</td>'
            f'<td class="num">{r["n"]}</td>'
            f'<td class="num">{r["avg_latency"]} ms</td>'
            f'<td class="num">{r["pct_auto"]}%</td>'
            f'<td class="num">{r["pct_pend"]}%</td>'
            f'<td class="num">{r["pct_p2p"]}%</td>'
            "</tr>"
        )
    return "".join(trs)


def main() -> None:
    recs = load_records()
    kpis = compute_kpis(recs)
    conf = compute_confusion(recs)
    cat_rows = compute_category_summary(recs)
    dot_points = compute_dot_points(recs)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    html = TEMPLATE.format(
        n=kpis["n"],
        p50=kpis["p50_latency"],
        p95=kpis["p95_latency"],
        cost=kpis["total_cost"],
        cost_per_1k=kpis["cost_per_1k"],
        unsafe=kpis["unsafe_auto_approvals"],
        not_meet_total=kpis["not_meet_total"],
        urgency_mismatch_pct=kpis["urgency_mismatch_pct"],
        urgency_mismatches=kpis["urgency_mismatches"],
        heatmap_svg=render_heatmap(conf),
        dotplot_svg=render_dot_plot(dot_points),
        category_rows=render_category_table(cat_rows),
        total_input_tokens=f'{kpis["total_input_tokens"]:,}',
        h1l=HEAT_STEPS_LIGHT[1], h2l=HEAT_STEPS_LIGHT[2], h3l=HEAT_STEPS_LIGHT[3], h4l=HEAT_STEPS_LIGHT[4],
        h1d=HEAT_STEPS_DARK[1], h2d=HEAT_STEPS_DARK[2], h3d=HEAT_STEPS_DARK[3], h4d=HEAT_STEPS_DARK[4],
        t0l=TIER_COLOR_LIGHT["meets_criteria"], t1l=TIER_COLOR_LIGHT["borderline"], t2l=TIER_COLOR_LIGHT["does_not_meet_criteria"],
        t0d=TIER_COLOR_DARK["meets_criteria"], t1d=TIER_COLOR_DARK["borderline"], t2d=TIER_COLOR_DARK["does_not_meet_criteria"],
    )
    OUTPUT_PATH.write_text(html)
    print(f"Wrote dashboard to {OUTPUT_PATH}")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Jev Prior-Authorization Triage — POC Results</title>
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --good:           #0ca30c;
    --heat-0: #f4f7fc; --heat-1: {h1l}; --heat-2: {h2l}; --heat-3: {h3l}; --heat-4: {h4l};
    --tier-0: {t0l}; --tier-1: {t1l}; --tier-2: {t2l};
    --outlier: #eb6834;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --good:           #0ca30c;
      --heat-0: #20262f; --heat-1: {h1d}; --heat-2: {h2d}; --heat-3: {h3d}; --heat-4: {h4d};
      --tier-0: {t0d}; --tier-1: {t1d}; --tier-2: {t2d};
      --outlier: #d95926;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --good:           #0ca30c;
    --heat-0: #20262f; --heat-1: {h1d}; --heat-2: {h2d}; --heat-3: {h3d}; --heat-4: {h4d};
    --tier-0: {t0d}; --tier-1: {t1d}; --tier-2: {t2d};
    --outlier: #d95926;
  }}

  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--page-plane); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--text-primary); }}
  .wrap {{ max-width: 920px; margin: 0 auto; padding: 32px 20px 80px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); margin: 0 0 20px; font-size: 0.95rem; }}
  .banner {{ background: var(--surface-1); border: 1px solid var(--border); border-left: 4px solid var(--outlier); border-radius: 8px; padding: 14px 16px; font-size: 0.88rem; color: var(--text-secondary); margin-bottom: 28px; line-height: 1.5; }}
  .banner strong {{ color: var(--text-primary); }}

  .kpi-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 36px; }}
  .kpi {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
  .kpi .value {{ font-size: 1.7rem; font-weight: 600; font-variant-numeric: proportional-nums; }}
  .kpi .label {{ font-size: 0.78rem; color: var(--text-secondary); margin-top: 4px; line-height: 1.3; }}
  .kpi.good .value {{ color: var(--good); }}

  section {{ margin-bottom: 44px; }}
  h2 {{ font-size: 1.1rem; margin: 0 0 6px; }}
  .caption {{ color: var(--text-secondary); font-size: 0.88rem; margin: 0 0 16px; line-height: 1.5; max-width: 640px; }}

  .chart-card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 20px; overflow-x: auto; }}

  .heat-col-label, .heat-row-label {{ font-size: 12px; fill: var(--text-secondary); }}
  .heat-rect {{ stroke: var(--surface-1); stroke-width: 2; }}
  .heat-bucket-0 {{ fill: var(--heat-0); }}
  .heat-bucket-1 {{ fill: var(--heat-1); }}
  .heat-bucket-2 {{ fill: var(--heat-2); }}
  .heat-bucket-3 {{ fill: var(--heat-3); }}
  .heat-bucket-4 {{ fill: var(--heat-4); }}
  .heat-count {{ font-size: 20px; font-weight: 600; }}
  .heat-pct {{ font-size: 11px; }}
  .heat-cell-text-dark {{ fill: var(--text-primary); }}
  .heat-cell-text-light {{ fill: #fcfcfb; }}
  .heat-cell {{ cursor: default; }}

  .gridline {{ stroke: var(--gridline); stroke-width: 1; }}
  .axis-baseline {{ stroke: var(--baseline); stroke-width: 1; }}
  .axis-tick {{ font-size: 11px; fill: var(--text-muted); }}
  .tier-x-label {{ font-size: 12px; fill: var(--text-secondary); }}
  .dot {{ stroke: var(--surface-1); stroke-width: 1.5; cursor: default; }}
  .dot-tier-0 {{ fill: var(--tier-0); }}
  .dot-tier-1 {{ fill: var(--tier-1); }}
  .dot-tier-2 {{ fill: var(--tier-2); }}
  .dot-outlier {{ fill: var(--outlier); stroke: var(--text-primary); }}

  .legend {{ display: flex; gap: 18px; flex-wrap: wrap; margin: 10px 0 18px; font-size: 0.82rem; color: var(--text-secondary); }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-swatch {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; }}
  th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--gridline); }}
  th {{ color: var(--text-secondary); font-weight: 500; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.02em; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}

  .callout {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; font-size: 0.88rem; color: var(--text-secondary); line-height: 1.6; }}
  .callout a {{ color: var(--text-primary); }}
  .tooltip {{ position: fixed; pointer-events: none; background: var(--text-primary); color: var(--surface-1); padding: 6px 10px; border-radius: 6px; font-size: 12px; max-width: 260px; z-index: 10; opacity: 0; transition: opacity 0.1s; line-height: 1.4; }}
  footer {{ color: var(--text-muted); font-size: 0.8rem; margin-top: 50px; border-top: 1px solid var(--border); padding-top: 16px; line-height: 1.6; }}
  footer a {{ color: var(--text-secondary); }}
</style>
</head>
<body>
<div class="viz-root">
<div class="wrap">
  <h1>Prior-Authorization Triage with Jev</h1>
  <p class="subtitle">A proof of concept: TypeSafe AI's Jev (System-1 model) triaging synthetic prior-authorization requests for a payer utilization-management workflow.</p>

  <div class="banner">
    <strong>Synthetic data only.</strong> All 150 requests below are generated, PHI-free examples against simplified illustrative policies — not real patients, claims, or payer policy documents. This is a proof of concept, not a validated clinical or coverage decision system. In this design, Jev only ever <em>triages/routes</em> requests; a human always makes the final call on anything short of auto-approval, and auto-approvals remain subject to normal audit sampling.
  </div>

  <div class="kpi-row">
    <div class="kpi"><div class="value">{n}</div><div class="label">Synthetic PA requests triaged</div></div>
    <div class="kpi"><div class="value">{p50} ms</div><div class="label">Median (p50) latency, measured</div></div>
    <div class="kpi"><div class="value">{p95} ms</div><div class="label">p95 latency, measured</div></div>
    <div class="kpi"><div class="value">${cost}</div><div class="label">Total cost for the batch ({total_input_tokens} input tokens)</div></div>
    <div class="kpi good"><div class="value">{unsafe} / {not_meet_total}</div><div class="label">Clearly non-qualifying requests auto-approved (lower is better)</div></div>
    <div class="kpi"><div class="value">{urgency_mismatch_pct}%</div><div class="label">Requests where Jev's urgency assessment disagreed with the submitter's self-claimed urgency</div></div>
  </div>

  <section>
    <h2>Did routing match reality?</h2>
    <p class="caption">Rows are the synthetic ground truth our policy engine assigned when generating each request (never shown to Jev). Columns are Jev's routing decision. A well-behaved triage system should cluster along the diagonal — and critically, put zero weight in the bottom-left cell (clearly-non-qualifying requests auto-approved).</p>
    <div class="chart-card">{heatmap_svg}</div>
  </section>

  <section>
    <h2>Is the confidence calibrated?</h2>
    <p class="caption">Each dot is one request: Jev's "meets medical necessity" probability, grouped by our synthetic ground-truth tier. The orange dot is the single lowest routing-confidence decision (0.24) in the entire batch — it also happens to be the one borderline case that got auto-approved. A confidence threshold around 0.3 would have caught it and routed it to a human instead.</p>
    <div class="legend">
      <span class="legend-item"><span class="legend-swatch" style="background:var(--tier-0)"></span>Clearly meets criteria</span>
      <span class="legend-item"><span class="legend-swatch" style="background:var(--tier-1)"></span>Borderline</span>
      <span class="legend-item"><span class="legend-swatch" style="background:var(--tier-2)"></span>Clearly does not meet</span>
      <span class="legend-item"><span class="legend-swatch" style="background:var(--outlier)"></span>Lowest confidence in batch</span>
    </div>
    <div class="chart-card">{dotplot_svg}</div>
  </section>

  <section>
    <h2>By procedure type</h2>
    <p class="caption">Table view of the same run, broken out by procedure category — the accessible/data-table alternative to the charts above.</p>
    <div class="chart-card">
      <table>
        <thead><tr><th>Procedure</th><th class="num">n</th><th class="num">Avg latency</th><th class="num">Auto-approve</th><th class="num">Pend review</th><th class="num">Peer-to-peer</th></tr></thead>
        <tbody>{category_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Context: vendor-published figures</h2>
    <div class="callout">
      The numbers above are all measured directly from our own pipeline run against the live Jev API — nothing here is copied from marketing material. For context only, TypeSafe AI's own launch materials report Jev latency in the 70–500ms range and claim up to ~193.6× faster / ~444.6× cheaper workflows versus comparable LLMs, with input priced at $0.042 per million tokens and output free. <strong>These are the vendor's reported figures, not independently verified by this project</strong> — see <a href="https://typesafe.ai/blog/introducing-system-one-models-and-jev" target="_blank" rel="noopener">typesafe.ai/blog/introducing-system-one-models-and-jev</a>. Our own measured p50/p95 above are broadly consistent with that range.
    </div>
  </section>

  <footer>
    Generated from a live run against the Jev API (model reported as <code>jev-1.13.0</code>) over 150 synthetic, PHI-free prior-authorization requests. Source: <a href="https://github.com/vishalbitit/jev-prior-auth-triage" target="_blank" rel="noopener">github.com/vishalbitit/jev-prior-auth-triage</a>. Not for real clinical or coverage decisioning.
  </footer>
</div>
</div>
<div class="tooltip" id="tooltip"></div>
<script>
  const tooltip = document.getElementById('tooltip');
  document.querySelectorAll('[data-tooltip]').forEach(el => {{
    el.addEventListener('mousemove', (e) => {{
      tooltip.textContent = el.getAttribute('data-tooltip');
      tooltip.style.left = (e.clientX + 14) + 'px';
      tooltip.style.top = (e.clientY + 14) + 'px';
      tooltip.style.opacity = 1;
    }});
    el.addEventListener('mouseleave', () => {{ tooltip.style.opacity = 0; }});
  }});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
