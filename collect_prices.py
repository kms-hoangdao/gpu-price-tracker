#!/usr/bin/env python3
"""Thu thập snapshot giá thuê GPU từ các nguồn public API.

Nguồn hiện tại (cột source trong CSV):
- vast: Vast.ai marketplace (nhiều offer/GPU -> phân phối giá min/p10/median)
- runpod-secure / runpod-community: RunPod (giá niêm yết cố định -> offers=1)
- datacrunch / datacrunch-spot: DataCrunch on-demand & spot (giá niêm yết -> offers=1)
- cudo: Cudo Compute (giá/GPU theo từng datacenter -> phân phối nhỏ;
  lưu ý giá Cudo chưa gồm vCPU/RAM tính riêng)

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
    "H100 PCIE",
    "H200",
    "B200",
    "A100 SXM4",
    "A100 PCIE",
    "L40S",
    "RTX PRO 6000 WS",
    "RTX A6000",
    "RTX 3090",
    "RTX 4090",
    "RTX 5080",
    "RTX 5090",
]

# Tên GPU của từng provider -> tên chuẩn trong GPUS (chỉ map biến thể tương đương thật)
RUNPOD_GPU_MAP = {
    "H100 SXM": "H100 SXM",
    "H100 NVL": "H100 NVL",
    "H100 PCIe": "H100 PCIE",
    "H200 SXM": "H200",
    "B200": "B200",
    "A100 SXM": "A100 SXM4",
    "A100 PCIe": "A100 PCIE",
    "L40S": "L40S",
    "RTX A6000": "RTX A6000",
    "RTX 3090": "RTX 3090",
    "RTX 4090": "RTX 4090",
    "RTX 5080": "RTX 5080",
    "RTX 5090": "RTX 5090",
}
DATACRUNCH_GPU_MAP = {
    "H100 SXM5 80GB": "H100 SXM",
    "H200 SXM5 141GB": "H200",
    "B200 SXM6 180GB": "B200",
    "A100 SXM4 80GB": "A100 SXM4",
    "L40S 48GB": "L40S",
    "RTX A6000 48GB": "RTX A6000",
}
CUDO_GPU_MAP = {
    "H100 SXM": "H100 SXM",
    "A100 80GB PCIe": "A100 PCIE",
}

VAST_URL = "https://console.vast.ai/api/v0/bundles/"
RUNPOD_URL = "https://api.runpod.io/graphql"
DATACRUNCH_URL = "https://api.datacrunch.io/v1/instance-types"
CUDO_URL = "https://rest.compute.cudo.org/v1/vms/machine-types"
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


def stats_row(timestamp, source, gpu, prices, verified=None):
    """Một dòng CSV từ danh sách giá ($/GPU/giờ). Giá niêm yết thì prices có 1 phần tử."""
    prices = sorted(prices)
    if not prices:
        return None
    verified = sorted(verified) if verified else []
    return {
        "timestamp_utc": timestamp,
        "source": source,
        "gpu": gpu,
        "offers": len(prices),
        "min_usd_hr": round(prices[0], 4),
        "p10_usd_hr": round(prices[max(0, len(prices) // 10 - 1)], 4),
        "median_usd_hr": round(statistics.median(prices), 4),
        "verified_offers": len(verified) if verified else "",
        "verified_median_usd_hr": round(statistics.median(verified), 4) if verified else "",
    }


# --- Vast.ai ---

def fetch_vast_offers(gpu_name):
    # API cap ~64 offers/response nên phân trang bằng cursor giá:
    # sort dph_total tăng dần, trang sau lọc dph_total > giá cao nhất đã thấy
    seen, cursor = {}, None
    for _ in range(10):
        query = {
            "gpu_name": {"eq": gpu_name},
            "rentable": {"eq": True},
            "external": {"eq": False},
            "type": "on-demand",
            "limit": 500,
            "order": [["dph_total", "asc"]],
        }
        if cursor is not None:
            query["dph_total"] = {"gt": cursor}
        url = VAST_URL + "?q=" + urllib.parse.quote(json.dumps(query))
        batch = http_json(url)["offers"]
        new = [o for o in batch if o["id"] not in seen]
        for o in new:
            seen[o["id"]] = o
        if len(batch) < 60 or not new:
            break
        cursor = max(o["dph_total"] for o in batch)
        time.sleep(1)  # tránh rate limit khi phân trang
    return list(seen.values())


def vast_rows(timestamp):
    raw = {}
    rows = []
    for gpu in GPUS:
        try:
            offers = fetch_vast_offers(gpu)
        except Exception as e:
            if "429" in str(e):  # rate limit: nghỉ rồi thử lại 1 lần
                time.sleep(20)
                try:
                    offers = fetch_vast_offers(gpu)
                except Exception as e2:
                    print(f"[WARN] vast/{gpu}: {e2}", file=sys.stderr)
                    continue
            else:
                print(f"[WARN] vast/{gpu}: {e}", file=sys.stderr)
                continue
        raw[gpu] = offers
        # dph_total là giá cả máy; chia num_gpus để ra giá mỗi GPU/giờ
        usable = [o for o in offers if o.get("num_gpus") and o.get("dph_total")]
        prices = [o["dph_total"] / o["num_gpus"] for o in usable]
        verified = [
            o["dph_total"] / o["num_gpus"]
            for o in usable
            if o.get("verification") == "verified"
        ]
        row = stats_row(timestamp, "vast", gpu, prices, verified)
        if row:
            rows.append(row)
        time.sleep(1)  # lịch sự với API công khai
    return rows, raw


# --- RunPod ---

def runpod_rows(timestamp):
    body = json.dumps(
        {"query": "query { gpuTypes { id displayName securePrice communityPrice } }"}
    ).encode()
    data = http_json(RUNPOD_URL, data=body, headers={"Content-Type": "application/json"})
    gpu_types = data["data"]["gpuTypes"]
    rows = []
    for t in gpu_types:
        gpu = RUNPOD_GPU_MAP.get(t["displayName"])
        if not gpu:
            continue
        # Giá 0 nghĩa là không có hàng
        for market, price in [
            ("runpod-secure", t.get("securePrice")),
            ("runpod-community", t.get("communityPrice")),
        ]:
            if price:
                rows.append(stats_row(timestamp, market, gpu, [price]))
    return rows, gpu_types


# --- DataCrunch ---

def datacrunch_rows(timestamp):
    types = http_json(DATACRUNCH_URL)
    # Mỗi GPU có nhiều size (1x/2x/4x...) cùng giá mỗi GPU -> lấy giá thấp nhất
    ondemand, spot = {}, {}
    for t in types:
        desc = t.get("gpu", {}).get("description") or ""
        model = desc.split("x ", 1)[-1] if "x " in desc else desc
        gpu = DATACRUNCH_GPU_MAP.get(model)
        n = t.get("gpu", {}).get("number_of_gpus")
        if not gpu or not n:
            continue
        for bucket, key in [(ondemand, "price_per_hour"), (spot, "spot_price")]:
            price = float(t.get(key) or 0) / n
            if price:
                bucket[gpu] = min(bucket.get(gpu, price), price)
    rows = [stats_row(timestamp, "datacrunch", g, [p]) for g, p in ondemand.items()]
    rows += [stats_row(timestamp, "datacrunch-spot", g, [p]) for g, p in spot.items()]
    return rows, types


# --- Cudo Compute ---

def cudo_rows(timestamp):
    data = http_json(CUDO_URL)["machineTypes"]
    # gpuPriceHr là giá mỗi GPU, mỗi entry là một (datacenter, machine type)
    prices_by_gpu = {}
    for t in data:
        gpu = CUDO_GPU_MAP.get(t.get("gpuModel") or "")
        price = float((t.get("gpuPriceHr") or {}).get("value") or 0)
        if gpu and price:
            prices_by_gpu.setdefault(gpu, []).append(price)
    rows = [stats_row(timestamp, "cudo", g, ps) for g, ps in prices_by_gpu.items()]
    return rows, data


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA_DIR.joinpath("raw").mkdir(parents=True, exist_ok=True)

    rows, raw = [], {}
    sources = [
        ("vast", vast_rows),
        ("runpod", runpod_rows),
        ("datacrunch", datacrunch_rows),
        ("cudo", cudo_rows),
    ]
    for name, fetch in sources:
        try:
            source_rows, source_raw = fetch(timestamp)
            rows.extend(r for r in source_rows if r)
            raw[name] = source_raw
        except Exception as e:
            print(f"[WARN] {name}: {e}", file=sys.stderr)

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
