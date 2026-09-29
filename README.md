# ⚡ Linux Cloudflare WARP App (SOCKS5 Proxy & Web Control Center)

Công cụ tự động hóa cài đặt, cấu hình và quản trị **Cloudflare WARP** cho máy chủ Linux (Data Center / VPS / Cloud). Hoàn toàn miễn phí, **an toàn tuyệt đối cho kết nối SSH**, tương thích toàn diện với tất cả các phiên bản Ubuntu từ 20.04 đến 26.04 LTS.

Tích hợp sẵn **Web Dashboard Dark Glassmorphism 7 Tabs** có đăng nhập bảo mật, **Quản lý Proxy Dân Cư (Residential Proxy)** và **Terminal Menu (TUI)** tiện lợi, không cần ghi nhớ các câu lệnh phức tạp.

---

## 📑 Mục lục
1. [Hỗ trợ Hệ điều hành](#-hỗ-trợ-các-phiên-bản-hệ-điều-hành)
2. [Nguyên lý An toàn Cốt lõi (Safe for SSH)](#-tính-năng-an-toàn-cốt-lõi-safe-by-default)
3. [Cài đặt nhanh trong 1 dòng lệnh](#-cài-đặt-nhanh-trong-1-dòng-lệnh)
4. [Mô hình Định tuyến Thông minh (Smart Routing)](#-mô-hình-định-tuyến-thông-minh-smart-routing)
5. [🏡 Quản Lý & Tích Hợp Proxy Dân Cư (Residential Proxy)](#-quản-lý--tích-hợp-proxy-dân-cư-residential-proxy)
6. [Giao diện Trực quan (Web UI & TUI)](#-giao-diện-trực-quan-thay-vì-gõ-lệnh-cli)
   - [Web Dashboard 7 Tabs](#1--web-dashboard-hiện-đại--bảo-mật-trên-trình-duyệt)
   - [Terminal Interactive Menu](#2--terminal-interactive-menu-tui-trong-ssh)
7. [Tăng tốc GitLab CI/CD & Runner](#-tăng-tốc-gitlab-cicd-pipeline--gitlab-runner)
8. [Hướng dẫn Sử dụng CLI](#-hướng-dẫn-sử-dụng-sau-khi-cài-đặt)
9. [Các Lệnh Quản trị Nhanh](#-các-lệnh-quản-lý-tiện-ích)
10. [Bảo mật & Quản lý Mật khẩu](#-bảo-mật--quản-lý-mật-khẩu-web-ui)
11. [Tài liệu Chi tiết](#-tài-liệu-chi-tiết)

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
> Script này **bắt buộc chạy ở chế độ SOCKS5 Proxy (`127.0.0.1:40000`)**, tuyệt đối không can thiệp vào bảng định tuyến (Routing Table) của hệ điều hành. Toàn bộ lưu lượng SSH, Web Server, Database hiện có vẫn hoạt động 100% bình thường.

---

## 🛠️ Cài đặt nhanh trong 1 dòng lệnh

### Cách 1: Clone repo và chạy cài đặt (Khuyên dùng)
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
2. **Khắc phục tường lửa Data Center (Chặn Port 80 Outbound):** Tự động phát hiện nếu cổng 80 ra ngoài bị chặn và chuyển đổi kho APT sang **HTTPS** (`https://archive.ubuntu.com/`).
3. **Cài đặt & Kích hoạt:** Tự động thêm GPG key, repository và cài đặt `cloudflare-warp`.
4. **Cấu hình SOCKS5 Proxy:** Thiết lập cổng `127.0.0.1:40000`, kích hoạt kết nối và chạy kiểm tra định tuyến tự động (`warp=on`).

---

## 🔀 Mô hình Định tuyến Thông minh (Smart Routing)

Hệ thống cho phép định tuyến chọn lọc từng dịch vụ đi qua WARP mà không làm chậm máy chủ:

| Dịch vụ | Hướng kết nối | Tốc độ | Lý do |
| :--- | :--- | :--- | :--- |
| **SSH / Web / DB** | 🟢 Đi trực tiếp (Direct) | Nguyên bản | Giữ an toàn và phản hồi tức thì cho người quản trị |
| **Docker Hub** | 🟢 Đi trực tiếp (`NO_PROXY`) | ~200 Mbps | Tải image từ Docker Hub nội địa cực nhanh, không qua VPN |
| **Docker Daemon & Build** | ⚡ Qua WARP SOCKS5 | Cực nhanh | Kéo registry quốc tế (ghcr.io, quay.io, gcr.io) và cài đặt pip/npm trong container |
| **GitHub CLI** | ⚡ Qua WARP SOCKS5 | Cực nhanh | Khắc phục đứt cáp, tăng tốc `git clone/fetch/push` |
| **GitLab Quốc tế** | ⚡ Qua WARP SOCKS5 | Cực nhanh | Khắc phục tình trạng treo khi kéo code từ `gitlab.com` |
| **GitLab CI/CD Runner**| ⚡ Qua WARP SOCKS5 | Tối đa | Tăng tốc tải NPM, PyPI, Maven, Go module và images |

---

## 🏡 Quản Lý & Tích Hợp Proxy Dân Cư (Residential Proxy)

Bên cạnh Cloudflare WARP Anycast miễn phí, hệ thống hiện hỗ trợ **kết nối trực tiếp đến các nhà cung cấp Proxy Dân Cư (Clean Residential / ISP Private IP)** như BrightData, Oxylabs, Smartproxy, Webshare, IPRoyal, Proxy-Seller,...

### 🌟 Ưu Điểm Vượt Trội Của Proxy Dân Cư:
* **Tốc độ tải xuống vượt trội:** Băng thông cao, không bị bóp nghẽn hoặc giới hạn tải đồng thời.
* **IP Dân Cư Sạch (Clean Residential ISP):** Không bị nhận diện là Datacenter IP, hoàn toàn không bị chặn CAPTCHA khi kéo code từ GitHub, GitLab hoặc cào dữ liệu (crawling).
* **Bóc tách tự động thông minh (Smart Auto-Parser):** Chỉ cần dán chuỗi proxy thô dạng `ip:port:user:pass`, `user:pass@host:port` hoặc `socks5://...`, hệ thống sẽ tự động phân tích và điền vào form.
* **Đo kiểm chất lượng thời gian thực (Live Diagnostic & Benchmark):** Tự động đo độ trễ TTFB (ping ms), băng thông tải thực tế (MB/s), truy vấn IP Public và nhà mạng (ISP/ASN).
* **Chuyển đổi 1-Click (Egress Switcher):** Dễ dàng chuyển hướng toàn bộ Docker Daemon và Git CLI giữa **Cloudflare WARP Anycast** và **Proxy Dân Cư** mà không cần khởi động lại máy chủ.

---

## 🖥️ Giao Diện Trực Quan Thay Vì Gõ Lệnh CLI

Để người dùng không cần phải ghi nhớ các câu lệnh phức tạp, công cụ hỗ trợ **2 loại giao diện trực quan**:

### 1. 🌐 Web Dashboard Hiện Đại & Bảo Mật (Trên trình duyệt)
Giao diện Web siêu nhẹ (chạy bằng Python 3 standard library có sẵn, không cần cài thêm bất kỳ thư viện pip nào, hỗ trợ `ThreadingTCPServer` xử lý đa luồng mượt mà):

```bash
# Khởi chạy Web Dashboard trực tiếp:
sudo python3 web_dashboard.py
# Hoặc chạy qua script:
sudo bash install.sh --dashboard

# Cài đặt thành dịch vụ hệ thống (tự chạy ngầm cùng hệ thống khi khởi động lại):
sudo bash install.sh --dashboard-service
```
*Truy cập trình duyệt tại:* **`http://<IP_MAY_CHU>:8888`** *(Hoặc `http://127.0.0.1:8888`)*

#### 📑 Cấu trúc 7 Tab Chuyên Biệt & Tiện Lợi:
1. 📊 **Tổng quan & Kết nối (`#overview`):**
   * Theo dõi trạng thái Anycast thời gian thực (`status-pulse`), trạm PoP (VD: `SIN - Singapore`), cổng SOCKS5 Local, Egress IP Public.
   * Nút **Bật / Tắt WARP** nhanh với 1 cú click.
   * Thẻ tóm tắt 4 dịch vụ: Docker Proxy, Proxy Dân Cư, Git CLI, và Đo Tốc Độ Toàn Cầu kèm lối tắt chuyển tab.
   * Bảng câu lệnh cURL & Export biến môi trường kèm nút Copy nhanh.
2. ⚡ **Đo kiểm Tốc độ (`#speedtest`):**
   * Kiểm tra băng thông và độ trễ (ping/ms) đến 8 Cloud Data Center toàn cầu: 🇸🇬 Singapore, 🇯🇵 Tokyo, 🇩🇪 Đức Falkenstein & Nuremberg, 🇺🇸 Mỹ Ashburn & Hillsboro, 🇬🇧 Anh London, 🇫🇮 Phần Lan.
   * Nút phím tắt đo nhanh từng trạm hoặc chạy **🚀 Benchmark All** toàn bộ 8 trạm song song.
   * Đồng hồ số đo MB/s kèm thanh đo trực quan hóa tốc độ (Visual Progress Bar).
3. 🔀 **Điều hướng Proxy (`#routing`):**
   * Công tắc bật/tắt Proxy cho **Docker Daemon** (tự động kèm quy tắc `NO_PROXY` Docker Hub).
   * Công tắc tăng tốc riêng cho **GitHub CLI** (`github.com`).
   * Công tắc tăng tốc riêng cho **GitLab CLI** (`gitlab.com`).
   * Ô đổi cổng SOCKS5 Proxy trực tiếp (1024 - 65535).
   * Hướng dẫn cấu hình Privoxy chuyển đổi HTTP Proxy sang SOCKS5.
4. 🏡 **Proxy Dân Cư (`#residential`):**
   * Thanh điều khiển nguồn Egress hoạt động (Chuyển đổi 1-click giữa WARP và Proxy Dân Cư).
   * Hộp nhập nhanh chuỗi proxy với tính năng bóc tách tự động (`IP:PORT:USER:PASS`).
   * Cấu hình chi tiết giao thức SOCKS5 / HTTP / HTTPS, host, port, xác thực và `NO_PROXY`.
   * Thẻ chẩn đoán trực tiếp: Egress IP, ISP nhà mạng, quốc gia, độ trễ TTFB và tốc độ tải thực tế (MB/s).
   * Lệnh cURL & biến môi trường export mẫu cho terminal / CI-CD pipeline.
5. 🐳 **Docker Daemon Proxy & Build Console (`#docker`):**
   * **Quản lý Proxy Docker Daemon & Systemd:**
     - Xem trực quan trạng thái daemon (`docker info`), phiên bản Docker, địa chỉ Proxy, trạng thái file cấu hình systemd.
     - Tùy chỉnh danh sách `NO_PROXY` trực tiếp với các Preset 1-click: *Khuyên dùng (Docker Hub + Mạng nội bộ)*, *Toàn bộ qua WARP*, *Kubernetes / Internal LAN*.
     - Nút **⚡ Áp Dụng & Reload Daemon** (`systemctl daemon-reload && systemctl restart docker`) tự động nạp cấu hình mới mà không làm đứt kết nối máy chủ.
     - Nút **🛑 Tắt Proxy Docker** để khôi phục mặc định.
   * **Quét Thư Mục & Chọn Dự Án Dockerfile (Project Directory Scanner & Context):**
     - Quét tự động cây thư mục máy chủ (`/root`, `/home`, `/var/www`,...) để tìm mọi `Dockerfile`, `Dockerfile.*`, `*.dockerfile`.
     - Tải (Load) nội dung Dockerfile vào Web Editor để kiểm tra và tinh chỉnh trực tiếp trên giao diện web.
     - Tự động gán thư mục dự án làm **Docker Build Context** (`docker build -f <file> <context_dir>`), hỗ trợ đầy đủ các lệnh `COPY . /app` hoặc `COPY requirements.txt .` của dự án thực tế.
     - Nút **Hủy Context** để linh hoạt chuyển đổi giữa dự án thực tế và chế độ thử nghiệm độc lập.
   * **Trình Thực Thi Lệnh Docker Build Trực Tiếp:**
     - Tích hợp sẵn các mẫu Dockerfile phổ biến: 🏔️ *Alpine + cURL*, 🐍 *Python + Pip Packages*, 🟩 *Node.js + NPM Express*, 🐙 *Git Clone Repo*, ✏️ *Custom Dockerfile*.
     - **Tích hợp HTTP Proxy Bridge (Privoxy :8118):** Tự động chuyển đổi SOCKS5 WARP thành HTTP Proxy chuẩn (`http://127.0.0.1:8118`), khắc phục triệt để lỗi `Missing dependencies for SOCKS support` của Python `pip` và lỗi không hỗ trợ SOCKS của Debian/Ubuntu `apt-get`.
     - Chọn nguồn proxy build: **Cloudflare WARP (qua HTTP Bridge)** hoặc **Proxy Dân Cư (Residential)**.
     - Tùy chỉnh Tag Name Image (VD: `warp-build-test:latest` hoặc tự động đặt theo tên thư mục dự án).
     - Tùy chọn build nâng cao: Tự động inject `--build-arg HTTP_PROXY=...`, `--network host`, `--no-cache`, và tự động dọn dẹp image.
     - Hộp hiển thị Live Terminal Console với BuildKit logs chi tiết, mã thoát (Exit Code), thời gian đo kiểm thực tế (giây).
     - Nút **🗑️ Dọn Image** để giải phóng dung lượng đĩa và nút **🧹 Xóa Console**.
6. 🦊 **GitLab CI/CD (`#gitlab`):**
   * Cấu hình sẵn khối biến môi trường cho `.gitlab-ci.yml` (kèm nút Copy).
   * Cấu hình mẫu cho `/etc/gitlab-runner/config.toml` với `network_mode = "host"` (kèm nút Copy).
   * Liên kết trực tiếp tới file mẫu `gitlab-ci.example.yml` và `gitlab-runner.example.toml`.
7. 📋 **Nhật ký & Chẩn đoán (`#logs`):**
   * Xem trực tiếp log dịch vụ `warp-svc` theo thời gian thực trên giao diện terminal.
   * Hỗ trợ checkbox **Tự động làm mới (5s)** và nút làm mới thủ công.

#### 🔐 Tính năng Bảo Mật Toàn Diện:
* **Trang Đăng Nhập Glassmorphism Dark Mode:** Tự động chặn và chuyển hướng mọi truy cập trái phép về `/login`.
* **Mã hóa Mật khẩu SHA-256 + 16-byte Random Salt:** Không lưu plain-text mật khẩu. File cấu hình `.warp_auth.json` và `.residential_proxy.json` được phân quyền an toàn `chmod 600`.
* **Chống Brute-Force Rate Limiting:** Tự động khóa IP 5 phút nếu nhập sai quá 5 lần liên tiếp (Mã lỗi 429).
* **Quản lý Phiên An toàn:** Sử dụng Session Cookie ngẫu nhiên 64-hex với cờ `HttpOnly` (chống XSS) và `SameSite=Lax` (chống CSRF).
* **Tiêu đề HTTP Security:** Tự động gắn `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.
* **Đổi mật khẩu trực tiếp:** Hỗ trợ đổi mật khẩu nhanh qua nút `🔑 Đổi mật khẩu` ngay trên Header Web UI.

---

### 2. 📟 Terminal Interactive Menu (TUI trong SSH)
Nếu không muốn mở cổng web ra ngoài Internet, bạn có thể quản lý trực tiếp bằng giao diện số trong terminal SSH:

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
  Tích hợp    : Docker [Bật (kèm NO_PROXY)] | GitHub [Bật] | GitLab [Bật]
  Nguồn Egress: Cloudflare WARP Anycast (hoặc 🏡 Proxy Dân Cư)
──────────────────────────────────────────────────────────────────────
  [1] Bật kết nối WARP (Connect)
  [2] Tạm ngắt kết nối WARP (Disconnect)
  [3] Đổi cổng SOCKS5 Proxy (Change Port)
  [4] Bật / Tắt Proxy cho Docker Daemon (kèm NO_PROXY)
  [5] 🚀 Quét thư mục & Build Dockerfile qua Proxy
  [6] Bật / Tắt Proxy cho GitHub CLI (github.com)
  [7] Bật / Tắt Proxy cho GitLab CLI (gitlab.com)
  [8] 🏡 Cấu hình & Quản lý Proxy Dân Cư (Residential Proxy)
  [9] 🦊 Xem cấu hình tăng tốc GitLab CI/CD & Runner
  [10] ⚡ Đo kiểm tốc độ mạng quốc tế (Speed Test)
  [11] 🌐 Mở Web Dashboard trên trình duyệt (Port 8888)
  [12] 🔐 Đổi mật khẩu Web Dashboard
  [13] 📋 Xem log dịch vụ (warp-svc logs)
  [0] Thoát
```

---

## 🦊 Tăng tốc GitLab CI/CD Pipeline & GitLab Runner
Áp dụng cho các máy chủ tự host GitLab Runner đặt tại Data Center để khắc phục tình trạng kéo code từ `gitlab.com` hoặc tải package (NPM, PyPI, Maven, Go) bị chậm hoặc timeout:

### A. Cấu hình cho Runner (`/etc/gitlab-runner/config.toml`):
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
*(Xem file mẫu đầy đủ tại [gitlab-runner.example.toml](gitlab-runner.example.toml))*

### B. Cấu hình trong `.gitlab-ci.yml` (Toàn bộ Pipeline):
```yaml
variables:
  ALL_PROXY: "socks5://127.0.0.1:40000"
  HTTP_PROXY: "socks5://127.0.0.1:40000"
  HTTPS_PROXY: "socks5://127.0.0.1:40000"
  NO_PROXY: "localhost,127.0.0.1,docker.io,*.docker.com"
```
*(Xem file pipeline mẫu đầy đủ cho Node, Python, Docker tại [gitlab-ci.example.yml](gitlab-ci.example.yml))*

---

## 📖 Hướng dẫn sử dụng sau khi cài đặt

### 1. Tăng tốc Git CLI (Chỉ cho GitHub / GitLab quốc tế)
```bash
# Chỉ riêng GitHub đi qua WARP SOCKS5:
git config --global http."https://github.com/".proxy "socks5://127.0.0.1:40000"

# Chỉ riêng GitLab đi qua WARP SOCKS5:
git config --global http."https://gitlab.com/".proxy "socks5://127.0.0.1:40000"

# Hủy cấu hình (khi muốn về mặc định):
git config --global --unset http."https://github.com/".proxy
git config --global --unset http."https://gitlab.com/".proxy
```

### 2. Sử dụng với cURL
```bash
curl --socks5-hostname 127.0.0.1:40000 https://cloudflare.com/cdn-cgi/trace
```

### 3. Dùng biến môi trường tạm thời cho phiên Terminal
```bash
export all_proxy="socks5://127.0.0.1:40000"
export ALL_PROXY="socks5://127.0.0.1:40000"

# Tắt proxy:
unset all_proxy ALL_PROXY
```

### 4. Cấu hình cho Docker Daemon (Kèm NO_PROXY)
Tạo file `/etc/systemd/system/docker.service.d/http-proxy.conf`:
```ini
[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:40000"
Environment="HTTPS_PROXY=socks5://127.0.0.1:40000"
Environment="NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.com,production.cloudflare.docker.com"
```
Khởi động lại Docker:
```bash
sudo systemctl daemon-reload && sudo systemctl restart docker
```

---

## 🔐 Bảo Mật & Quản Lý Mật Khẩu Web UI

### Thông tin đăng nhập mặc định:
* **Tài khoản:** `admin`
* **Mật khẩu mặc định:** `datahub@2026`

### 3 cách đổi mật khẩu nhanh:
1. **Trên Web UI:** Đăng nhập và nhấp vào nút **`🔑 Đổi mật khẩu`** trên góc phải màn hình.
2. **Qua Menu Terminal:** Chạy `sudo bash menu.sh` và chọn mục **`[10] 🔐 Đổi mật khẩu Web Dashboard`**.
3. **Bằng câu lệnh CLI:**
   ```bash
   sudo bash install.sh --set-password "MatKhauMoiCuaBan@2026"
   ```

---

## 📌 Các lệnh quản lý tiện ích

```bash
# Mở menu Terminal TUI
sudo bash install.sh --menu

# Chạy Web Dashboard trên cổng 8888
sudo bash install.sh --dashboard

# Cài đặt Web Dashboard chạy nền cùng hệ thống (systemd)
sudo bash install.sh --dashboard-service

# Đổi mật khẩu đăng nhập Web Dashboard
sudo bash install.sh --set-password "MatKhauMoi@2026"

# Kiểm tra trạng thái kết nối WARP
sudo bash install.sh --status

# Gỡ bỏ cài đặt hoàn toàn khỏi hệ thống
sudo bash install.sh --uninstall

# Xem trợ giúp
sudo bash install.sh --help
```

---

## 📄 Tài liệu chi tiết
Chi tiết về số liệu đo kiểm thực tế (Hetzner Đức vs Docker Hub), nguyên lý định tuyến và cấu hình Privoxy nâng cao: xem tại **[CF_Warp_guideline.md](CF_Warp_guideline.md)**.
