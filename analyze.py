#!/usr/bin/env python3
"""Phân tích data/prices.csv và sinh report.html (SVG tự chứa, không dependency).

Chạy: python3 analyze.py  ->  in tóm tắt ra console + ghi report.html
"""

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
CSV_PATH = HERE / "data" / "prices.csv"
OUT_PATH = HERE / "report.html"

# Thứ tự nguồn cố định = thứ tự gán màu categorical (không bao giờ xáo)
SOURCES = ["vast", "runpod-secure", "runpod-community", "datacrunch", "datacrunch-spot", "cudo"]
COLORS = {  # palette đã validate (dataviz skill), light/dark cùng hue khác step
    "vast": ("#2a78d6", "#3987e5"),
    "runpod-secure": ("#1baf7a", "#199e70"),
    "runpod-community": ("#eda100", "#c98500"),
    "datacrunch": ("#008300", "#008300"),
    "datacrunch-spot": ("#4a3aa7", "#9085e9"),
    "cudo": ("#e34948", "#e66767"),
}
GPU_ORDER = [
    "H100 SXM", "H100 NVL", "H100 PCIE", "H200", "B200",
    "A100 SXM4", "A100 PCIE", "L40S", "RTX PRO 6000 WS", "RTX A6000",
    "RTX 3090", "RTX 4090", "RTX 5080", "RTX 5090",
]
HEADLINE_GPU = "H100 SXM"


