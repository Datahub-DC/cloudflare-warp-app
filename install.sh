#!/usr/bin/env bash
# ==============================================================================
# Script Name   : install.sh
# Description   : Tự động cài đặt và cấu hình Cloudflare WARP an toàn (SOCKS5 Proxy)
# Supported OS  : Ubuntu 20.04 (Focal), 22.04 (Jammy), 24.04 (Noble), 26.04 (Resolute)
# Author        : DataHub DC Support Team
# Email         : jason.nguyen@hextech.vn
# Safety Rule   : Bắt buộc dùng Proxy Mode (Port 40000), không can thiệp bảng định tuyến,
#                 đảm bảo kết nối SSH IP Public không bao giờ bị gián đoạn.
# ==============================================================================

set -e

# Màu sắc thông báo
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PROXY_PORT=40000

# Kiểm tra quyền root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}[LỖI] Script cần được chạy với quyền root (hoặc sudo).${NC}"
        echo -e "Vui lòng chạy lại với: ${CYAN}sudo bash $0${NC}"
        exit 1
    fi
}

# Phát hiện hệ điều hành và phiên bản
detect_os() {
    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra hệ điều hành...${NC}"
    if [ ! -f /etc/os-release ]; then
        echo -e "${RED}[LỖI] Không tìm thấy /etc/os-release. Script chỉ hỗ trợ Ubuntu / Debian.${NC}"
        exit 1
    fi

    . /etc/os-release
    OS_NAME="${NAME:-Linux}"
    OS_ID="${ID:-unknown}"
    OS_VERSION="${VERSION_ID:-}"
    CODENAME="${VERSION_CODENAME:-$UBUNTU_CODENAME}"

    if [ -z "$CODENAME" ] && command -v lsb_release >/dev/null 2>&1; then
        CODENAME=$(lsb_release -cs 2>/dev/null || echo "")
    fi

    echo -e "  - Hệ điều hành: ${CYAN}${OS_NAME}${NC} (Phiên bản: ${CYAN}${OS_VERSION:-N/A}${NC}, Codename: ${CYAN}${CODENAME}${NC})"

    # Kiểm tra tính tương thích với Cloudflare Repository
    case "$CODENAME" in
        focal)
            TARGET_CODENAME="focal"    # Ubuntu 20.04 LTS
            ;;
        jammy)
            TARGET_CODENAME="jammy"    # Ubuntu 22.04 LTS
            ;;
        noble)
            TARGET_CODENAME="noble"    # Ubuntu 24.04 LTS
            ;;
        resolute)
            TARGET_CODENAME="resolute" # Ubuntu 26.04 LTS
            ;;
        *)
            # Nếu codename khác, kiểm tra xem Cloudflare có repo tương ứng không
            echo -e "${YELLOW}  [!] Phiên bản '$CODENAME' nằm ngoài danh mục mặc định. Đang kiểm tra repo Cloudflare...${NC}"
            if curl -fsSL -o /dev/null "https://pkg.cloudflareclient.com/dists/${CODENAME}/Release" 2>/dev/null; then
                TARGET_CODENAME="$CODENAME"
                echo -e "  - Tìm thấy repo chính thức cho: ${GREEN}${TARGET_CODENAME}${NC}"
            else
                echo -e "${YELLOW}  [!] Chưa có repo cho '$CODENAME'. Tự động fallback về Ubuntu 24.04 LTS (noble)...${NC}"
                TARGET_CODENAME="noble"
            fi
            ;;
    esac
    echo -e "  - Kho gói áp dụng: ${GREEN}https://pkg.cloudflareclient.com/ (${TARGET_CODENAME})${NC}"
}

