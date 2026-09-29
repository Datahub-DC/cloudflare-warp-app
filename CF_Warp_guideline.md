# HƯỚNG DẪN CÀI ĐẶT & TỐI ƯU HÓA CLOUDFLARE WARP TRÊN MÁY CHỦ DATA CENTER

> **Mục tiêu:** Tăng tốc đường truyền quốc tế (Git, CI/CD, Package, Server quốc tế), đồng thời tối ưu định tuyến để không làm chậm các dịch vụ có CDN gần (như Docker Hub).  
> **Môi trường áp dụng:** Ubuntu / Debian / RHEL trên hạ tầng DataHub DC (CMC Telecom).  
> **Chi phí:** 0 VNĐ (Cloudflare WARP Free Tier).

---

## 1. NGUYÊN LÝ HOẠT ĐỘNG & CẢNH BÁO AN TOÀN

### 1.1. Nguyên lý tăng tốc quốc tế
* Cloudflare sở hữu các trạm Anycast PoP đặt ngay tại Việt Nam (**SGN - TP.HCM** và **HAN - Hà Nội**), có kết nối peering trực tiếp với CMC Telecom qua hạ tầng **mạng nội địa (Domestic)** tốc độ cao.
* Khi kết nối WARP, dữ liệu từ server tới trạm Cloudflare được tính là băng thông trong nước. Từ Cloudflare, gói tin ra quốc tế sẽ chạy trên **hệ thống cáp quang riêng (Private Backbone)** của Cloudflare, vượt qua các điểm nghẽn và hạn chế bóp băng thông quốc tế thông thường.

### 1.2. ⚠️ Cảnh báo an toàn tuyệt đối
> [!CAUTION]
> **TUYỆT ĐỐI KHÔNG DÙNG CHẾ ĐỘ MẶC ĐỊNH (FULL TUNNEL / VPN MODE):**
> * Mặc định lệnh `warp-cli connect` sẽ tạo card mạng ảo và ghi đè Default Gateway (`0.0.0.0/0`).
> * Điều này sẽ làm **mất kết nối SSH vào IP Public** của máy chủ ngay lập tức!
>
> **GIẢI PHÁP BẮT BUỘC:** Chỉ chạy WARP ở **Chế độ Proxy (Proxy Mode - SOCKS5)**.
> * Chế độ này mở cổng lắng nghe tại `127.0.0.1:40000`, **KHÔNG đụng vào bảng định tuyến (Routing Table)** của hệ điều hành.
> * Các kết nối SSH, Web Server, Database qua IP Public vẫn hoạt động 100% bình thường.

---

## 2. KINH NGHIỆM THỰC TẾ TRÊN MÁY CHỦ DATAHUB DC

> [!IMPORTANT]
> **Lưu ý về Firewall Data Center (Chặn Port 80 Outbound):**  
> Máy chủ tại DC thường chặn cổng HTTP (port 80) đi ra ngoài. Nếu mirror APT đang dùng `http://` (đặc biệt là mirror mặc định `de.archive.ubuntu.com`), lệnh `apt update` và cài đặt sẽ bị treo / lỗi.
>
> **Khắc phục:** Cần chuyển đổi APT repositories sang **HTTPS** trước khi cài đặt.

Chạy lệnh chuyển sang mirror HTTPS chính thức:
```bash
sudo sed -i 's|http://de.archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
sudo sed -i 's|http://security.ubuntu.com/ubuntu/|https://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
```

---

## 3. CÁC BƯỚC CÀI ĐẶT CHI TIẾT (UBUNTU 24.04 / DEBIAN)

### Bước 1: Thêm Repository của Cloudflare & Cài đặt
```bash
# 1. Thêm GPG key của Cloudflare
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | sudo gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg

# 2. Thêm APT source với HTTPS
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/cloudflare-client.list

# 3. Cập nhật và cài đặt package
sudo apt update && sudo apt install -y cloudflare-warp
```

### Bước 2: Thiết lập WARP chạy ở Proxy Mode (SOCKS5)
Thực hiện lần lượt các lệnh sau (thêm cờ `--accept-tos` để không bị nhắc xác nhận điều khoản):