def load_rows():
    with open(CSV_PATH) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["median"] = float(r["median_usd_hr"])
        r["min"] = float(r["min_usd_hr"])
        r["ts"] = datetime.strptime(r["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ")
    return sorted(rows, key=lambda r: r["ts"])


def build(rows):
    # series[gpu][source] = [[iso_ts, median], ...]
    series = defaultdict(lambda: defaultdict(list))
    for r in rows:
        series[r["gpu"]][r["source"]].append([r["timestamp_utc"], r["median"]])

    timestamps = sorted({r["timestamp_utc"] for r in rows})
    days = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / 86400 if rows else 0

    # Bảng snapshot mới nhất cho mỗi (gpu, source)
    latest = {}
    for r in rows:
        latest[(r["gpu"], r["source"])] = r
    table = []
    for gpu in GPU_ORDER:
        for src in SOURCES:
            r = latest.get((gpu, src))
            if r:
                table.append({
                    "gpu": gpu, "source": src, "median": r["median"], "min": r["min"],
                    "offers": r["offers"], "asof": r["timestamp_utc"],
                })

    # Intraday (chỉ vast — nguồn duy nhất biến động theo giờ): giá median trung bình theo giờ UTC
    intraday = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["source"] == "vast":
            intraday[r["gpu"]][r["ts"].hour].append(r["median"])
    intraday_avg = {
        gpu: {h: round(statistics.mean(v), 4) for h, v in hours.items()}
        for gpu, hours in intraday.items()
    }

    findings = []
    findings.append(
        f"Dữ liệu: {len(timestamps)} snapshot trong {days:.1f} ngày "
        f"({rows[0]['timestamp_utc']} → {rows[-1]['timestamp_utc']})."
    )
    if days < 3:
        findings.append("⚠️ Dưới 3 ngày data — pattern theo giờ/ngày chưa đáng tin, chỉ xem cho vui.")
    for gpu in GPU_ORDER:
        prices = {src: latest[(gpu, src)]["median"] for src in SOURCES if (gpu, src) in latest}
        if len(prices) < 2:
            continue
        lo_src = min(prices, key=prices.get)
        hi_src = max(prices, key=prices.get)
        spread = prices[hi_src] / prices[lo_src]
        findings.append(
            f"{gpu}: rẻ nhất {lo_src} ${prices[lo_src]:.2f}/h, đắt nhất {hi_src} "
            f"${prices[hi_src]:.2f}/h — chênh {spread:.1f}×."
        )
    # Biến động giá vast (nguồn spot duy nhất có phân phối)
    for gpu in GPU_ORDER:
        vals = [p for _, p in series[gpu].get("vast", [])]
        if len(vals) >= 24:
            cv = statistics.pstdev(vals) / statistics.mean(vals) * 100
            findings.append(f"Biến động giá Vast {gpu}: CV {cv:.1f}% quanh mean ${statistics.mean(vals):.2f}/h.")

    return {
        "generated": rows[-1]["timestamp_utc"] if rows else "",
        "gpus": [g for g in GPU_ORDER if g in series],
        "sources": SOURCES,
        "colors": COLORS,
        "headline": HEADLINE_GPU,
        "days": round(days, 1),
        "series": {g: dict(s) for g, s in series.items()},
        "intraday": intraday_avg,
        "table": table,
        "findings": findings,
    }


TEMPLATE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPU Price Tracker — Report</title>
<style>
:root {
  --surface: #fcfcfb; --card: #ffffff; --border: #e5e4df;
  --text-1: #1a1a19; --text-2: #5f5e58; --grid: #ececea;
}
@media (prefers-color-scheme: dark) {
  :root { --surface: #1a1a19; --card: #232322; --border: #3a3a38;
          --text-1: #ffffff; --text-2: #c3c2b7; --grid: #32322f; }
}
* { box-sizing: border-box; margin: 0; }
body { background: var(--surface); color: var(--text-1);
  font: 14px/1.5 -apple-system, "Segoe UI", sans-serif; padding: 24px; max-width: 1080px; margin: 0 auto; }
h1 { font-size: 20px; } h2 { font-size: 15px; margin: 0 0 4px; }
.sub { color: var(--text-2); font-size: 12.5px; margin: 4px 0 20px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; margin-bottom: 16px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 6px; font-size: 12.5px; color: var(--text-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 16px; }
svg { display: block; width: 100%; height: auto; }
.tooltip { position: fixed; pointer-events: none; background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 14px rgba(0,0,0,.12);
  display: none; z-index: 10; min-width: 150px; }
.tooltip .t { color: var(--text-2); margin-bottom: 4px; }
.tooltip .row { display: flex; justify-content: space-between; gap: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--border); }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { color: var(--text-2); font-weight: 600; }
ul { padding-left: 18px; } li { margin: 3px 0; }
.overflow { overflow-x: auto; }
</style></head><body data-palette="__PALETTE__">
<h1>GPU Price Tracker</h1>
<p class="sub">Giá thuê mỗi GPU/giờ (USD, median mỗi snapshot) · cập nhật __GENERATED__ · __DAYS__ ngày data</p>

<div class="card"><h2>Nhận xét tự động</h2><ul id="findings"></ul></div>

<div class="legend" id="legend"></div>
<div class="grid2" id="charts"></div>

<div class="card"><h2>Pattern theo giờ UTC — __HEADLINE__ trên Vast.ai</h2>
<p class="sub">Giá median trung bình theo giờ trong ngày. Cần ≥ 1-2 tuần data mới đáng tin.</p>
<div id="intraday"></div></div>

<div class="card overflow"><h2>Snapshot mới nhất</h2><table id="latest"></table></div>

<div class="tooltip" id="tip"></div>
<script>
const DATA = __DATA__;
const dark = matchMedia('(prefers-color-scheme: dark)').matches;
const color = s => DATA.colors[s][dark ? 1 : 0];
const css = v => getComputedStyle(document.body).getPropertyValue(v).trim();
const fmt = v => '$' + (v >= 10 ? v.toFixed(1) : v.toFixed(2));
const tip = document.getElementById('tip');

// Legend chung (màu theo entity, thứ tự cố định)
document.getElementById('legend').innerHTML = DATA.sources.map(s =>
  `<span><i class="swatch" style="background:${color(s)}"></i>${s}</span>`).join('');

document.getElementById('findings').innerHTML =
  DATA.findings.map(f => `<li>${f}</li>`).join('');

function ticks(lo, hi, n) {
  const span = hi - lo || 1, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => span / s <= n) || mag * 10;
  const start = Math.ceil(lo / step) * step, out = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function lineChart(el, title, seriesBySource, xLabels) {
  const W = 520, H = 240, m = {t: 28, r: 12, b: 26, l: 44};
  const xs = xLabels, n = xs.length;
  const all = Object.values(seriesBySource).flatMap(pts => pts.map(p => p[1]));
  const lo = 0, hi = Math.max(...all) * 1.08;
  const X = i => m.l + (n < 2 ? 0.5 : i / (n - 1)) * (W - m.l - m.r);
  const Y = v => H - m.b - (v - lo) / (hi - lo) * (H - m.t - m.b);
  const idx = Object.fromEntries(xs.map((t, i) => [t, i]));

  let g = `<text x="${m.l}" y="16" fill="${css('--text-1')}" font-size="13" font-weight="600">${title}</text>`;
  for (const v of ticks(lo, hi, 4)) {
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--grid')}"/>` +
         `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" fill="${css('--text-2')}" font-size="11">${fmt(v)}</text>`;
  }
  const nx = Math.min(5, n);
  for (let k = 0; k < nx; k++) {
    const i = Math.round(k * (n - 1) / Math.max(1, nx - 1));
    const anchor = k === 0 ? 'start' : k === nx - 1 ? 'end' : 'middle';
    g += `<text x="${X(i)}" y="${H - 8}" text-anchor="${anchor}" fill="${css('--text-2')}" font-size="11">` +
         xs[i].slice(5, 16).replace('T', ' ') + `</text>`;
  }
  for (const s of DATA.sources) {
    const pts = seriesBySource[s];
    if (!pts) continue;
    const d = pts.map(p => `${X(idx[p[0]])},${Y(p[1])}`).join(' ');
    g += `<polyline points="${d}" fill="none" stroke="${color(s)}" stroke-width="2" stroke-linejoin="round"/>`;
    if (pts.length === 1) g += `<circle cx="${X(idx[pts[0][0]])}" cy="${Y(pts[0][1])}" r="3" fill="${color(s)}"/>`;
  }
  g += `<line id="xh" y1="${m.t}" y2="${H - m.b}" stroke="${css('--text-2')}" stroke-width="1" opacity="0"/>`;
  el.innerHTML = `<div class="card"><svg viewBox="0 0 ${W} ${H}">${g}</svg></div>`;

  const svg = el.querySelector('svg'), xh = svg.querySelector('#xh');
  svg.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect(), sx = W / r.width;
    const px = (e.clientX - r.left) * sx;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (W - m.l - m.r) * (n - 1))));
    xh.setAttribute('x1', X(i)); xh.setAttribute('x2', X(i)); xh.setAttribute('opacity', .5);
    const rows = DATA.sources.flatMap(s => {
      const p = (seriesBySource[s] || []).find(p => p[0] === xs[i]);
      return p ? [`<div class="row"><span><i class="swatch" style="background:${color(s)}"></i> ${s}</span><b>${fmt(p[1])}</b></div>`] : [];
    });
    tip.innerHTML = `<div class="t">${xs[i].replace('T', ' ').replace('Z', ' UTC')}</div>` + rows.join('');
    tip.style.display = 'block';
    tip.style.left = Math.min(innerWidth - 190, e.clientX + 14) + 'px';
    tip.style.top = (e.clientY + 14) + 'px';
  });
  svg.addEventListener('mouseleave', () => { tip.style.display = 'none'; xh.setAttribute('opacity', 0); });
}

