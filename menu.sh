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

    local egress_st="${BLUE}Cloudflare WARP Anycast${NC}"
    if [ -f /root/linux-cloudflare-warp/.residential_proxy.json ]; then
        local is_res
        is_res=$(python3 -c "import json; d=json.load(open('/root/linux-cloudflare-warp/.residential_proxy.json')); print('1' if d.get('active_source')=='residential' or d.get('enabled') else '0')" 2>/dev/null)
        if [ "$is_res" = "1" ]; then
            local res_host
            res_host=$(python3 -c "import json; d=json.load(open('/root/linux-cloudflare-warp/.residential_proxy.json')); print(f\"{d.get('proto','socks5')}://{d.get('host','')}:{d.get('port','')}\")" 2>/dev/null)
            egress_st="${GREEN}🏡 Proxy Dân Cư [${res_host}]${NC}"
        fi
    fi
    echo -e "  Nguồn Egress: ${egress_st}"
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
    if systemctl is-active --quiet warp-dashboard.service 2>/dev/null || pgrep -f "web_dashboard.py" >/dev/null; then
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
    echo -e "  Tài khoản đăng nhập     : ${YELLOW}admin${NC}"
    echo -e "  Mật khẩu mặc định       : ${YELLOW}datahub@2026${NC}"
    echo -e "  ${MAGENTA}*(Có thể đổi mật khẩu tại mục [11] hoặc nút '🔑 Đổi mật khẩu' trên Web)*${NC}"
}