```bash
# 1. Đăng ký tài khoản máy trạm mới với Cloudflare
warp-cli --accept-tos registration new

# 2. Chuyển sang chế độ SOCKS5 Proxy (KHÔNG tạo card mạng ảo)
warp-cli --accept-tos mode proxy

# 3. Thiết lập cổng lắng nghe (Mặc định: 40000)
warp-cli --accept-tos proxy port 40000

# 4. Bật kết nối tunnel
warp-cli --accept-tos connect

# 5. Kiểm tra trạng thái kết nối
warp-cli --accept-tos status
```
*Kết quả mong đợi:* `Status update: Connected` và `Network: healthy`.

### Bước 3: Kiểm tra định tuyến qua SOCKS5 Proxy
```bash
curl --socks5-hostname 127.0.0.1:40000 https://cloudflare.com/cdn-cgi/trace
```
Output phải có các dòng:
* `warp=on` (Đã chạy qua đường truyền WARP).
* `colo=SIN` hoặc `colo=SGN` (Trạm Anycast tối ưu nhất).

---

## 4. KẾT QUẢ ĐO KIỂM THỰC TẾ & BÀI HỌC QUAN TRỌNG

### 4.1. Bảng đối chiếu tốc độ thực tế đo tại máy chủ DataHub DC:

| Tác vụ đo kiểm | Kích thước | Tải TRỰC TIẾP (CMC) | Tải qua WARP SOCKS5 | Đánh giá & Phân tích |
| :--- | :--- | :--- | :--- | :--- |
| **Server châu Âu (Hetzner Đức)** | 100 MB | **`2m 32s`** (670 KB/s) | **`51s`** (2.0 MB/s) |  **WARP nhanh gấp ~3 lần**. Cứu cánh cho các server quốc tế xa không có CDN. |
| **Docker Hub (`pytorch:latest`)** | ~3.66 GB | **`1m 54s`** (~24.7 MB/s) | **`31m 00s`** (~1.9 MB/s) | ⚠️ **WARP chậm hơn 16 lần**. Do Docker Hub bóp băng thông dải IP chia sẻ của WARP. |
| **Docker Hub (`vllm-openai:latest`)** | ~8.73 GB | **`5m 53s`** (~24.7 MB/s) | — |  Kéo trực tiếp đạt tới ~200 Mbps nhờ CDN Edge gần. |

### 4.2. Bài học cốt lõi:
1. **Dịch vụ có CDN gần (Docker Hub, Ubuntu Mirror nội địa, v.v.):** Tải trực tiếp qua mạng CMC nhanh hơn rất nhiều (~200 Mbps). **Không nên** đẩy toàn bộ qua WARP.
2. **Dịch vụ quốc tế không có CDN (Git quốc tế, máy chủ EU/US, PyPI, Hetzner, AWS non-CDN):** Qua WARP cho tốc độ và độ ổn định cao hơn gấp nhiều lần.

---

## 5. CẤU HÌNH ĐIỀU HƯỚNG TỐI ƯU (SMART ROUTING)

### 5.1. Cấu hình Docker Daemon: Bỏ qua Docker Hub, chỉ proxy các registry khác
Để Docker Hub tải trực tiếp tốc độ cao, nhưng các registry quốc tế khác vẫn đi qua WARP, cấu hình biến `NO_PROXY`:

Tạo file `/etc/systemd/system/docker.service.d/http-proxy.conf`:
```ini
[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:40000"
Environment="HTTPS_PROXY=socks5://127.0.0.1:40000"
Environment="NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23"
```

Áp dụng cấu hình:
```bash
sudo systemctl daemon-reload && sudo systemctl restart docker
```

> [!TIP]
> Nếu bạn chỉ dùng Docker Hub thông thường, cách tốt nhất là **không đặt proxy cho Docker Daemon** để Docker luôn kéo ở tốc độ tối đa.

### 5.2. Cấu hình Git CLI: Chỉ định proxy theo từng Domain cụ thể
Git hỗ trợ cấu hình proxy riêng biệt cho từng URL/Domain cực kỳ linh hoạt:

```bash
# Chỉ riêng GitHub đi qua WARP SOCKS5:
git config --global http."https://github.com/".proxy "socks5://127.0.0.1:40000"

# Chỉ riêng GitLab quốc tế đi qua WARP:
git config --global http."https://gitlab.com/".proxy "socks5://127.0.0.1:40000"

# Hủy cấu hình khi cần:
git config --global --unset http."https://github.com/".proxy
```
*(Các Git server nội bộ hoặc server trong nước vẫn tự động đi trực tiếp).*