# Khắc phục sự cố chặn Port 80 (HTTP) tại môi trường Data Center
fix_firewall_and_apt() {
    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra kết nối kho lưu trữ APT & Tường lửa Data Center...${NC}"
    
    # Kiểm tra xem cổng 80 có bị chặn outbound không
    HTTP_BLOCKED=false
    if ! curl -m 4 -s -o /dev/null http://archive.ubuntu.com/ 2>/dev/null; then
        HTTP_BLOCKED=true
    fi

    if [ "$HTTP_BLOCKED" = true ]; then
        echo -e "${YELLOW}  [!] Phát hiện Data Center chặn kết nối HTTP (Port 80) ra ngoài.${NC}"
        echo -e "      Đang tự động chuyển đổi cấu hình APT sang HTTPS để tránh lỗi tải gói..."
        
        # Định dạng deb822 mới (Ubuntu 24.04+)
        if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
            sed -i 's|http://de.archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
            sed -i 's|http://archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
            sed -i 's|http://security.ubuntu.com/ubuntu/|https://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
            sed -i 's|http://vn.archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list.d/ubuntu.sources
        fi

        # Định dạng truyền thống (Ubuntu 20.04, 22.04)
        if [ -f /etc/apt/sources.list ]; then
            sed -i 's|http://de.archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list
            sed -i 's|http://archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list
            sed -i 's|http://security.ubuntu.com/ubuntu/|https://security.ubuntu.com/ubuntu/|g' /etc/apt/sources.list
            sed -i 's|http://vn.archive.ubuntu.com/ubuntu/|https://archive.ubuntu.com/ubuntu/|g' /etc/apt/sources.list
        fi
        echo -e "  - Đã chuyển mirror APT sang ${GREEN}HTTPS (https://archive.ubuntu.com/)${NC} thành công."
    else
        echo -e "  - Kết nối APT bình thường."
    fi
}

# Cài đặt cloudflare-warp từ kho chính thức
install_warp_package() {
    echo -e "${BLUE}==>${NC} ${BOLD}Cài đặt các gói phụ thuộc cơ bản (curl, gpg, ca-certificates)...${NC}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y -qq
    apt-get install -y -qq curl gpg lsb-release ca-certificates

    echo -e "${BLUE}==>${NC} ${BOLD}Cấu hình GPG key và Repository của Cloudflare...${NC}"
    mkdir -p /usr/share/keyrings
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ ${TARGET_CODENAME} main" | tee /etc/apt/sources.list.d/cloudflare-client.list >/dev/null

    echo -e "${BLUE}==>${NC} ${BOLD}Cài đặt package cloudflare-warp...${NC}"
    apt-get update -y -qq
    apt-get install -y -qq cloudflare-warp
    echo -e "  - Cài đặt package ${GREEN}cloudflare-warp${NC} thành công!"
}

# Hàm thực thi lệnh warp-cli hỗ trợ cả bản mới và bản cũ
run_warp_cli() {
    warp-cli --accept-tos "$@" 2>/dev/null || warp-cli "$@" 2>/dev/null
}

# Cấu hình chế độ SOCKS5 Proxy an toàn tuyệt đối
configure_warp_proxy() {
    echo -e "${BLUE}==>${NC} ${BOLD}Khởi động và kích hoạt dịch vụ warp-svc...${NC}"
    systemctl enable --now warp-svc >/dev/null 2>&1
    sleep 2

    echo -e "${BLUE}==>${NC} ${BOLD}Đăng ký máy trạm với Cloudflare...${NC}"
    run_warp_cli registration new || run_warp_cli register || true

    echo -e "${BLUE}==>${NC} ${BOLD}Chuyển sang chế độ PROXY MODE (SOCKS5 - Port ${PROXY_PORT})...${NC}"
    # Đặt chế độ proxy (hỗ trợ cả cú pháp mới & cũ)
    run_warp_cli mode proxy || run_warp_cli set-mode proxy || true
    run_warp_cli proxy port "$PROXY_PORT" || run_warp_cli set-proxy-port "$PROXY_PORT" || true

    echo -e "${BLUE}==>${NC} ${BOLD}Kích hoạt kết nối WARP...${NC}"
    run_warp_cli connect || true
    sleep 3

    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra trạng thái kết nối...${NC}"
    run_warp_cli status || true
}