change_dashboard_password() {
    local script_dir
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}   ${BOLD}${YELLOW}ĐỔI MẬT KHẨU ĐĂNG NHẬP WEB DASHBOARD${NC}                               ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    read -s -rp "Nhập mật khẩu mới (tối thiểu 6 ký tự): " new_pass
    echo ""
    if [ ${#new_pass} -lt 6 ]; then
        echo -e "${RED}[LỖI] Mật khẩu quá ngắn! Phải có ít nhất 6 ký tự.${NC}"
        return
    fi
    read -s -rp "Xác nhận lại mật khẩu mới: " confirm_pass
    echo ""
    if [ "$new_pass" != "$confirm_pass" ]; then
        echo -e "${RED}[LỖI] Mật khẩu xác nhận không khớp!${NC}"
        return
    fi

    python3 "${script_dir}/web_dashboard.py" --set-password "$new_pass"
    if systemctl is-active --quiet warp-dashboard.service 2>/dev/null; then
        systemctl restart warp-dashboard.service
    fi
    echo -e "${GREEN}Đã cập nhật mật khẩu Web Dashboard thành công!${NC}"
}

residential_proxy_menu() {
    local script_dir
    script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

    while true; do
        clear_screen
        echo -e "${CYAN}╔══════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║${NC}   ${BOLD}${YELLOW}QUẢN LÝ & CẤU HÌNH PROXY DÂN CƯ (RESIDENTIAL PROXY)${NC}                ${CYAN}║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════════════════════════════════════╝${NC}"

        # Đọc thông tin proxy hiện tại
        local current_info
        current_info=$(python3 -c "
import json, os
f = '/root/linux-cloudflare-warp/.residential_proxy.json'
if os.path.exists(f):
    try:
        d = json.load(open(f))
        proto = d.get('proto', 'socks5')
        host = d.get('host', '')
        port = d.get('port', 1080)
        user = d.get('username', '')
        active = d.get('active_source', 'warp')
        pwd = '******' if d.get('password') else ''
        url = f'{proto}://{user}:{pwd}@{host}:{port}' if user else f'{proto}://{host}:{port}'
        print(f'{active}|{url if host else \"Chưa cấu hình\"}')
    except:
        print('warp|Chưa cấu hình')
else:
    print('warp|Chưa cấu hình')
" 2>/dev/null)

        local active_src
        active_src=$(echo "$current_info" | cut -d'|' -f1)
        local proxy_url_display
        proxy_url_display=$(echo "$current_info" | cut -d'|' -f2)

        if [ "$active_src" = "residential" ]; then
            echo -e "  Egress hiện tại: ${GREEN}${BOLD}● ĐANG SỬ DỤNG PROXY DÂN CƯ${NC}"
        else
            echo -e "  Egress hiện tại: ${BLUE}${BOLD}🛡️ Đang sử dụng Cloudflare WARP Anycast${NC}"
        fi
        echo -e "  Địa chỉ Proxy  : ${YELLOW}${proxy_url_display}${NC}"
        echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
        echo -e "  ${BOLD}[1]${NC} 📋 Nhập nhanh chuỗi Proxy (IP:Port:User:Pass hoặc user:pass@host:port)"
        echo -e "  ${BOLD}[2]${NC} ✍️  Nhập thủ công chi tiết (Giao thức, Host, Port, User, Pass)"
        echo -e "  ${BOLD}[3]${NC} 🔍 Kiểm tra kết nối & Đo tốc độ tải (Benchmark & Public IP)"
        echo -e "  ${BOLD}[4]${NC} ⚡ ${BOLD}${GREEN}Kích hoạt Proxy Dân Cư cho Toàn bộ (Docker Daemon + Git CLI)${NC}"
        echo -e "  ${BOLD}[5]${NC} 🐳 Chỉ kích hoạt cho riêng Docker Daemon"
        echo -e "  ${BOLD}[6]${NC} 🐙 Chỉ kích hoạt cho riêng Git CLI (GitHub & GitLab)"
        echo -e "  ${BOLD}[7]${NC} 🛡️  ${BOLD}${BLUE}Khôi phục hệ thống về Cloudflare WARP Anycast${NC}"
        echo -e "  ${BOLD}[0]${NC} Quay lại Menu chính"
        echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
        read -rp "Chọn thao tác [0-7]: " res_choice

        case "$res_choice" in
            1)
                echo ""
                echo -e "${CYAN}Nhập chuỗi proxy từ nhà cung cấp (VD: 103.186.x.x:8080:username:password):${NC}"
                read -rp "Dán chuỗi Proxy: " raw_str
                if [ -n "$raw_str" ]; then
                    local parse_res
                    parse_res=$(python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import parse_proxy_string, save_residential_proxy, get_proxy_url
p = parse_proxy_string('''$raw_str''')
if p:
    save_residential_proxy(p)
    print('OK|' + get_proxy_url(p, hide_password=True))
else:
    print('ERR|Định dạng không hợp lệ!')
" 2>/dev/null)
                    if echo "$parse_res" | grep -q "^OK|"; then
                        local masked_u
                        masked_u=$(echo "$parse_res" | cut -d'|' -f2-)
                        echo -e "${GREEN}✓ Đã phân tích và lưu cấu hình thành công: ${YELLOW}${masked_u}${NC}"
                    else
                        echo -e "${RED}[LỖI] Không thể phân tích chuỗi proxy! Vui lòng thử nhập thủ công.${NC}"
                    fi
                fi
                pause
                ;;
            2)
                echo ""
                echo -e "${BOLD}Nhập thông tin kết nối Proxy Dân Cư:${NC}"
                read -rp "Giao thức [socks5/http/https, mặc định socks5]: " in_proto
                in_proto=${in_proto:-socks5}
                read -rp "Host / IP Proxy: " in_host
                if [ -z "$in_host" ]; then
                    echo -e "${RED}[LỖI] Host không được để trống!${NC}"
                    pause
                    continue
                fi
                read -rp "Port [mặc định 1080]: " in_port
                in_port=${in_port:-1080}
                read -rp "Username (để trống nếu Whitelist IP): " in_user
                read -s -rp "Password (để trống nếu Whitelist IP): " in_pass
                echo ""
                read -rp "Danh sách NO_PROXY [mặc định giữ nguyên]: " in_noproxy
                in_noproxy=${in_noproxy:-"localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24"}

                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import save_residential_proxy
save_residential_proxy({
    'proto': '''$in_proto''',
    'host': '''$in_host''',
    'port': int('''$in_port'''),
    'username': '''$in_user''',
    'password': '''$in_pass''',
    'no_proxy': '''$in_noproxy'''
})
print('Saved')
" 2>/dev/null
                echo -e "${GREEN}✓ Đã lưu cấu hình proxy thành công!${NC}"
                pause
                ;;
            3)
                echo ""
                echo -e "${YELLOW}Đang kiểm tra kết nối đến Proxy Dân Cư & đo tốc độ...${NC}"
                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import load_residential_proxy, test_residential_proxy, save_residential_proxy
cfg = load_residential_proxy()
if not cfg.get('host'):
    print('ERR: Chưa cấu hình Host cho Proxy Dân Cư!')
    sys.exit(1)
res = test_residential_proxy(cfg)
if res.get('success'):
    cfg['last_test'] = res
    save_residential_proxy(cfg)
    print(f\"SUCCESS|{res.get('ip')}|{res.get('isp')}|{res.get('country')}|{res.get('latency_ms')}|{res.get('speed_mb_s')}\")
else:
    print('FAIL|' + str(res.get('error', 'Unknown error')))
" 2>&1 | while read -r line; do
                    if echo "$line" | grep -q "^SUCCESS|"; then
                        local ip isp country latency speed
                        ip=$(echo "$line" | cut -d'|' -f2)
                        isp=$(echo "$line" | cut -d'|' -f3)
                        country=$(echo "$line" | cut -d'|' -f4)
                        latency=$(echo "$line" | cut -d'|' -f5)
                        speed=$(echo "$line" | cut -d'|' -f6)
                        echo -e "${GREEN}✓ Kết nối Proxy Dân Cư thành công!${NC}"
                        echo -e "  ➜ Egress Public IP : ${CYAN}${BOLD}${ip}${NC}"
                        echo -e "  ➜ Nhà mạng (ISP)   : ${YELLOW}${isp} (${country})${NC}"
                        echo -e "  ➜ Độ trễ (TTFB)    : ${MAGENTA}${latency} ms${NC}"
                        echo -e "  ➜ Tốc độ tải về    : ${GREEN}${BOLD}${speed} MB/s${NC}"
                    elif echo "$line" | grep -q "^FAIL|"; then
                        local err
                        err=$(echo "$line" | cut -d'|' -f2-)
                        echo -e "${RED}[LỖI KẾT NỐI] ${err}${NC}"
                    elif echo "$line" | grep -q "^ERR:"; then
                        echo -e "${RED}$line${NC}"
                    fi
                done
                pause
                ;;
            4)
                echo ""
                echo -e "${YELLOW}Đang kích hoạt Proxy Dân Cư cho Toàn bộ (Docker Daemon + Git)...${NC}"
                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import load_residential_proxy, get_proxy_url, apply_proxy_to_docker, apply_proxy_to_git, save_residential_proxy
cfg = load_residential_proxy()
url = get_proxy_url(cfg, hide_password=False)
if not url:
    print('ERR: Chưa cấu hình proxy!')
    sys.exit(1)
apply_proxy_to_docker(url, cfg.get('no_proxy', ''))
apply_proxy_to_git(url)
cfg['active_source'] = 'residential'
cfg['enabled'] = True
save_residential_proxy(cfg)
print('OK')
" 2>/dev/null
                echo -e "${GREEN}✓ Đã chuyển Docker Daemon và Git CLI sang dùng Proxy Dân Cư thành công!${NC}"
                pause
                ;;
            5)
                echo ""
                echo -e "${YELLOW}Đang áp dụng Proxy Dân Cư riêng cho Docker Daemon...${NC}"
                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import load_residential_proxy, get_proxy_url, apply_proxy_to_docker, save_residential_proxy
