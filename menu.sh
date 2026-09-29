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
        docker_st="${GREEN}Bật (kèm NO_PROXY)${NC}"
    fi

    local github_st="${RED}Tắt${NC}"
    if git config --global http."https://github.com/".proxy 2>/dev/null | grep -q "socks5"; then
        github_st="${GREEN}Bật${NC}"
    fi

    local gitlab_st="${RED}Tắt${NC}"
    if git config --global http."https://gitlab.com/".proxy 2>/dev/null | grep -q "socks5"; then
        gitlab_st="${GREEN}Bật${NC}"
    fi

    echo -e "  Tích hợp    : Docker [${docker_st}] | GitHub [${github_st}] | GitLab [${gitlab_st}]"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
}

pause() {
    echo ""
    read -rp "Nhấn [Enter] để quay lại menu..." _
}

speed_test_dc() {
    local name="$1"
    local flag="$2"
    local url="$3"
    local port="$4"

    echo -ne "  Đang đo tới: ${flag} ${BOLD}${name}${NC}... "
    local res
    res=$(curl -m 8 --socks5-hostname 127.0.0.1:"$port" -r 0-3145728 -s -w "%{speed_download},%{time_starttransfer},%{time_total}" -o /dev/null "$url")
    
    local speed_raw ttfb total_t speed_mb latency_ms
    speed_raw=$(echo "$res" | cut -d, -f1)
    ttfb=$(echo "$res" | cut -d, -f2)
    total_t=$(echo "$res" | cut -d, -f3)

    if [ -n "$speed_raw" ] && [ "$speed_raw" != "0" ]; then
        speed_mb=$(awk -v s="$speed_raw" 'BEGIN { printf "%.2f", s / 1048576 }')
        latency_ms=$(awk -v t="$ttfb" 'BEGIN { printf "%d", t * 1000 }')
        echo -e "${GREEN}Xong!${NC}"
        echo -e "  ➜ Tốc độ: ${CYAN}${BOLD}${speed_mb} MB/s${NC} | Độ trễ: ${YELLOW}${latency_ms} ms${NC} | Thời gian: ${total_t}s"
    else
        echo -e "${RED}Thất bại / Timeout${NC}"
    fi
}

speed_test_menu() {
    local port
    port=$(get_current_port)
    while true; do
        clear_screen
        echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║${NC}   ${BOLD}${YELLOW}ĐO KIỂM TỐC ĐỘ MẠNG ĐA QUỐC GIA QUA WARP SOCKS5${NC}                  ${CYAN}║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
        echo -e "  Cổng Proxy: ${YELLOW}127.0.0.1:${port}${NC}"
        echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
        echo -e "  ${BOLD}[1]${NC} 🇸🇬 Singapore (Hetzner DC)"
        echo -e "  ${BOLD}[2]${NC} 🇯🇵 Nhật Bản (Tokyo, Linode DC)"
        echo -e "  ${BOLD}[3]${NC} 🇩🇪 Đức (Falkenstein, Hetzner DC)"
        echo -e "  ${BOLD}[4]${NC} 🇩🇪 Đức (Nuremberg, Hetzner DC)"
        echo -e "  ${BOLD}[5]${NC} 🇺🇸 Mỹ - Bờ Đông (Ashburn Virginia, Hetzner)"
        echo -e "  ${BOLD}[6]${NC} 🇺🇸 Mỹ - Bờ Tây (Hillsboro Oregon, Hetzner)"
        echo -e "  ${BOLD}[7]${NC} 🇬🇧 Anh Quốc (London, Linode DC)"
        echo -e "  ${BOLD}[8]${NC} 🇫🇮 Phần Lan (Helsinki, Hetzner DC)"
        echo -e "  ${BOLD}[9]${NC} 🚀 ${BOLD}Đo kiểm TOÀN BỘ các Data Center (Benchmark All)${NC}"
        echo -e "  ${BOLD}[0]${NC} Quay lại Menu chính"
        echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
        read -rp "Chọn Data Center để đo kiểm [0-9]: " dc_choice

        case "$dc_choice" in
            1)
                echo ""
                speed_test_dc "Singapore (Hetzner)" "🇸🇬" "https://sin-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            2)
                echo ""
                speed_test_dc "Nhật Bản (Tokyo, Linode)" "🇯🇵" "http://speedtest.tokyo2.linode.com/100MB-tokyo2.bin" "$port"
                pause
                ;;
            3)
                echo ""
                speed_test_dc "Đức (Falkenstein, Hetzner)" "🇩🇪" "https://fsn1-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            4)
                echo ""
                speed_test_dc "Đức (Nuremberg, Hetzner)" "🇩🇪" "https://nbg1-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            5)
                echo ""
                speed_test_dc "Mỹ - Bờ Đông (Ashburn)" "🇺🇸" "https://ash-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            6)
                echo ""
                speed_test_dc "Mỹ - Bờ Tây (Hillsboro)" "🇺🇸" "https://hil-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            7)
                echo ""
                speed_test_dc "Anh Quốc (London, Linode)" "🇬🇧" "http://speedtest.london.linode.com/100MB-london.bin" "$port"
                pause
                ;;
            8)
                echo ""
                speed_test_dc "Phần Lan (Helsinki, Hetzner)" "🇫🇮" "https://hel1-speed.hetzner.com/100MB.bin" "$port"
                pause
                ;;
            9)
                echo ""
                echo -e "${BLUE}==>${NC} ${BOLD}Bắt đầu đo kiểm toàn bộ 8 Data Center quốc tế...${NC}"
                echo ""
                speed_test_dc "Singapore (Hetzner)" "🇸🇬" "https://sin-speed.hetzner.com/100MB.bin" "$port"
                speed_test_dc "Nhật Bản (Tokyo, Linode)" "🇯🇵" "http://speedtest.tokyo2.linode.com/100MB-tokyo2.bin" "$port"
                speed_test_dc "Đức (Falkenstein, Hetzner)" "🇩🇪" "https://fsn1-speed.hetzner.com/100MB.bin" "$port"
                speed_test_dc "Đức (Nuremberg, Hetzner)" "🇩🇪" "https://nbg1-speed.hetzner.com/100MB.bin" "$port"
                speed_test_dc "Mỹ - Bờ Đông (Ashburn)" "🇺🇸" "https://ash-speed.hetzner.com/100MB.bin" "$port"
                speed_test_dc "Mỹ - Bờ Tây (Hillsboro)" "🇺🇸" "https://hil-speed.hetzner.com/100MB.bin" "$port"
                speed_test_dc "Anh Quốc (London, Linode)" "🇬🇧" "http://speedtest.london.linode.com/100MB-london.bin" "$port"
                speed_test_dc "Phần Lan (Helsinki, Hetzner)" "🇫🇮" "https://hel1-speed.hetzner.com/100MB.bin" "$port"
                echo ""
                echo -e "${GREEN}Đã hoàn thành đo kiểm toàn bộ!${NC}"
                pause
                ;;
            0)
                break
                ;;
            *)
                echo -e "${RED}Lựa chọn không hợp lệ!${NC}"
                sleep 1
                ;;
        esac
    done
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