# Kiểm tra kết quả qua cURL SOCKS5
verify_connection() {
    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra định tuyến qua SOCKS5 Proxy (127.0.0.1:${PROXY_PORT})...${NC}"
    local RETRIES=5
    local CONNECTED=false
    local TRACE_OUTPUT=""

    for i in $(seq 1 $RETRIES); do
        TRACE_OUTPUT=$(curl -m 8 --socks5-hostname 127.0.0.1:${PROXY_PORT} -s https://cloudflare.com/cdn-cgi/trace 2>/dev/null || echo "")
        if echo "$TRACE_OUTPUT" | grep -q "warp=on"; then
            CONNECTED=true
            break
        fi
        sleep 2
    done

    echo ""
    if [ "$CONNECTED" = true ]; then
        local COLO=$(echo "$TRACE_OUTPUT" | grep "^colo=" | cut -d= -f2)
        local IP=$(echo "$TRACE_OUTPUT" | grep "^ip=" | cut -d= -f2)

        echo -e "${GREEN}========================================================================${NC}"
        echo -e "${GREEN}${BOLD}🎉 CÀI ĐẶT & KÍCH HOẠT CLOUDFLARE WARP THÀNH CÔNG!${NC}"
        echo -e "${GREEN}========================================================================${NC}"
        echo -e "  ${BOLD}Chế độ hoạt động :${NC} ${CYAN}SOCKS5 Proxy (Tuyệt đối an toàn cho SSH)${NC}"
        echo -e "  ${BOLD}Cổng Proxy local :${NC} ${YELLOW}127.0.0.1:${PROXY_PORT}${NC}"
        echo -e "  ${BOLD}Trạng thái WARP  :${NC} ${GREEN}warp=on${NC}"
        echo -e "  ${BOLD}Trạm Anycast PoP :${NC} ${GREEN}${COLO}${NC}"
        echo -e "  ${BOLD}Egress IP        :${NC} ${CYAN}${IP}${NC}"
        echo -e "${GREEN}========================================================================${NC}"
        echo ""
        echo -e "${BOLD}HƯỚNG DẪN SỬ DỤNG NHANH:${NC}"
        echo -e "  1. ${BOLD}Sử dụng với cURL:${NC}"
        echo -e "     ${CYAN}curl --socks5-hostname 127.0.0.1:${PROXY_PORT} https://example.com${NC}"
        echo ""
        echo -e "  2. ${BOLD}Cấu hình tăng tốc Git (chỉ riêng GitHub):${NC}"
        echo -e "     ${CYAN}git config --global http.\"https://github.com/\".proxy \"socks5://127.0.0.1:${PROXY_PORT}\"${NC}"
        echo ""
        echo -e "  3. ${BOLD}Bật proxy tạm thời cho toàn bộ phiên Terminal / CI-CD:${NC}"
        echo -e "     ${CYAN}export all_proxy=\"socks5://127.0.0.1:${PROXY_PORT}\"${NC}"
        echo -e "     ${CYAN}export ALL_PROXY=\"socks5://127.0.0.1:${PROXY_PORT}\"${NC}"
        echo ""
        echo -e "  4. ${BOLD}Mở Bảng Điều Khiển Giao Diện Trực Quan (UI):${NC}"
        echo -e "     - ${GREEN}Terminal Interactive UI (TUI):${NC} ${CYAN}sudo bash menu.sh${NC}"
        echo -e "     - ${GREEN}Web Dashboard (Trình duyệt):${NC}    ${CYAN}sudo python3 web_dashboard.py${NC} (hoặc chạy ${CYAN}sudo bash install.sh --dashboard-service${NC})"
        echo ""
        echo -e "  5. ${BOLD}Xem tài liệu chi tiết (Docker NO_PROXY, Privoxy):${NC}"
        echo -e "     Đọc tài liệu: ${CYAN}CF_Warp_guideline.md${NC}"
        echo ""
    else
        echo -e "${RED}========================================================================${NC}"
        echo -e "${RED}[CẢNH BÁO] Chưa thể xác thực kết nối qua 127.0.0.1:${PROXY_PORT}.${NC}"
        echo -e "Vui lòng kiểm tra lại dịch vụ bằng lệnh:"
        echo -e "  ${CYAN}warp-cli --accept-tos status${NC}"
        echo -e "  ${CYAN}sudo journalctl -u warp-svc -n 50 --no-pager${NC}"
        echo -e "${RED}========================================================================${NC}"
    fi
}

# Cài đặt Web Dashboard làm systemd service
setup_dashboard_service() {
    local script_dir
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    echo -e "${BLUE}==>${NC} ${BOLD}Cài đặt Web Dashboard thành dịch vụ hệ thống (systemd)...${NC}"
    cp "${script_dir}/warp-dashboard.service" /etc/systemd/system/warp-dashboard.service
    systemctl daemon-reload
    systemctl enable --now warp-dashboard.service
    echo -e "${GREEN}Dịch vụ warp-dashboard đã được kích hoạt và tự động khởi động cùng hệ thống!${NC}"
    local ip_public
    ip_public=$(curl -m 3 -s ifconfig.me || hostname -I | awk '{print $1}')
    echo -e "  Truy cập giao diện tại: ${CYAN}http://${ip_public}:8888${NC}"
    exit 0
}

# Gỡ cài đặt hoàn toàn
uninstall_warp() {
    echo -e "${YELLOW}==>${NC} ${BOLD}Đang tiến hành gỡ bỏ Cloudflare WARP...${NC}"
    systemctl stop warp-dashboard >/dev/null 2>&1 || true
    systemctl disable warp-dashboard >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/warp-dashboard.service

    run_warp_cli disconnect || true
    systemctl stop warp-svc >/dev/null 2>&1 || true
    systemctl disable warp-svc >/dev/null 2>&1 || true
    
    export DEBIAN_FRONTEND=noninteractive
    apt-get remove --purge -y cloudflare-warp >/dev/null 2>&1 || true
    rm -f /etc/apt/sources.list.d/cloudflare-client.list
    rm -f /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    apt-get update -y -qq >/dev/null 2>&1 || true

    echo -e "${GREEN}Đã gỡ bỏ Cloudflare WARP sạch sẽ khỏi hệ thống.${NC}"
    exit 0
}

# Kiểm tra trạng thái nhanh
show_status() {
    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra trạng thái Cloudflare WARP...${NC}"
    run_warp_cli status || true
    echo ""
    echo -e "${BLUE}==>${NC} ${BOLD}Kiểm tra đường truyền qua SOCKS5:${NC}"
    curl -m 5 --socks5-hostname 127.0.0.1:${PROXY_PORT} -s https://cloudflare.com/cdn-cgi/trace 2>/dev/null || echo "Không kết nối được SOCKS5 proxy."
    exit 0
}

# Hiển thị trợ giúp
show_help() {
    echo "Sử dụng: sudo bash $0 [TÙY CHỌN]"
    echo ""
    echo "Tùy chọn:"
    echo "  (không truyền tham số) : Cài đặt và cấu hình WARP Proxy tự động"
    echo "  --menu                 : Mở giao diện tương tác dòng lệnh (Terminal UI)"
    echo "  --dashboard            : Chạy Web Dashboard trên cổng 8888"
    echo "  --dashboard-service    : Cài đặt Web Dashboard làm systemd service (tự bật khi khởi động)"
    echo "  --status               : Kiểm tra trạng thái kết nối WARP hiện tại"
    echo "  --uninstall            : Gỡ cài đặt Cloudflare WARP sạch sẽ"
    echo "  --help, -h             : Hiển thị hướng dẫn này"
    exit 0
}

# Điểm vào chính của script
main() {
    local script_dir
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

    case "$1" in
        --menu)
            check_root
            bash "${script_dir}/menu.sh"
            ;;
        --dashboard)
            check_root
            python3 "${script_dir}/web_dashboard.py"
            ;;
        --dashboard-service)
            check_root
            setup_dashboard_service
            ;;
        --uninstall)
            check_root
            uninstall_warp
            ;;
        --status)
            show_status
            ;;
        --help|-h)
            show_help
            ;;
        "")
            check_root
            echo -e "${CYAN}========================================================================${NC}"
            echo -e "${CYAN}${BOLD}   CLOUDFLARE WARP INSTALLER (UBUNTU 20.04 / 22.04 / 24.04 / 26.04)     ${NC}"
            echo -e "${CYAN}========================================================================${NC}"
            detect_os
            fix_firewall_and_apt
            install_warp_package
            configure_warp_proxy
            verify_connection
            ;;
        *)
            echo -e "${RED}[LỖI] Tùy chọn không hợp lệ: $1${NC}"
            show_help
            ;;
    esac
}

main "$@"
