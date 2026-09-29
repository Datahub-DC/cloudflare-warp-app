#!/usr/bin/env bash
# ==============================================================================
# Script Name : menu.sh
# Description : Terminal Interactive UI (TUI) cho Cloudflare WARP SOCKS5
# ==============================================================================

# Màu sắc
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Kiểm tra quyền root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[LỖI] Menu cần được chạy với quyền root (hoặc sudo).${NC}"
    echo -e "Vui lòng chạy lại: ${CYAN}sudo bash $0${NC}"
    exit 1
fi

run_warp() {
    warp-cli --accept-tos "$@" 2>/dev/null || warp-cli "$@" 2>/dev/null
}

get_current_port() {
    local settings
    settings=$(run_warp settings list)
    local port
    port=$(echo "$settings" | grep -iE "WarpProxy on port|port:" | grep -oE "[0-9]+" | head -n 1)
    echo "${port:-40000}"
}

clear_screen() {
    clear
}

header() {
    clear_screen
    local port
    port=$(get_current_port)
    local status_raw
    status_raw=$(run_warp status)
    local is_conn=false
    if echo "$status_raw" | grep -q "Connected"; then
        is_conn=true
    fi

    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}${YELLOW}CLOUDFLARE WARP CONTROL CENTER${NC} - ${BOLD}BẢNG ĐIỀU KHIỂN TERMINAL (TUI)${NC}      ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"

    if [ "$is_conn" = true ]; then
        echo -e "  Trạng thái  : ${GREEN}${BOLD}● ĐANG KẾT NỐI (Connected)${NC}"
    else
        echo -e "  Trạng thái  : ${RED}${BOLD}○ ĐÃ NGẮT KẾT NỐI (Disconnected)${NC}"
    fi

    echo -e "  Chế độ      : ${MAGENTA}SOCKS5 Proxy (An toàn tuyệt đối cho SSH)${NC}"
    echo -e "  Cổng Proxy  : ${YELLOW}127.0.0.1:${port}${NC}"

    # Kiểm tra trạng thái Docker & Git
    local docker_st="${RED}Tắt${NC}"
    if [ -f /etc/systemd/system/docker.service.d/http-proxy.conf ]; then
        docker_st="${GREEN}Bật (kèm NO_PROXY Docker Hub)${NC}"
    fi

    local git_st="${RED}Tắt${NC}"
    if git config --global http."https://github.com/".proxy 2>/dev/null | grep -q "socks5"; then
        git_st="${GREEN}Bật (github.com)${NC}"
    fi

    echo -e "  Tích hợp    : Docker [${docker_st}] | Git [${git_st}]"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
}

pause() {
    echo ""
    read -rp "Nhấn [Enter] để quay lại menu..." _
}

speed_test() {
    local port
    port=$(get_current_port)
    echo -e "${BLUE}==>${NC} ${BOLD}Đang kiểm tra tốc độ tải file từ Hetzner (Đức) qua WARP...${NC}"
    echo -e "    Cổng proxy: 127.0.0.1:${port}"
    curl --socks5-hostname 127.0.0.1:"$port" -o /dev/null -w "\n  Tốc độ tải qua WARP : %{speed_download} bytes/sec (~%{speed_download} / 1048576 MB/s)\n  Thời gian kết nối   : %{time_connect}s\n  Tổng thời gian      : %{time_total}s\n" https://fsn1-speed.hetzner.com/100MB.bin
}

