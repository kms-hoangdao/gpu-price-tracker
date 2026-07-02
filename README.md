# GPU Price Tracker — bước validate

Script thu thập giá thuê GPU từ các public API (không cần key), phục vụ bài phân tích
"30 ngày giá GPU spot" để đo nhu cầu trước khi build sản phẩm thật.

Nguồn hiện tại (cột `source` trong CSV):
- `vast` — Vast.ai marketplace: nhiều offer/GPU nên có phân phối giá (min/p10/median)
- `runpod-secure`, `runpod-community` — RunPod: giá niêm yết cố định (offers=1, min=median)
- `datacrunch`, `datacrunch-spot` — DataCrunch: giá niêm yết on-demand và spot
- `cudo` — Cudo Compute: giá mỗi GPU theo từng datacenter (lưu ý: chưa gồm vCPU/RAM
  tính riêng, nên hơi thấp hơn giá thuê thực tế)

Đã thăm dò nhưng bỏ qua: Lambda, Hyperstack, TensorDock (API đều cần key),
Vultr (GPU fractional, khó map sang giá mỗi-GPU tương đương).

## Chạy tay

```bash
python3 collect_prices.py
```

## Chạy tự động mỗi giờ (cron)

```bash
crontab -e
# thêm dòng:
0 * * * * cd /Users/hoangdao/Downloads/Idea/gpu-price-tracker && /usr/bin/python3 collect_prices.py >> collect.log 2>&1
```

Lưu ý macOS: máy ngủ thì cron không chạy. Nếu muốn chắc chắn 24/7, chạy trên một VPS rẻ
(hoặc GitHub Actions schedule — repo private, commit file CSV sau mỗi lần chạy).

## Dữ liệu

- `data/prices.csv` — mỗi giờ 1 dòng/(source, GPU): min, p10, median, verified median
  ($/GPU/giờ). Đây là dữ liệu chính để vẽ chart cho bài viết.
- `data/raw/<timestamp>.json.gz` — toàn bộ offer thô (region, verified, specs) để sau này
  phân tích sâu hơn (giá theo region, giờ nào trong ngày rẻ nhất...). ~90KB/lần chạy,
  ~65MB/tháng.

## Ghi chú phân tích

- `dph_total` của Vast là giá cả máy → script đã chia `num_gpus` để ra giá mỗi GPU.
- `min` thường là host unverified/chập chờn — khi viết bài, dùng `p10` hoặc
  `verified_median` làm "giá thị trường" thì trung thực hơn.