// Small multiples: 1 chart / GPU, cùng mapping màu
const chartsEl = document.getElementById('charts');
for (const gpu of DATA.gpus) {
  const xs = [...new Set(Object.values(DATA.series[gpu]).flat().map(p => p[0]))].sort();
  const div = document.createElement('div');
  chartsEl.appendChild(div);
  lineChart(div, gpu, DATA.series[gpu], xs);
}

// Intraday: bar theo giờ UTC cho GPU headline (vast)
(function () {
  const data = DATA.intraday[DATA.headline] || {};
  const hours = Object.keys(data).map(Number).sort((a, b) => a - b);
  if (!hours.length) return;
  const W = 980, H = 200, m = {t: 10, r: 10, b: 24, l: 44};
  const vals = hours.map(h => data[h]);
  const hi = Math.max(...vals) * 1.1;
  const bw = (W - m.l - m.r) / 24;
  const Y = v => H - m.b - v / hi * (H - m.t - m.b);
  let g = '';
  for (const v of ticks(0, hi, 3)) {
    g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="${css('--grid')}"/>` +
         `<text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end" fill="${css('--text-2')}" font-size="11">${fmt(v)}</text>`;
  }
  for (let h = 0; h < 24; h++) {
    const x = m.l + h * bw;
    if (data[h] != null) {
      g += `<rect x="${x + 1}" y="${Y(data[h])}" width="${bw - 2}" height="${H - m.b - Y(data[h])}"
        rx="4" fill="${color('vast')}" data-h="${h}"/>`;
    }
    if (h % 3 === 0) g += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle" fill="${css('--text-2')}" font-size="11">${h}h</text>`;
  }
  const el = document.getElementById('intraday');
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`;
  el.querySelectorAll('rect').forEach(r => {
    r.addEventListener('mousemove', e => {
      const h = r.dataset.h;
      tip.innerHTML = `<div class="t">${h}:00–${h}:59 UTC</div><div class="row"><span>median TB</span><b>${fmt(data[h])}</b></div>`;
      tip.style.display = 'block';
      tip.style.left = Math.min(innerWidth - 190, e.clientX + 14) + 'px';
      tip.style.top = (e.clientY + 14) + 'px';
    });
    r.addEventListener('mouseleave', () => tip.style.display = 'none');
  });
})();

// Bảng snapshot mới nhất (table view = relief cho màu contrast thấp)
document.getElementById('latest').innerHTML =
  '<tr><th>GPU</th><th>Nguồn</th><th>Median $/h</th><th>Min $/h</th><th>Offers</th><th>Lúc</th></tr>' +
  DATA.table.map(r =>
    `<tr><td>${r.gpu}</td><td><i class="swatch" style="background:${color(r.source)}"></i> ${r.source}</td>` +
    `<td>${fmt(r.median)}</td><td>${fmt(r.min)}</td><td>${r.offers}</td>` +
    `<td>${r.asof.replace('T', ' ').replace('Z', '')}</td></tr>`).join('');
</script></body></html>
"""


def main():
    rows = load_rows()
    payload = build(rows)
    html = (
        TEMPLATE
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
        .replace("__PALETTE__", ",".join(c[0] for c in COLORS.values()))
        .replace("__GENERATED__", payload["generated"])
        .replace("__DAYS__", str(payload["days"]))
        .replace("__HEADLINE__", HEADLINE_GPU)
    )
    OUT_PATH.write_text(html)
    print(f"Report: {OUT_PATH}\n")
    for f in payload["findings"]:
        print(" -", f)


if __name__ == "__main__":
    main()