toggle_gitlab() {
    local port
    port=$(get_current_port)
    if git config --global http."https://gitlab.com/".proxy 2>/dev/null | grep -q "socks5"; then
        echo -e "${YELLOW}Đang hủy cấu hình proxy cho GitLab...${NC}"
        git config --global --unset http."https://gitlab.com/".proxy
        echo -e "${GREEN}Đã hủy proxy GitLab. Git sẽ kết nối trực tiếp.${NC}"
    else
        echo -e "${YELLOW}Đang cấu hình proxy WARP SOCKS5 cho riêng GitLab (gitlab.com)...${NC}"
        git config --global http."https://gitlab.com/".proxy "socks5://127.0.0.1:${port}"
        echo -e "${GREEN}Đã cấu hình proxy GitLab thành công!${NC}"
    fi
}

show_gitlab_cicd_guide() {
    clear_screen
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}${YELLOW}HƯỚNG DẪN TĂNG TỐC GITLAB CI/CD QUA CLOUDFLARE WARP${NC}             ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BOLD}1. DÀNH CHO FILE .gitlab-ci.yml (Toàn bộ Pipeline):${NC}"
    echo -e "Thêm khối variables vào đầu file .gitlab-ci.yml:"
    echo -e "${YELLOW}------------------------------------------------------------${NC}"
    echo -e "${CYAN}variables:${NC}"
    echo -e "  ${CYAN}ALL_PROXY: \"socks5://127.0.0.1:40000\"${NC}"
    echo -e "  ${CYAN}HTTP_PROXY: \"socks5://127.0.0.1:40000\"${NC}"
    echo -e "  ${CYAN}HTTPS_PROXY: \"socks5://127.0.0.1:40000\"${NC}"
    echo -e "  ${CYAN}NO_PROXY: \"localhost,127.0.0.1,docker.io,*.docker.com\"${NC}"
    echo -e "${YELLOW}------------------------------------------------------------${NC}"
    echo ""
    echo -e "${BOLD}2. DÀNH CHO GITLAB RUNNER (/etc/gitlab-runner/config.toml):${NC}"
    echo -e "Nếu dùng Docker Executor, bắt buộc thêm ${GREEN}network_mode = \"host\"${NC}:"
    echo -e "${YELLOW}------------------------------------------------------------${NC}"
    echo -e "${CYAN}[[runners]]${NC}"
    echo -e "  ${CYAN}executor = \"docker\"${NC}"
    echo -e "  ${CYAN}environment = [\"ALL_PROXY=socks5://127.0.0.1:40000\"]${NC}"
    echo -e "  ${CYAN}[runners.docker]${NC}"
    echo -e "    ${GREEN}network_mode = \"host\"${NC}"
    echo -e "${YELLOW}------------------------------------------------------------${NC}"
    echo ""
    echo -e "File mẫu chi tiết: ${GREEN}gitlab-ci.example.yml${NC} & ${GREEN}gitlab-runner.example.toml${NC}"
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
    echo -e "  ${BOLD}[5]${NC} ${BLUE}Bật / Tắt Proxy cho GitHub CLI${NC} (github.com)"
    echo -e "  ${BOLD}[6]${NC} ${MAGENTA}Bật / Tắt Proxy cho GitLab CLI${NC} (gitlab.com)"
    echo -e "  ${BOLD}[7]${NC} 🦊 ${BOLD}Xem cấu hình tăng tốc GitLab CI/CD & Runner${NC}"
    echo -e "  ${BOLD}[8]${NC} ⚡ ${BOLD}Đo kiểm tốc độ mạng quốc tế${NC} (Speed Test)"
    echo -e "  ${BOLD}[9]${NC} 🌐 ${CYAN}Mở Web Dashboard trên trình duyệt${NC} (Port 8888)"
    echo -e "  ${BOLD}[10]${NC} 📋 Xem log dịch vụ (warp-svc logs)"
    echo -e "  ${BOLD}[0]${NC} Thoát"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
    read -rp "Chọn thao tác [0-10]: " choice

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
            toggle_gitlab
            pause
            ;;
        7)
            show_gitlab_cicd_guide
            pause
            ;;
        8)
            speed_test_menu
            ;;
        9)
            start_web_dashboard
            pause
            ;;
        10)
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
