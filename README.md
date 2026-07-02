# GPU Price Tracker — bước validate

Script thu thập giá thuê GPU từ Vast.ai public API (không cần key), phục vụ bài phân tích
"30 ngày giá GPU spot" để đo nhu cầu trước khi build sản phẩm thật.

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

- `data/prices.csv` — mỗi giờ 1 dòng/GPU: min, p10, median, verified median ($/GPU/giờ).
  Đây là dữ liệu chính để vẽ chart cho bài viết.
- `data/raw/<timestamp>.json.gz` — toàn bộ offer thô (region, verified, specs) để sau này
  phân tích sâu hơn (giá theo region, giờ nào trong ngày rẻ nhất...). ~90KB/lần chạy,
  ~65MB/tháng.

## Ghi chú phân tích

- `dph_total` của Vast là giá cả máy → script đã chia `num_gpus` để ra giá mỗi GPU.
- `min` thường là host unverified/chập chờn — khi viết bài, dùng `p10` hoặc
  `verified_median` làm "giá thị trường" thì trung thực hơn.
