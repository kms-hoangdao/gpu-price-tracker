#!/usr/bin/env python3
"""Thu thập snapshot giá thuê GPU từ Vast.ai public API.

Chạy định kỳ bằng cron (mỗi giờ). Mỗi lần chạy:
- Ghi 1 dòng thống kê giá cho mỗi GPU vào data/prices.csv (dữ liệu chính để vẽ chart)
- Lưu toàn bộ offer thô vào data/raw/<timestamp>.json.gz (để phân tích sâu sau này)

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

# Các GPU đáng theo dõi cho bài phân tích. Tên phải khớp gpu_name của Vast.ai.
GPUS = [
    "H100 SXM",
    "H100 NVL",
    "H200",
    "B200",
    "A100 SXM4",
    "RTX 4090",
    "RTX 5090",
]

API_URL = "https://console.vast.ai/api/v0/bundles/"
DATA_DIR = Path(__file__).parent / "data"
CSV_PATH = DATA_DIR / "prices.csv"
CSV_FIELDS = [
    "timestamp_utc",
    "gpu",
    "offers",
    "min_usd_hr",
    "p10_usd_hr",
    "median_usd_hr",
    "verified_offers",
    "verified_median_usd_hr",
]


def fetch_offers(gpu_name):
    query = {
        "gpu_name": {"eq": gpu_name},
        "rentable": {"eq": True},
        "external": {"eq": False},
        "type": "on-demand",
        "limit": 1000,
        "order": [["dph_total", "asc"]],
    }
    url = API_URL + "?q=" + urllib.parse.quote(json.dumps(query))
    req = urllib.request.Request(url, headers={"User-Agent": "gpu-price-research/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["offers"]


def snapshot_row(timestamp, gpu_name, offers):
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
        "gpu": gpu_name,
        "offers": len(prices),
        "min_usd_hr": round(prices[0], 4),
        "p10_usd_hr": round(prices[max(0, len(prices) // 10 - 1)], 4),
        "median_usd_hr": round(statistics.median(prices), 4),
        "verified_offers": len(verified),
        "verified_median_usd_hr": round(statistics.median(verified), 4) if verified else "",
    }


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA_DIR.joinpath("raw").mkdir(parents=True, exist_ok=True)

    rows, raw = [], {}
    for gpu in GPUS:
        try:
            offers = fetch_offers(gpu)
        except Exception as e:
            print(f"[WARN] {gpu}: {e}", file=sys.stderr)
            continue
        raw[gpu] = offers
        row = snapshot_row(timestamp, gpu, offers)
        if row:
            rows.append(row)
        time.sleep(1)  # lịch sự với API công khai

    if not rows:
        sys.exit("Không lấy được dữ liệu GPU nào — kiểm tra mạng hoặc API đổi format.")

    write_header = not CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    raw_path = DATA_DIR / "raw" / f"{timestamp.replace(':', '')}.json.gz"
    with gzip.open(raw_path, "wt") as f:
        json.dump({"timestamp_utc": timestamp, "offers_by_gpu": raw}, f)

    for row in rows:
        print(
            f"{row['gpu']:>10}: {row['offers']:>4} offers | "
            f"min ${row['min_usd_hr']}/h | median ${row['median_usd_hr']}/h | "
            f"verified median ${row['verified_median_usd_hr'] or 'n/a'}/h"
        )


if __name__ == "__main__":
    main()
