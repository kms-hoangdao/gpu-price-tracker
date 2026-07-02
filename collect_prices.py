#!/usr/bin/env python3
"""Thu thập snapshot giá thuê GPU từ các nguồn public API.

Nguồn hiện tại:
- vast: Vast.ai marketplace (nhiều offer/GPU -> có phân phối giá min/p10/median)
- runpod-secure / runpod-community: RunPod (giá niêm yết cố định/GPU -> offers=1)

Chạy định kỳ bằng cron/GitHub Actions (mỗi giờ). Mỗi lần chạy:
- Ghi 1 dòng thống kê cho mỗi (source, GPU) vào data/prices.csv
- Lưu response thô vào data/raw/<timestamp>.json.gz

Không cần API key. Chỉ dùng stdlib.
"""

import csv
import gzip
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Các GPU đáng theo dõi. Tên phải khớp gpu_name của Vast.ai.
GPUS = [
    "H100 SXM",
    "H100 NVL",
    "H200",
    "B200",
    "A100 SXM4",
    "RTX 4090",
    "RTX 5090",
]

# displayName của RunPod -> tên chuẩn trong GPUS
RUNPOD_GPU_MAP = {
    "H100 SXM": "H100 SXM",
    "H100 NVL": "H100 NVL",
    "H200 SXM": "H200",
    "B200": "B200",
    "A100 SXM": "A100 SXM4",
    "RTX 4090": "RTX 4090",
    "RTX 5090": "RTX 5090",
}

VAST_URL = "https://console.vast.ai/api/v0/bundles/"
RUNPOD_URL = "https://api.runpod.io/graphql"
USER_AGENT = "gpu-price-research/0.1"
DATA_DIR = Path(__file__).parent / "data"
CSV_PATH = DATA_DIR / "prices.csv"
CSV_FIELDS = [
    "timestamp_utc",
    "source",
    "gpu",
    "offers",
    "min_usd_hr",
    "p10_usd_hr",
    "median_usd_hr",
    "verified_offers",
    "verified_median_usd_hr",
]


def http_json(url, data=None, headers=None):
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_vast_offers(gpu_name):
    query = {
        "gpu_name": {"eq": gpu_name},
        "rentable": {"eq": True},
        "external": {"eq": False},
        "type": "on-demand",
        "limit": 1000,
        "order": [["dph_total", "asc"]],
    }
    url = VAST_URL + "?q=" + urllib.parse.quote(json.dumps(query))
    return http_json(url)["offers"]


def vast_row(timestamp, gpu_name, offers):
    # dph_total là giá cả máy; chia num_gpus để ra giá mỗi GPU/giờ
    prices = sorted(
        o["dph_total"] / o["num_gpus"]
        for o in offers
        if o.get("num_gpus") and o.get("dph_total")
    )
    verified = sorted(
        o["dph_total"] / o["num_gpus"]
        for o in offers
        if o.get("num_gpus") and o.get("dph_total") and o.get("verification") == "verified"
    )
    if not prices:
        return None
    return {
        "timestamp_utc": timestamp,
        "source": "vast",
        "gpu": gpu_name,
        "offers": len(prices),
        "min_usd_hr": round(prices[0], 4),
        "p10_usd_hr": round(prices[max(0, len(prices) // 10 - 1)], 4),
        "median_usd_hr": round(statistics.median(prices), 4),
        "verified_offers": len(verified),
        "verified_median_usd_hr": round(statistics.median(verified), 4) if verified else "",
    }


def fetch_runpod_gpu_types():
    body = json.dumps(
        {"query": "query { gpuTypes { id displayName securePrice communityPrice } }"}
    ).encode()
    data = http_json(RUNPOD_URL, data=body, headers={"Content-Type": "application/json"})
    return data["data"]["gpuTypes"]


def runpod_rows(timestamp, gpu_types):
    # Giá RunPod là niêm yết cố định theo GPU type; giá 0 nghĩa là không có hàng
    rows = []
    for t in gpu_types:
        gpu = RUNPOD_GPU_MAP.get(t["displayName"])
        if not gpu:
            continue
        for market, price in [
            ("runpod-secure", t.get("securePrice")),
            ("runpod-community", t.get("communityPrice")),
        ]:
            if not price:
                continue
            rows.append({
                "timestamp_utc": timestamp,
                "source": market,
                "gpu": gpu,
                "offers": 1,
                "min_usd_hr": price,
                "p10_usd_hr": price,
                "median_usd_hr": price,
                "verified_offers": "",
                "verified_median_usd_hr": "",
            })
    return rows


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA_DIR.joinpath("raw").mkdir(parents=True, exist_ok=True)

    rows, raw = [], {}

    vast_raw = {}
    for gpu in GPUS:
        try:
            offers = fetch_vast_offers(gpu)
        except Exception as e:
            print(f"[WARN] vast/{gpu}: {e}", file=sys.stderr)
            continue
        vast_raw[gpu] = offers
        row = vast_row(timestamp, gpu, offers)
        if row:
            rows.append(row)
        time.sleep(1)  # lịch sự với API công khai
    raw["vast"] = vast_raw

    try:
        gpu_types = fetch_runpod_gpu_types()
        raw["runpod"] = gpu_types
        rows.extend(runpod_rows(timestamp, gpu_types))
    except Exception as e:
        print(f"[WARN] runpod: {e}", file=sys.stderr)

    if not rows:
        sys.exit("Không lấy được dữ liệu từ nguồn nào — kiểm tra mạng hoặc API đổi format.")

    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    raw_path = DATA_DIR / "raw" / f"{timestamp.replace(':', '')}.json.gz"
    with gzip.open(raw_path, "wt") as f:
        json.dump({"timestamp_utc": timestamp, "sources": raw}, f)

    for row in rows:
        print(
            f"{row['source']:>17} | {row['gpu']:>10}: {row['offers']:>4} offers | "
            f"min ${row['min_usd_hr']}/h | median ${row['median_usd_hr']}/h"
        )


if __name__ == "__main__":
    main()