cfg = load_residential_proxy()
url = get_proxy_url(cfg, hide_password=False)
if not url:
    print('ERR: Chưa cấu hình proxy!')
    sys.exit(1)
apply_proxy_to_docker(url, cfg.get('no_proxy', ''))
cfg['active_source'] = 'residential'
save_residential_proxy(cfg)
print('OK')
" 2>/dev/null
                echo -e "${GREEN}✓ Đã kích hoạt Proxy Dân Cư cho Docker Daemon!${NC}"
                pause
                ;;
            6)
                echo ""
                echo -e "${YELLOW}Đang áp dụng Proxy Dân Cư riêng cho Git CLI (github.com & gitlab.com)...${NC}"
                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import load_residential_proxy, get_proxy_url, apply_proxy_to_git, save_residential_proxy
cfg = load_residential_proxy()
url = get_proxy_url(cfg, hide_password=False)
if not url:
    print('ERR: Chưa cấu hình proxy!')
    sys.exit(1)
apply_proxy_to_git(url)
cfg['active_source'] = 'residential'
save_residential_proxy(cfg)
print('OK')
" 2>/dev/null
                echo -e "${GREEN}✓ Đã kích hoạt Proxy Dân Cư cho Git CLI!${NC}"
                pause
                ;;
            7)
                echo ""
                echo -e "${YELLOW}Đang khôi phục toàn bộ hệ thống về Cloudflare WARP Anycast...${NC}"
                python3 -c "