toggle_docker() {
    local port
    port=$(get_current_port)
    local conf_file="/etc/systemd/system/docker.service.d/http-proxy.conf"

    if [ -f "$conf_file" ]; then
        echo -e "${YELLOW}Đang tắt proxy cho Docker Daemon...${NC}"
        rm -f "$conf_file"
        systemctl daemon-reload && systemctl restart docker
        echo -e "${GREEN}Đã tắt proxy Docker thành công. Docker sẽ kéo trực tiếp.${NC}"
    else
        echo -e "${YELLOW}Đang bật proxy cho Docker Daemon (kèm NO_PROXY Docker Hub)...${NC}"
        mkdir -p /etc/systemd/system/docker.service.d
        cat <<EOF > "$conf_file"
[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:${port}"
Environment="HTTPS_PROXY=socks5://127.0.0.1:${port}"
Environment="NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23"
EOF
        systemctl daemon-reload && systemctl restart docker
        echo -e "${GREEN}Đã bật proxy Docker thành công!${NC}"
    fi
}

toggle_git() {
    local port
    port=$(get_current_port)
    if git config --global http."https://github.com/".proxy 2>/dev/null | grep -q "socks5"; then
        echo -e "${YELLOW}Đang hủy cấu hình proxy cho GitHub...${NC}"
        git config --global --unset http."https://github.com/".proxy
        echo -e "${GREEN}Đã hủy proxy GitHub. Git sẽ kết nối trực tiếp.${NC}"
    else
        echo -e "${YELLOW}Đang cấu hình proxy WARP SOCKS5 cho riêng GitHub...${NC}"
        git config --global http."https://github.com/".proxy "socks5://127.0.0.1:${port}"
        echo -e "${GREEN}Đã cấu hình proxy GitHub thành công!${NC}"
    fi
}

change_port() {
    local old_port
    old_port=$(get_current_port)
    echo -e "Cổng hiện tại: ${YELLOW}${old_port}${NC}"
    read -rp "Nhập cổng SOCKS5 mới (1024 - 65535) [mặc định: 40000]: " new_port
    new_port=${new_port:-40000}

    if [[ "$new_port" =~ ^[0-9]+$ ]] && [ "$new_port" -ge 1024 ] && [ "$new_port" -le 65535 ]; then
        echo -e "Đang đổi sang cổng ${new_port}..."
        run_warp proxy port "$new_port" || run_warp set-proxy-port "$new_port"
        echo -e "${GREEN}Đã đổi cổng thành công sang: ${new_port}${NC}"
    else
        echo -e "${RED}Cổng không hợp lệ! Vui lòng nhập số từ 1024 đến 65535.${NC}"
    fi
}

start_web_dashboard() {
    local script_dir
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    echo -e "${BLUE}==>${NC} ${BOLD}Khởi động Web Dashboard trên cổng 8888...${NC}"

    # Kiểm tra xem web_dashboard đang chạy chưa
    if pgrep -f "web_dashboard.py" >/dev/null; then
        echo -e "${GREEN}Web Dashboard đang hoạt động sẵn tại:${NC}"
    else
        nohup python3 "${script_dir}/web_dashboard.py" >/dev/null 2>&1 &
        sleep 1
        echo -e "${GREEN}Đã khởi động Web Dashboard thành công!${NC}"
    fi

    local ip_public
    ip_public=$(curl -m 3 -s ifconfig.me || hostname -I | awk '{print $1}')
    echo -e "  Truy cập trình duyệt tại: ${CYAN}http://${ip_public}:8888${NC}"
    echo -e "  Hoặc truy cập nội bộ    : ${CYAN}http://127.0.0.1:8888${NC}"
}

# Vòng lặp Menu chính
while true; do
    header
    echo -e "  ${BOLD}[1]${NC} ${GREEN}Bật kết nối WARP${NC} (Connect)"
    echo -e "  ${BOLD}[2]${NC} ${RED}Tạm ngắt kết nối WARP${NC} (Disconnect)"
    echo -e "  ${BOLD}[3]${NC} ${YELLOW}Đổi cổng SOCKS5 Proxy${NC} (Change Port)"
    echo -e "  ${BOLD}[4]${NC} ${CYAN}Bật / Tắt Proxy cho Docker Daemon${NC} (kèm NO_PROXY)"
    echo -e "  ${BOLD}[5]${NC} ${BLUE}Bật / Tắt Proxy cho GitHub CLI${NC}"
    echo -e "  ${BOLD}[6]${NC} ⚡ ${BOLD}Đo kiểm tốc độ mạng quốc tế${NC} (Speed Test)"
    echo -e "  ${BOLD}[7]${NC} 🌐 ${MAGENTA}Mở Web Dashboard trên trình duyệt${NC} (Port 8888)"
    echo -e "  ${BOLD}[8]${NC} 📋 Xem log dịch vụ (warp-svc logs)"
    echo -e "  ${BOLD}[0]${NC} Thoát"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
    read -rp "Chọn thao tác [0-8]: " choice

    case "$choice" in
        1)
            echo -e "${YELLOW}Đang kích hoạt kết nối WARP...${NC}"
            run_warp connect
            sleep 2
            run_warp status
            pause
            ;;
        2)
            echo -e "${YELLOW}Đang ngắt kết nối WARP...${NC}"
            run_warp disconnect
            sleep 1
            run_warp status
            pause
            ;;
        3)
            change_port
            pause
            ;;
        4)
            toggle_docker
            pause
            ;;
        5)
            toggle_git
            pause
            ;;
        6)
            speed_test
            pause
            ;;
        7)
            start_web_dashboard
            pause
            ;;
        8)
            journalctl -u warp-svc -n 30 --no-pager
            pause
            ;;
        0)
            clear_screen
            echo "Tạm biệt!"
            exit 0
            ;;
        *)
            echo -e "${RED}Lựa chọn không hợp lệ!${NC}"
            sleep 1
            ;;
    esac
done