### 5.3. Dùng cURL hoặc Scripts theo nhu cầu (On-Demand)
Khi cần tải file hoặc gọi API từ server quốc tế bị bóp băng thông:
```bash
# Cách 1: Dùng cờ trực tiếp
curl --socks5-hostname 127.0.0.1:40000 -O https://example.com/large-file.tar.gz

# Cách 2: Gán biến môi trường trong phiên làm việc hiện tại (hoặc trong CI/CD script)
export all_proxy="socks5://127.0.0.1:40000"
export ALL_PROXY="socks5://127.0.0.1:40000"

# Sau khi xong, hủy biến:
unset all_proxy ALL_PROXY
```

### 5.4. Tăng tốc GitLab CI/CD Pipeline & Runner
Đối với các máy chủ đóng vai trò làm GitLab Runner tự host (Self-hosted Runner) tại Data Center, việc kéo mã nguồn từ `gitlab.com` hoặc tải container image từ `registry.gitlab.com` thường bị bóp băng thông quốc tế.

#### 1. Cấu hình Runner (`/etc/gitlab-runner/config.toml`):
* Với **Docker Executor**, bắt buộc phải thêm `network_mode = "host"` để job container có thể kết nối tới SOCKS5 Proxy `127.0.0.1:40000` của máy chủ Host:
```toml
[[runners]]
  name = "warp-docker-runner"
  url = "https://gitlab.com"
  executor = "docker"
  environment = [
    "ALL_PROXY=socks5://127.0.0.1:40000",
    "HTTP_PROXY=socks5://127.0.0.1:40000",
    "HTTPS_PROXY=socks5://127.0.0.1:40000",
    "NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.com"
  ]
  [runners.docker]
    network_mode = "host"
```

#### 2. Cấu hình trong `.gitlab-ci.yml`:
Thêm vào đầu file pipeline để toàn bộ các bước (tải package NPM, pip, Go, clone submodule) tự động đi qua WARP:
```yaml
variables:
  ALL_PROXY: "socks5://127.0.0.1:40000"
  HTTP_PROXY: "socks5://127.0.0.1:40000"
  HTTPS_PROXY: "socks5://127.0.0.1:40000"
  NO_PROXY: "localhost,127.0.0.1,docker.io,*.docker.com"
```
*(Tham khảo mẫu hoàn chỉnh tại `gitlab-ci.example.yml` và `gitlab-runner.example.toml`).*

### 5.5. Giải pháp nâng cao: Dùng Privoxy làm Proxy điều hướng tự động
Nếu muốn một cổng HTTP proxy duy nhất (ví dụ `127.0.0.1:8118`) tự động nhận diện domain để đi thẳng hay đi qua WARP:

1. Cài đặt Privoxy:
   ```bash
   sudo apt install -y privoxy
   ```
2. Thêm vào cuối file cấu hình `/etc/privoxy/config`:
   ```text
   # Mặc định tất cả đi TRỰC TIẾP
   forward / .

   # Chỉ các domain quốc tế chỉ định mới forward qua WARP SOCKS5
   forward-socks5 .github.com 127.0.0.1:40000 .
   forward-socks5 .gitlab.com 127.0.0.1:40000 .
   forward-socks5 .huggingface.co 127.0.0.1:40000 .
   forward-socks5 .hetzner.com 127.0.0.1:40000 .
   ```
3. Khởi động lại: `sudo systemctl restart privoxy`.

---

## 6. BẢNG TRA CỨU LỆNH QUẢN LÝ NHANH (CHEATSHEET)

| Thao tác | Câu lệnh |
| :--- | :--- |
| **Kiểm tra trạng thái WARP** | `warp-cli --accept-tos status` |
| **Xem cấu hình chi tiết** | `warp-cli --accept-tos settings list` |
| **Ngắt kết nối WARP** | `warp-cli --accept-tos disconnect` |
| **Bật lại kết nối WARP** | `warp-cli --accept-tos connect` |
| **Kiểm tra IP & trạm PoP** | `curl --socks5-hostname 127.0.0.1:40000 https://cloudflare.com/cdn-cgi/trace` |
| **Khởi động lại Service** | `sudo systemctl restart warp-svc` |
| **Xem log dịch vụ WARP** | `sudo journalctl -u warp-svc -n 50 -f` |
| **Gỡ cài đặt hoàn toàn** | `sudo apt remove --purge -y cloudflare-warp` |