import sys
sys.path.insert(0, '${script_dir}')
from web_dashboard import restore_warp_proxy
restore_warp_proxy()
print('OK')
" 2>/dev/null
                echo -e "${GREEN}✓ Đã khôi phục Docker và Git về Cloudflare WARP Anycast!${NC}"
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

# Vòng lặp Menu chính
while true; do
    header
    echo -e "  ${BOLD}[1]${NC} ${GREEN}Bật kết nối WARP${NC} (Connect)"
    echo -e "  ${BOLD}[2]${NC} ${RED}Tạm ngắt kết nối WARP${NC} (Disconnect)"
    echo -e "  ${BOLD}[3]${NC} ${YELLOW}Đổi cổng SOCKS5 Proxy${NC} (Change Port)"
    echo -e "  ${BOLD}[4]${NC} ${CYAN}Bật / Tắt Proxy cho Docker Daemon${NC} (kèm NO_PROXY)"
    echo -e "  ${BOLD}[5]${NC} ${BLUE}Bật / Tắt Proxy cho GitHub CLI${NC} (github.com)"
    echo -e "  ${BOLD}[6]${NC} ${MAGENTA}Bật / Tắt Proxy cho GitLab CLI${NC} (gitlab.com)"
    echo -e "  ${BOLD}[7]${NC} 🏡 ${BOLD}${GREEN}Cấu hình & Quản lý Proxy Dân Cư${NC} (Residential Proxy)"
    echo -e "  ${BOLD}[8]${NC} 🦊 ${BOLD}Xem cấu hình tăng tốc GitLab CI/CD & Runner${NC}"
    echo -e "  ${BOLD}[9]${NC} ⚡ ${BOLD}Đo kiểm tốc độ mạng quốc tế${NC} (Speed Test)"
    echo -e "  ${BOLD}[10]${NC} 🌐 ${CYAN}Mở Web Dashboard trên trình duyệt${NC} (Port 8888)"
    echo -e "  ${BOLD}[11]${NC} 🔐 ${YELLOW}Đổi mật khẩu Web Dashboard${NC}"
    echo -e "  ${BOLD}[12]${NC} 📋 Xem log dịch vụ (warp-svc logs)"
    echo -e "  ${BOLD}[0]${NC} Thoát"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────────────${NC}"
    read -rp "Chọn thao tác [0-12]: " choice

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
            residential_proxy_menu
            ;;
        8)
            show_gitlab_cicd_guide
            pause
            ;;
        9)
            speed_test_menu
            ;;
        10)
            start_web_dashboard
            pause
            ;;
        11)
            change_dashboard_password
            pause
            ;;
        12)
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
