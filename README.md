# Linux Cloudflare WARP Installer (SOCKS5 Proxy Mode)

Công cụ tự động hóa cài đặt và cấu hình **Cloudflare WARP** cho máy chủ Linux (Data Center / VPS) hoàn toàn miễn phí, an toàn tuyệt đối cho kết nối SSH, tương thích toàn diện với các phiên bản Ubuntu.

---

## 🚀 Hỗ trợ các phiên bản hệ điều hành
* **Ubuntu 20.04 LTS (Focal Fossa)**
* **Ubuntu 22.04 LTS (Jammy Jellyfish)**
* **Ubuntu 24.04 LTS (Noble Numbat)**
* **Ubuntu 26.04 LTS (Resolute)**

---

## ⚠️ Tính năng an toàn cốt lõi (Safe by Default)

> [!CAUTION]
> **KHÔNG BAO GIỜ BỊ MẤT KẾT NỐI SSH:**  
> Mặc định chế độ Full Tunnel (VPN Card mạng ảo) của WARP sẽ ghi đè Default Gateway và làm ngắt kết nối SSH vào IP Public của máy chủ ngay lập tức.  
> Script này **bắt buộc chạy ở chế độ SOCKS5 Proxy (`127.0.0.1:40000`)**, tuyệt đối không can thiệp vào bảng định tuyến (Routing Table) của hệ điều hành. Toàn bộ lưu lượng SSH, Web Server, DB hiện có vẫn hoạt động 100% bình thường.

---

## 🛠️ Cài đặt nhanh trong 1 dòng lệnh

### Cách 1: Clone repo và chạy cài đặt
```bash
git clone https://github.com/Datahub-DC/cloudflare-warp-app.git
cd cloudflare-warp-app
sudo bash install.sh
```

### Cách 2: Chạy trực tiếp qua cURL / Bash
```bash
curl -fsSL https://raw.githubusercontent.com/Datahub-DC/cloudflare-warp-app/main/install.sh | sudo bash
```

---

## ⚡ Các tính năng tự động của Script

1. **Tự động nhận diện bản phân phối:** Tự động phát hiện Codename (`focal`, `jammy`, `noble`, `resolute`) để chọn đúng kho APT Cloudflare chính thức.
2. **Khắc phục tường lửa Data Center (Chặn Port 80 Outbound):** Tự động phát hiện nếu cổng 80 ra ngoài bị chặn và tự động chuyển đổi kho lưu trữ APT sang **HTTPS** (`https://archive.ubuntu.com/`).
3. **Cài đặt & Kích hoạt:** Tự động thêm GPG key, repository và cài đặt `cloudflare-warp`.
4. **Cấu hình SOCKS5 Proxy:** Thiết lập cổng `127.0.0.1:40000`, kích hoạt kết nối và chạy kiểm tra định tuyến tự động (`warp=on`).

---

## 📖 Hướng dẫn sử dụng sau khi cài đặt

### 1. Tăng tốc Git CLI (Chỉ cho GitHub/GitLab quốc tế)
```bash
# Chỉ riêng GitHub đi qua WARP SOCKS5:
git config --global http."https://github.com/".proxy "socks5://127.0.0.1:40000"

# Chỉ riêng GitLab đi qua WARP SOCKS5:
git config --global http."https://gitlab.com/".proxy "socks5://127.0.0.1:40000"

# Khi nào muốn tắt:
git config --global --unset http."https://github.com/".proxy
```

### 2. Sử dụng với cURL
```bash
curl --socks5-hostname 127.0.0.1:40000 -O https://example.com/file.tar.gz
```

### 3. Dùng biến môi trường tạm thời cho phiên Terminal / CI-CD
```bash
export all_proxy="socks5://127.0.0.1:40000"
export ALL_PROXY="socks5://127.0.0.1:40000"

# Tắt proxy:
unset all_proxy ALL_PROXY
```

### 4. Cấu hình cho Docker Daemon (Khuyên dùng NO_PROXY)
> [!TIP]
> Docker Hub kéo trực tiếp qua mạng nội địa thường rất nhanh (~200 Mbps). Nếu cần proxy cho các registry quốc tế khác, cấu hình danh sách `NO_PROXY` để bỏ qua Docker Hub:

Tạo file `/etc/systemd/system/docker.service.d/http-proxy.conf`:
```ini
[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:40000"
Environment="HTTPS_PROXY=socks5://127.0.0.1:40000"
Environment="NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com"
```
Khởi động lại Docker:
```bash
sudo systemctl daemon-reload && sudo systemctl restart docker
```

### 5. Tăng tốc GitLab CI/CD Pipeline & GitLab Runner
Áp dụng cho các máy chủ tự host GitLab Runner đặt tại Data Center để khắc phục tình trạng kéo code từ `gitlab.com` hoặc tải package (NPM, PyPI, Maven, Go) bị chậm:

#### A. Cấu hình cho Runner (`/etc/gitlab-runner/config.toml`):
> [!IMPORTANT]
> Nếu Runner sử dụng **Docker Executor**, bắt buộc phải cấu hình `network_mode = "host"` để container job có thể truy cập được SOCKS5 Proxy `127.0.0.1:40000` của máy chủ Host!

```toml
[[runners]]
  name = "warp-docker-runner"
  url = "https://gitlab.com"
  executor = "docker"
  environment = [
    "ALL_PROXY=socks5://127.0.0.1:40000",
    "NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.com"
  ]
  [runners.docker]
    network_mode = "host"
```
*(Xem file mẫu đầy đủ tại [gitlab-runner.example.toml](file:///root/linux-cloudflare-warp/gitlab-runner.example.toml))*

#### B. Cấu hình trong `.gitlab-ci.yml` (Toàn bộ Pipeline):
```yaml
variables:
  ALL_PROXY: "socks5://127.0.0.1:40000"
  HTTP_PROXY: "socks5://127.0.0.1:40000"
  HTTPS_PROXY: "socks5://127.0.0.1:40000"
  NO_PROXY: "localhost,127.0.0.1,docker.io,*.docker.com"
```
*(Xem file pipeline mẫu đầy đủ cho Node, Python, Docker tại [gitlab-ci.example.yml](file:///root/linux-cloudflare-warp/gitlab-ci.example.yml))*

---

## 🖥️ Giao Diện Trực Quan Thay Vì Gõ Lệnh CLI

Để người dùng không cần phải ghi nhớ các câu lệnh phức tạp, công cụ hỗ trợ **2 loại giao diện trực quan**:

### 1. 🌐 Web Dashboard Hiện Đại & Bảo Mật (Trên trình duyệt)
Giao diện Web siêu nhẹ (chạy bằng Python 3 có sẵn, không cần cài đặt thêm bất kỳ thư viện nào):
* 🔐 **Bảo mật & Chống Hack toàn diện:**
  * Trang đăng nhập Dark Mode Glassmorphism bảo vệ tất cả endpoint UI và REST API.
  * Mã hóa mật khẩu chuẩn công nghiệp **SHA-256 + 16-byte Random Salt**.
  * **Chống Brute-Force Rate Limiting:** Tự động khóa IP 5 phút nếu nhập sai quá 5 lần liên tiếp.
  * Quản lý phiên bằng Session Cookie bảo mật (`HttpOnly`, `SameSite=Lax`, tự hủy khi hết hạn).
  * Tiêu đề bảo mật HTTP (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`).
* **Bật / Tắt WARP** với 1 cú click chuột.
* **Bật / Tắt Proxy cho Docker** (tự động cấu hình `NO_PROXY` cho Docker Hub để không bị bóp băng thông).
* **Bật / Tắt Proxy cho GitHub CLI** (`github.com`) & **GitLab CLI** (`gitlab.com`).
* **Đổi cổng SOCKS5 Proxy** trực quan.
* **Đo tốc độ mạng Đa Quốc Gia (Multi-Region Speed Test):** Đo kiểm tốc độ và độ trễ tới 8 Data Center quốc tế (🇸🇬 Singapore, 🇯🇵 Nhật Bản, 🇩🇪 Đức, 🇺🇸 Mỹ Bờ Đông/Tây, 🇬🇧 Anh Quốc, 🇫🇮 Phần Lan) hoặc chạy Benchmark toàn bộ cùng lúc.
* **Đổi mật khẩu trực tiếp:** Hỗ trợ đổi mật khẩu ngay trên giao diện Web (`🔑 Đổi mật khẩu`).
* **Xem nhật ký dịch vụ (Real-time Logs)**.

```bash
# Khởi chạy Web Dashboard trực tiếp:
sudo python3 web_dashboard.py
# Hoặc chạy qua script:
sudo bash install.sh --dashboard

# Cài đặt thành dịch vụ hệ thống (tự chạy ngầm cùng hệ thống khi khởi động lại):
sudo bash install.sh --dashboard-service
```
*Truy cập trình duyệt tại:* **`http://<IP_MAY_CHU>:8888`**
* **Tài khoản đăng nhập mặc định:**
  * Tên đăng nhập: `admin`
  * Mật khẩu: `datahub@2026`
* **Đổi mật khẩu đăng nhập bằng dòng lệnh:**
  ```bash
  sudo bash install.sh --set-password "MatKhauMoiCuaBan@2026"
  ```

---

### 2. 📟 Terminal Interactive Menu (TUI trong SSH)
Nếu không muốn mở cổng web ra ngoài, bạn có thể quản lý trực tiếp bằng menu số trong SSH:

```bash
# Mở menu điều khiển:
sudo bash menu.sh
# Hoặc:
sudo bash install.sh --menu
```

*Giao diện Menu trực quan:*
```text
╔══════════════════════════════════════════════════════════════════════╗
║   CLOUDFLARE WARP CONTROL CENTER - BẢNG ĐIỀU KHIỂN TERMINAL (TUI)     ║
╚══════════════════════════════════════════════════════════════════════╝
  Trạng thái  : ● ĐANG KẾT NỐI (Connected)
  Chế độ      : SOCKS5 Proxy (An toàn tuyệt đối cho SSH)
  Cổng Proxy  : 127.0.0.1:40000
  Tích hợp    : Docker [Bật (kèm NO_PROXY)] | Git [Bật] | GitLab [Bật]
──────────────────────────────────────────────────────────────────────
  [1] Bật kết nối WARP (Connect)
  [2] Tạm ngắt kết nối WARP (Disconnect)
  [3] Đổi cổng SOCKS5 Proxy (Change Port)
  [4] Bật / Tắt Proxy cho Docker Daemon (kèm NO_PROXY)
  [5] Bật / Tắt Proxy cho GitHub CLI (github.com)
  [6] Bật / Tắt Proxy cho GitLab CLI (gitlab.com)
  [7] 🦊 Xem cấu hình tăng tốc GitLab CI/CD & Runner
  [8] ⚡ Đo kiểm tốc độ mạng quốc tế (Speed Test)
  [9] 🌐 Mở Web Dashboard trên trình duyệt (Port 8888)
  [10] 🔐 Đổi mật khẩu Web Dashboard
  [11] 📋 Xem log dịch vụ (warp-svc logs)
  [0] Thoát
```

---

## 📌 Các lệnh quản lý tiện ích

```bash
# Mở menu Terminal
sudo bash install.sh --menu

# Chạy Web Dashboard
sudo bash install.sh --dashboard

# Cài đặt Web Dashboard chạy nền cùng hệ thống
sudo bash install.sh --dashboard-service

# Kiểm tra trạng thái kết nối
sudo bash install.sh --status

# Gỡ bỏ cài đặt hoàn toàn khỏi hệ thống
sudo bash install.sh --uninstall

# Xem trợ giúp
sudo bash install.sh --help
```

---

## 📄 Tài liệu chi tiết
Chi tiết về số liệu đo kiểm thực tế (Hetzner Đức vs Docker Hub), nguyên lý định tuyến và cấu hình Privoxy nâng cao: xem tại [CF_Warp_guideline.md](file:///root/linux-cloudflare-warp/CF_Warp_guideline.md).
