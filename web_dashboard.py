#!/usr/bin/env python3
"""
Cloudflare WARP Web Dashboard & Management API
Features:
- Secure Authentication with SHA-256 + Salt
- Anti-Brute-Force Rate Limiting
- Session Management with HttpOnly Cookies
- Multi-Region Speed Test (Germany, Singapore, Japan, USA, UK, Finland)
- Smart Routing Controls (Docker NO_PROXY, Git, GitLab CI/CD)
Zero external dependencies - Uses Python 3 standard library.
"""

import concurrent.futures
import hashlib
import http.cookies
import http.server
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import tempfile
import time
import urllib.parse

PORT = int(os.environ.get("WARP_DASHBOARD_PORT", "8888"))
HOST = os.environ.get("WARP_DASHBOARD_HOST", "0.0.0.0")
AUTH_FILE = os.environ.get("WARP_AUTH_FILE", "/root/linux-cloudflare-warp/.warp_auth.json")

# In-memory session store: token -> {"username": str, "expires": float}
SESSIONS = {}
# Rate limiting: ip -> [timestamp1, timestamp2, ...]
FAILED_ATTEMPTS = {}

DATA_CENTERS = {
    "SG_SIN": {
        "name": "Singapore (Hetzner DC)",
        "country": "Singapore",
        "flag": "🇸🇬",
        "url": "https://sin-speed.hetzner.com/100MB.bin"
    },
    "JP_TYO": {
        "name": "Nhật Bản (Tokyo, Linode)",
        "country": "Nhật Bản",
        "flag": "🇯🇵",
        "url": "http://speedtest.tokyo2.linode.com/100MB-tokyo2.bin"
    },
    "DE_FSN": {
        "name": "Đức (Falkenstein, Hetzner)",
        "country": "Đức",
        "flag": "🇩🇪",
        "url": "https://fsn1-speed.hetzner.com/100MB.bin"
    },
    "DE_NBG": {
        "name": "Đức (Nuremberg, Hetzner)",
        "country": "Đức",
        "flag": "🇩🇪",
        "url": "https://nbg1-speed.hetzner.com/100MB.bin"
    },
    "US_ASH": {
        "name": "Mỹ - Bờ Đông (Ashburn, Hetzner)",
        "country": "Hoa Kỳ",
        "flag": "🇺🇸",
        "url": "https://ash-speed.hetzner.com/100MB.bin"
    },
    "US_HIL": {
        "name": "Mỹ - Bờ Tây (Hillsboro, Hetzner)",
        "country": "Hoa Kỳ",
        "flag": "🇺🇸",
        "url": "https://hil-speed.hetzner.com/100MB.bin"
    },
    "UK_LON": {
        "name": "Anh Quốc (London, Linode)",
        "country": "Vương quốc Anh",
        "flag": "🇬🇧",
        "url": "http://speedtest.london.linode.com/100MB-london.bin"
    },
    "FI_HEL": {
        "name": "Phần Lan (Helsinki, Hetzner)",
        "country": "Phần Lan",
        "flag": "🇫🇮",
        "url": "https://hel1-speed.hetzner.com/100MB.bin"
    }
}

# ==============================================================================
# BẢO MẬT & XÁC THỰC
# ==============================================================================

def hash_password(password, salt=None):
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hashed, salt

def init_auth():
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Mật khẩu mặc định khởi tạo
    default_user = os.environ.get("WARP_DASHBOARD_USER", "admin")
    default_pass = os.environ.get("WARP_DASHBOARD_PASS", "datahub@2026")
    h, salt = hash_password(default_pass)
    auth_data = {
        "username": default_user,
        "password_hash": h,
        "salt": salt
    }
    os.makedirs(os.path.dirname(AUTH_FILE) if os.path.dirname(AUTH_FILE) else ".", exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump(auth_data, f)
    os.chmod(AUTH_FILE, 0o600)
    return auth_data

def set_password(new_password, username="admin"):
    h, salt = hash_password(new_password)
    auth_data = {
        "username": username,
        "password_hash": h,
        "salt": salt
    }
    os.makedirs(os.path.dirname(AUTH_FILE) if os.path.dirname(AUTH_FILE) else ".", exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump(auth_data, f)
    os.chmod(AUTH_FILE, 0o600)
    SESSIONS.clear()
    return True

def verify_credentials(user, password):
    auth_data = init_auth()
    if user != auth_data.get("username"):
        return False
    h, _ = hash_password(password, auth_data.get("salt"))
    return h == auth_data.get("password_hash")

def check_rate_limit(client_ip):
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(client_ip, []) if now - t < 300]
    FAILED_ATTEMPTS[client_ip] = attempts
    return len(attempts) >= 5

def record_failed_attempt(client_ip):
    now = time.time()
    if client_ip not in FAILED_ATTEMPTS:
        FAILED_ATTEMPTS[client_ip] = []
    FAILED_ATTEMPTS[client_ip].append(now)

def clear_failed_attempts(client_ip):
    if client_ip in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[client_ip]

def get_authenticated_user(headers):
    cookie_header = headers.get("Cookie", "")
    if not cookie_header:
        return None
    cookie = http.cookies.SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return None
    if "warp_session" not in cookie:
        return None
    token = cookie["warp_session"].value
    session = SESSIONS.get(token)
    if not session:
        return None
    if time.time() > session.get("expires", 0):
        del SESSIONS[token]
        return None
    return session.get("username")

# ==============================================================================
# HÀM HỖ TRỢ HỆ THỐNG
# ==============================================================================

def run_cmd(cmd, timeout=15):
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def get_docker_info():
    conf_path = "/etc/systemd/system/docker.service.d/http-proxy.conf"
    conf_exists = os.path.exists(conf_path)
    raw_conf = ""
    if conf_exists:
        try:
            with open(conf_path, "r") as f:
                raw_conf = f.read()
        except Exception:
            pass

    try:
        out = subprocess.check_output(["docker", "info"], stderr=subprocess.STDOUT, text=True, timeout=5)
        http_p = re.search(r"HTTP Proxy:\s*(.+)", out)
        https_p = re.search(r"HTTPS Proxy:\s*(.+)", out)
        no_p = re.search(r"No Proxy:\s*(.+)", out)
        ver = re.search(r"Server Version:\s*(.+)", out)
        return {
            "installed": True,
            "running": True,
            "version": ver.group(1).strip() if ver else "Unknown",
            "http_proxy": http_p.group(1).strip() if http_p else "",
            "https_proxy": https_p.group(1).strip() if https_p else "",
            "no_proxy": no_p.group(1).strip() if no_p else "",
            "conf_exists": conf_exists,
            "raw_conf": raw_conf
        }
    except Exception as e:
        return {
            "installed": True if os.path.exists("/usr/bin/docker") else False,
            "running": False,
            "version": "",
            "http_proxy": "",
            "https_proxy": "",
            "no_proxy": "",
            "conf_exists": conf_exists,
            "raw_conf": raw_conf,
            "error": str(e)
        }

def scan_dockerfiles(base_path="/root", max_depth=3):
    if not base_path or not os.path.exists(base_path):
        base_path = "/root"
    base_path = os.path.abspath(base_path)
    
    ignore_dirs = {
        ".git", "node_modules", "venv", ".venv", "__pycache__",
        ".cache", "tmp", ".gemini", "proc", "sys", "dev"
    }

    found = []
    base_depth = base_path.rstrip(os.path.sep).count(os.path.sep)

    try:
        for root, dirs, files in os.walk(base_path, topdown=True, followlinks=False):
            cur_depth = root.count(os.path.sep) - base_depth
            if cur_depth >= max_depth:
                dirs.clear()
                continue
            
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]

            for f in sorted(files):
                f_lower = f.lower()
                if f_lower == "dockerfile" or f_lower.startswith("dockerfile.") or f_lower.endswith(".dockerfile"):
                    full_p = os.path.join(root, f)
                    try:
                        st = os.stat(full_p)
                        if st.st_size > 2 * 1024 * 1024:
                            continue
                        rel_p = os.path.relpath(full_p, base_path)
                        dir_name = os.path.basename(root) or os.path.basename(base_path)
                        found.append({
                            "name": f,
                            "rel_path": rel_p,
                            "full_path": full_p,
                            "dir_path": root,
                            "dir_name": dir_name,
                            "size_bytes": st.st_size,
                            "mtime": int(st.st_mtime)
                        })
                    except Exception:
                        pass
    except Exception:
        pass

    found.sort(key=lambda x: (x["rel_path"].count(os.path.sep), x["rel_path"]))
    return found

def read_dockerfile_content(file_path):
    if not file_path or not os.path.isfile(file_path):
        return {"success": False, "error": f"Tệp không tồn tại: {file_path}"}
    try:
        st = os.stat(file_path)
        if st.st_size > 2 * 1024 * 1024:
            return {"success": False, "error": "Tệp quá lớn (> 2MB) để hiển thị"}
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "success": True,
            "content": content,
            "file_path": os.path.abspath(file_path),
            "dir_path": os.path.dirname(os.path.abspath(file_path)),
            "file_name": os.path.basename(file_path),
            "dir_name": os.path.basename(os.path.dirname(os.path.abspath(file_path)))
        }
    except Exception as e:
        return {"success": False, "error": f"Không thể đọc tệp: {str(e)}"}

RESIDENTIAL_PROXY_FILE = os.environ.get("RESIDENTIAL_PROXY_FILE", "/root/linux-cloudflare-warp/.residential_proxy.json")

def load_residential_proxy():
    if os.path.exists(RESIDENTIAL_PROXY_FILE):
        try:
            with open(RESIDENTIAL_PROXY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "enabled": False,
        "proto": "socks5",
        "host": "",
        "port": 1080,
        "username": "",
        "password": "",
        "no_proxy": "localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24",
        "active_source": "warp",
        "last_test": None
    }

def save_residential_proxy(data):
    current = load_residential_proxy()
    if isinstance(data, dict):
        if "password" in data and not data["password"] and current.get("password"):
            data["password"] = current["password"]
        for k, v in data.items():
            current[k] = v
    else:
        current = data
    os.makedirs(os.path.dirname(RESIDENTIAL_PROXY_FILE) if os.path.dirname(RESIDENTIAL_PROXY_FILE) else ".", exist_ok=True)
    with open(RESIDENTIAL_PROXY_FILE, "w") as f:
        json.dump(current, f, indent=2)
    os.chmod(RESIDENTIAL_PROXY_FILE, 0o600)
    return True

def parse_proxy_string(raw):
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    proto = "socks5"
    if "://" in raw:
        p, rest = raw.split("://", 1)
        if p.lower() in ["socks5", "http", "https"]:
            proto = p.lower()
            raw = rest
    
    if "@" in raw:
        auth_part, host_part = raw.split("@", 1)
        if ":" in auth_part:
            user, pwd = auth_part.split(":", 1)
        else:
            user, pwd = auth_part, ""
        if ":" in host_part:
            host, port = host_part.split(":", 1)
        else:
            host, port = host_part, "1080"
        try:
            return {"proto": proto, "host": host.strip(), "port": int(port.strip()), "username": user.strip(), "password": pwd.strip()}
        except Exception:
            return None

    parts = raw.split(":")
    if len(parts) == 4:
        try:
            return {"proto": proto, "host": parts[0].strip(), "port": int(parts[1].strip()), "username": parts[2].strip(), "password": parts[3].strip()}
        except Exception:
            return None
    elif len(parts) == 2:
        try:
            return {"proto": proto, "host": parts[0].strip(), "port": int(parts[1].strip()), "username": "", "password": ""}
        except Exception:
            return None
    return None

def get_proxy_url(config, hide_password=False):
    if not config:
        return ""
    proto = config.get("proto", "socks5").lower()
    host = str(config.get("host", "")).strip()
    port = str(config.get("port", "")).strip()
    username = str(config.get("username", "")).strip()
    password = str(config.get("password", "")).strip()

    if not host or not port:
        return ""

    if username:
        user_enc = urllib.parse.quote_plus(username)
        pass_display = "******" if hide_password else urllib.parse.quote_plus(password)
        return f"{proto}://{user_enc}:{pass_display}@{host}:{port}"
    return f"{proto}://{host}:{port}"

def test_residential_proxy(config):
    proxy_url = get_proxy_url(config, hide_password=False)
    if not proxy_url:
        return {"success": False, "error": "Chưa nhập đầy đủ Host và Port của Proxy!"}

    t0 = time.time()
    cmd = ["curl", "-m", "10", "-s", "-x", proxy_url, "-w", "%{time_starttransfer}", "https://cloudflare.com/cdn-cgi/trace"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=12)
    
    if p.returncode != 0:
        err_msg = p.stderr.strip() or f"Không thể kết nối đến proxy qua {config.get('host')}:{config.get('port')} (Mã lỗi: {p.returncode})"
        return {"success": False, "error": err_msg}
    
    trace_out = p.stdout
    ttfb = 0
    time_m = re.search(r"(\d+\.\d+)$", trace_out)
    if time_m:
        try:
            ttfb = round(float(time_m.group(1)) * 1000, 1)
        except Exception:
            pass

    ip_m = re.search(r"ip=([^\s]+)", trace_out)
    egress_ip = ip_m.group(1) if ip_m else "Unknown"
    loc_m = re.search(r"loc=([A-Z0-9]+)", trace_out)
    loc = loc_m.group(1) if loc_m else ""
    colo_m = re.search(r"colo=([A-Z0-9]+)", trace_out)
    colo = colo_m.group(1) if colo_m else ""
    warp_status = "warp=on" in trace_out

    speed_mb_s = 0.0
    try:
        speed_url = "https://speed.cloudflare.com/__down?bytes=5000000"
        speed_cmd = ["curl", "-m", "8", "-s", "-x", proxy_url, "-w", "%{speed_download}", "-o", "/dev/null", speed_url]
        sp = subprocess.run(speed_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if sp.returncode == 0 and sp.stdout.strip():
            raw_spd = float(sp.stdout.strip())
            speed_mb_s = round(raw_spd / (1024 * 1024), 2)
    except Exception:
        pass

    isp = "Residential / ISP"
    country_name = loc
    city = ""
    try:
        ip_cmd = ["curl", "-m", "4", "-s", f"http://ip-api.com/json/{egress_ip}"]
        ip_res = subprocess.run(ip_cmd, stdout=subprocess.PIPE, text=True, timeout=5)
        if ip_res.returncode == 0:
            ip_info = json.loads(ip_res.stdout)
            if ip_info.get("status") == "success":
                isp = ip_info.get("isp") or ip_info.get("org") or isp
                country_name = ip_info.get("country") or country_name
                city = ip_info.get("city") or ""
    except Exception:
        pass

    result = {
        "success": True,
        "proxy_url_masked": get_proxy_url(config, hide_password=True),
        "ip": egress_ip,
        "loc": loc,
        "colo": colo,
        "isp": isp,
        "city": city,
        "country": country_name,
        "latency_ms": ttfb,
        "speed_mb_s": speed_mb_s,
        "is_warp": warp_status,
        "tested_at": int(time.time())
    }
    return result

def apply_proxy_to_docker(proxy_url, no_proxy):
    if not no_proxy:
        no_proxy = "localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24"
    conf_dir = "/etc/systemd/system/docker.service.d"
    conf_path = f"{conf_dir}/http-proxy.conf"
    os.makedirs(conf_dir, exist_ok=True)
    content = f"""[Service]
Environment="HTTP_PROXY={proxy_url}"
Environment="HTTPS_PROXY={proxy_url}"
Environment="NO_PROXY={no_proxy}"
"""
    with open(conf_path, "w") as f:
        f.write(content)
    run_cmd("systemctl daemon-reload && systemctl restart docker", timeout=30)
    time.sleep(1)
    return get_docker_info()

def apply_proxy_to_git(proxy_url):
    run_cmd(f"git config --global http.\"https://github.com/\".proxy \"{proxy_url}\"")
    run_cmd(f"git config --global http.\"https://gitlab.com/\".proxy \"{proxy_url}\"")
    return True

def restore_warp_proxy():
    status = get_warp_status()
    port = status.get("port", 40000)
    warp_proxy_url = f"socks5://127.0.0.1:{port}"
    no_proxy = "localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24"
    apply_proxy_to_docker(warp_proxy_url, no_proxy)
    apply_proxy_to_git(warp_proxy_url)
    res_cfg = load_residential_proxy()
    res_cfg["active_source"] = "warp"
    res_cfg["enabled"] = False
    save_residential_proxy(res_cfg)
    return True

def get_warp_status():
    _, status_out, _ = run_cmd("warp-cli --accept-tos status 2>/dev/null || warp-cli status 2>/dev/null", timeout=5)
    is_connected = "Connected" in status_out
    
    _, settings_out, _ = run_cmd("warp-cli --accept-tos settings list 2>/dev/null || warp-cli settings 2>/dev/null", timeout=5)
    port_match = re.search(r"WarpProxy on port (\d+)", settings_out)
    if not port_match:
        port_match = re.search(r"port[:\s]+(\d+)", settings_out, re.IGNORECASE)
    proxy_port = int(port_match.group(1)) if port_match else 40000

    colo = "N/A"
    ip = "N/A"
    warp_on = False
    if is_connected:
        _, trace_out, _ = run_cmd(f"curl -m 4 --socks5-hostname 127.0.0.1:{proxy_port} -s https://cloudflare.com/cdn-cgi/trace", timeout=6)
        if "warp=on" in trace_out:
            warp_on = True
        colo_m = re.search(r"colo=([A-Z0-9]+)", trace_out)
        if colo_m:
            colo = colo_m.group(1)
        ip_m = re.search(r"ip=([^\s]+)", trace_out)
        if ip_m:
            ip = ip_m.group(1)

    docker_proxy_enabled = False
    docker_conf_path = "/etc/systemd/system/docker.service.d/http-proxy.conf"
    if os.path.exists(docker_conf_path):
        with open(docker_conf_path, "r") as f:
            content = f.read()
            if "HTTP_PROXY" in content and not content.strip().startswith("#"):
                docker_proxy_enabled = True

    _, git_proxy_out, _ = run_cmd("git config --global http.\"https://github.com/\".proxy")
    git_proxy_enabled = bool(git_proxy_out)

    _, gitlab_proxy_out, _ = run_cmd("git config --global http.\"https://gitlab.com/\".proxy")
    gitlab_proxy_enabled = bool(gitlab_proxy_out)

    res_cfg = load_residential_proxy()

    return {
        "connected": is_connected,
        "warp_active": warp_on,
        "port": proxy_port,
        "colo": colo,
        "ip": ip,
        "docker_proxy": docker_proxy_enabled,
        "docker_info": get_docker_info(),
        "git_proxy": git_proxy_enabled,
        "gitlab_proxy": gitlab_proxy_enabled,
        "raw_status": status_out or "WARP Service Offline",
        "residential_proxy": {
            "configured": bool(res_cfg.get("host") and res_cfg.get("port")),
            "enabled": res_cfg.get("enabled", False),
            "proto": res_cfg.get("proto", "socks5"),
            "host": res_cfg.get("host", ""),
            "port": res_cfg.get("port", 1080),
            "username": res_cfg.get("username", ""),
            "has_password": bool(res_cfg.get("password")),
            "no_proxy": res_cfg.get("no_proxy", ""),
            "active_source": res_cfg.get("active_source", "warp"),
            "proxy_url_masked": get_proxy_url(res_cfg, hide_password=True),
            "last_test": res_cfg.get("last_test")
        }
    }

def benchmark_single_dc(dc_key, port):
    dc = DATA_CENTERS.get(dc_key)
    if not dc:
        return None
    url = dc["url"]
    t0 = time.time()
    cmd = f"curl -m 7 --socks5-hostname 127.0.0.1:{port} -r 0-3145728 -s -w '%{{speed_download}},%{{time_starttransfer}},%{{time_total}}' -o /dev/null '{url}'"
    _, out, _ = run_cmd(cmd, timeout=9)
    duration = time.time() - t0
    parts = out.split(",")
    try:
        speed_bytes = float(parts[0]) if len(parts) > 0 and parts[0] else 0.0
        ttfb = float(parts[1]) if len(parts) > 1 and parts[1] else 0.0
        total_t = float(parts[2]) if len(parts) > 2 and parts[2] else duration
        speed_mb_s = speed_bytes / (1024 * 1024)
        latency_ms = int(ttfb * 1000)
    except Exception:
        speed_mb_s = 0.0
        latency_ms = 0
        total_t = duration

    return {
        "id": dc_key,
        "name": dc["name"],
        "country": dc["country"],
        "flag": dc["flag"],
        "speed_mb_s": round(speed_mb_s, 2),
        "latency_ms": latency_ms,
        "duration_sec": round(total_t, 2)
    }

# ==============================================================================
# GIAO DIỆN HTML (LOGIN & DASHBOARD)
# ==============================================================================

LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Đăng Nhập - Cloudflare WARP Control Center</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --primary: #f6821f;
      --primary-hover: #fa973f;
      --primary-glow: rgba(246, 130, 31, 0.3);
      --accent: #00d2ff;
      --danger: #ef4444;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
    body {
      background-color: var(--bg);
      background-image: 
        radial-gradient(at 0% 0%, rgba(246, 130, 31, 0.12) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(0, 210, 255, 0.12) 0px, transparent 50%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .login-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-radius: 24px;
      padding: 40px 36px;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
      text-align: center;
      position: relative;
    }
    .brand-logo {
      width: 56px;
      height: 56px;
      background: linear-gradient(135deg, #f6821f, #ff5e3a);
      border-radius: 16px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 30px var(--primary-glow);
      margin-bottom: 20px;
    }
    .brand-logo svg { width: 30px; height: 30px; fill: white; }
    h1 { font-size: 22px; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.5px; }
    p.sub { font-size: 13px; color: var(--text-muted); margin-bottom: 28px; line-height: 1.5; }
    .form-group { text-align: left; margin-bottom: 20px; }
    label { display: block; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 8px; }
    .input-wrap { position: relative; }
    input[type="text"], input[type="password"] {
      width: 100%;
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      padding: 12px 16px;
      color: white;
      font-size: 14px;
      outline: none;
      transition: all 0.2s;
    }
    input[type="text"]:focus, input[type="password"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 16px var(--primary-glow);
    }
    .remember-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      font-size: 13px;
      color: var(--text-muted);
    }
    .btn-login {
      width: 100%;
      background: var(--primary);
      color: white;
      border: none;
      border-radius: 12px;
      padding: 13px;
      font-size: 14px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 6px 20px var(--primary-glow);
      transition: all 0.2s;
    }
    .btn-login:hover {
      background: var(--primary-hover);
      transform: translateY(-1px);
    }
    .btn-login:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
    .alert-error {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #fca5a5;
      padding: 10px 14px;
      border-radius: 10px;
      font-size: 13px;
      margin-bottom: 20px;
      display: none;
      text-align: left;
    }
    .footer-note {
      margin-top: 24px;
      font-size: 11px;
      color: #64748b;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
  </style>
</head>
<body>

<div class="login-card">
  <div class="brand-logo">
    <svg viewBox="0 0 24 24"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3z"/></svg>
  </div>
  <h1>Cloudflare WARP Center</h1>
  <p class="sub">Xác thực quyền quản trị máy chủ Data Center</p>

  <div id="errorAlert" class="alert-error"></div>

  <form id="loginForm" onsubmit="handleLogin(event)">
    <div class="form-group">
      <label>Tên đăng nhập</label>
      <input type="text" id="username" required autocomplete="username" placeholder="admin" autofocus />
    </div>

    <div class="form-group">
      <label>Mật khẩu</label>
      <input type="password" id="password" required autocomplete="current-password" placeholder="••••••••" />
    </div>

    <div class="remember-row">
      <label style="display:flex; align-items:center; gap:8px; margin:0; text-transform:none; cursor:pointer;">
        <input type="checkbox" id="rememberMe" checked /> Ghi nhớ đăng nhập
      </label>
    </div>

    <button type="submit" id="submitBtn" class="btn-login">Đăng nhập</button>
  </form>

  <div class="footer-note">
    <span>🔒</span> Mã hóa SHA-256 & Chống brute-force bảo vệ
  </div>
</div>

<script>
  async function handleLogin(e) {
    e.preventDefault();
    const btn = document.getElementById('submitBtn');
    const alertBox = document.getElementById('errorAlert');
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;
    const remember = document.getElementById('rememberMe').checked;

    btn.disabled = true;
    btn.innerText = 'Đang xác thực...';
    alertBox.style.display = 'none';

    try {
      const res = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, remember })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        window.location.href = '/';
      } else {
        alertBox.innerText = data.error || 'Sai tên đăng nhập hoặc mật khẩu!';
        alertBox.style.display = 'block';
      }
    } catch (err) {
      alertBox.innerText = 'Lỗi kết nối tới máy chủ!';
      alertBox.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.innerText = 'Đăng nhập';
    }
  }
</script>

</body>
</html>
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cloudflare WARP Control Center</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #090d16;
      --card-bg: rgba(18, 24, 38, 0.7);
      --card-border: rgba(255, 255, 255, 0.08);
      --primary: #f6821f;
      --primary-hover: #fa973f;
      --primary-glow: rgba(246, 130, 31, 0.25);
      --accent: #00d2ff;
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.25);
      --danger: #ef4444;
      --danger-glow: rgba(239, 68, 68, 0.25);
      --text: #f3f4f6;
      --text-muted: #9ca3af;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }

    body {
      background-color: var(--bg);
      background-image: 
        radial-gradient(at 0% 0%, rgba(246, 130, 31, 0.08) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(0, 210, 255, 0.08) 0px, transparent 50%);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 30px 20px;
    }

    .container { width: 100%; max-width: 980px; }

    header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; }

    .brand { display: flex; align-items: center; gap: 14px; }

    .brand-logo {
      width: 44px; height: 44px;
      background: linear-gradient(135deg, #f6821f, #ff5e3a);
      border-radius: 12px;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 8px 24px var(--primary-glow);
    }

    .brand-logo svg { width: 24px; height: 24px; fill: white; }
    .brand-text h1 { font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }
    .brand-text p { font-size: 13px; color: var(--text-muted); }

    .header-actions { display: flex; align-items: center; gap: 10px; }

    .badge-mode {
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--success);
      font-size: 12px; font-weight: 600;
      padding: 6px 12px; border-radius: 20px;
      display: flex; align-items: center; gap: 6px;
    }

    .badge-mode .dot {
      width: 6px; height: 6px;
      background: var(--success); border-radius: 50%;
      box-shadow: 0 0 8px var(--success);
    }

    .dashboard-grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 20px;
      margin-bottom: 24px;
    }

    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-radius: 18px;
      padding: 24px;
      position: relative;
      overflow: hidden;
      transition: border-color 0.25s, transform 0.25s;
    }

    .card:hover { border-color: rgba(255, 255, 255, 0.15); }

    .col-3 { grid-column: span 3; }
    .col-4 { grid-column: span 4; }
    .col-5 { grid-column: span 5; }
    .col-6 { grid-column: span 6; }
    .col-7 { grid-column: span 7; }
    .col-8 { grid-column: span 8; }
    .col-12 { grid-column: span 12; }

    @media (max-width: 860px) {
      .col-7, .col-5, .col-6, .col-4, .col-3, .col-8 { grid-column: span 12; }
    }

    /* Tabs Navigation Bar */
    .tabs-bar {
      display: flex;
      gap: 6px;
      margin-bottom: 22px;
      background: rgba(15, 23, 42, 0.75);
      backdrop-filter: blur(16px);
      padding: 6px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      overflow-x: auto;
    }
    .tab-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 18px;
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      background: transparent;
      border: 1px solid transparent;
      border-radius: 10px;
      cursor: pointer;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      white-space: nowrap;
      user-select: none;
    }
    .tab-btn:hover {
      color: var(--text);
      background: rgba(255, 255, 255, 0.05);
    }
    .tab-btn.active {
      color: #ffffff;
      background: linear-gradient(135deg, rgba(249, 115, 22, 0.95) 0%, rgba(234, 88, 12, 0.95) 100%);
      box-shadow: 0 4px 16px var(--primary-glow);
      border-color: rgba(255, 255, 255, 0.2);
    }
    .tab-pane {
      display: none;
      animation: tabFadeIn 0.25s ease-out;
    }
    .tab-pane.active {
      display: block;
    }
    @keyframes tabFadeIn {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Metric & Shortcut Cards */
    .metric-card {
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 16px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.2s;
    }
    .metric-card:hover {
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.12);
      transform: translateY(-2px);
    }
    .metric-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
    }
    .metric-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .badge-status {
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 12px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .badge-status.active {
      background: rgba(16, 185, 129, 0.15);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .badge-status.inactive {
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-muted);
      border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .quick-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }
    .chip-btn {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.1);
      color: var(--text);
      font-size: 11px;
      font-weight: 600;
      padding: 5px 10px;
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.15s;
    }
    .chip-btn:hover {
      background: rgba(255, 255, 255, 0.12);
      border-color: var(--primary);
    }

    .status-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
    .status-indicator { display: flex; align-items: center; gap: 12px; }

    .status-pulse {
      width: 14px; height: 14px; border-radius: 50%;
      background: var(--success); box-shadow: 0 0 16px var(--success);
    }

    .status-pulse.disconnected { background: var(--danger); box-shadow: 0 0 16px var(--danger); }
    .status-title { font-size: 18px; font-weight: 700; }
    .status-subtitle { font-size: 13px; color: var(--text-muted); }

    .stats-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 18px; }

    .stat-box {
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.05);
      border-radius: 12px; padding: 12px 14px;
    }

    .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); margin-bottom: 4px; }
    .stat-value { font-family: 'JetBrains Mono', monospace; font-size: 15px; font-weight: 600; color: var(--text); }

    .control-item { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
    .control-item:last-child { border-bottom: none; padding-bottom: 0; }
    .control-info h4 { font-size: 14px; font-weight: 600; margin-bottom: 3px; }
    .control-info p { font-size: 12px; color: var(--text-muted); }

    .switch { position: relative; display: inline-block; width: 48px; height: 26px; }
    .switch input { opacity: 0; width: 0; height: 0; }
    .slider {
      position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
      background-color: rgba(255, 255, 255, 0.15);
      transition: .3s cubic-bezier(0.4, 0, 0.2, 1);
      border-radius: 34px;
    }
    .slider:before {
      position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px;
      background-color: white; transition: .3s cubic-bezier(0.4, 0, 0.2, 1);
      border-radius: 50%;
    }
    input:checked + .slider { background-color: var(--primary); box-shadow: 0 0 12px var(--primary-glow); }
    input:checked + .slider:before { transform: translateX(22px); }

    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      font-size: 13px; font-weight: 600; padding: 9px 15px; border-radius: 10px;
      border: none; cursor: pointer; transition: all 0.2s;
    }
    .btn-primary { background: var(--primary); color: white; box-shadow: 0 4px 16px var(--primary-glow); }
    .btn-primary:hover { background: var(--primary-hover); transform: translateY(-1px); }
    .btn-secondary { background: rgba(255, 255, 255, 0.08); color: var(--text); border: 1px solid rgba(255, 255, 255, 0.1); }
    .btn-secondary:hover { background: rgba(255, 255, 255, 0.14); }
    .btn-danger { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); }
    .btn-danger:hover { background: rgba(239, 68, 68, 0.25); }
    .btn-sm { padding: 6px 12px; font-size: 12px; }

    .select-style {
      background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: var(--text);
      padding: 7px 12px;
      border-radius: 8px;
      font-size: 12px;
      outline: none;
      width: 100%;
      cursor: pointer;
    }
    .select-style option { background: #111827; color: white; }

    .speed-gauge { text-align: center; padding: 12px 0; }
    .speed-number { font-family: 'JetBrains Mono', monospace; font-size: 36px; font-weight: 800; color: var(--accent); }

    .benchmark-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 12px;
    }
    .benchmark-table th {
      text-align: left; padding: 8px 10px; color: var(--text-muted);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      font-weight: 600; text-transform: uppercase; font-size: 11px;
    }
    .benchmark-table td { padding: 9px 10px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
    .benchmark-table tr:last-child td { border-bottom: none; }

    .terminal-box {
      background: #04070d; border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 12px; padding: 16px;
      font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #94a3b8;
      max-height: 180px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6;
    }

    .code-snippet {
      background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px; padding: 12px 14px;
      font-family: 'JetBrains Mono', monospace; font-size: 12px;
      display: flex; justify-content: space-between; align-items: center; margin-top: 8px;
    }
    .code-snippet code { color: var(--accent); overflow-x: auto; }

    #toast {
      position: fixed; bottom: 24px; right: 24px;
      background: #1e293b; border: 1px solid rgba(255, 255, 255, 0.1);
      color: white; padding: 12px 20px; border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
      display: none; align-items: center; gap: 10px;
      font-size: 13px; font-weight: 500; z-index: 999;
    }

    .modal-backdrop {
      position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(8px); display: none; align-items: center; justify-content: center;
      z-index: 1000; animation: fadeIn 0.2s ease;
    }
    .modal-card {
      background: #0f172a; border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 16px; padding: 24px; width: 90%; max-width: 420px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    }
    .modal-header {
      display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px;
    }
    .modal-header h3 { font-size: 16px; font-weight: 700; color: white; margin: 0; }
    .modal-close {
      background: none; border: none; font-size: 24px; color: var(--text-muted);
      cursor: pointer; line-height: 1; padding: 0 4px;
    }
    .modal-close:hover { color: white; }
    .input-style {
      width: 100%; box-sizing: border-box; background: rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 8px;
      padding: 10px 14px; color: white; font-size: 13px; outline: none;
      transition: border-color 0.2s;
    }
    .input-style:focus { border-color: var(--primary); }
    .modal-alert {
      padding: 10px 14px; border-radius: 8px; font-size: 12px; margin-bottom: 14px; display: none;
    }
    .modal-alert-error { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); }
    .modal-alert-success { background: rgba(16, 185, 129, 0.15); color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3); }
  </style>
</head>
<body>

<div class="container">
  <header>
    <div class="brand">
      <div class="brand-logo">
        <svg viewBox="0 0 24 24"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3z"/></svg>
      </div>
      <div class="brand-text">
        <h1>Cloudflare WARP Control Center</h1>
        <p>Bảng điều khiển & Tối ưu hóa SOCKS5 Proxy cho Máy chủ Data Center</p>
      </div>
    </div>
    <div class="header-actions">
      <div class="badge-mode">
        <div class="dot"></div>
        Proxy Mode (SOCKS5)
      </div>
      <button onclick="openChangePasswordModal()" class="btn btn-secondary btn-sm" title="Đổi mật khẩu Web Dashboard">
        🔑 Đổi mật khẩu
      </button>
      <button onclick="logout()" class="btn btn-secondary btn-sm" title="Đăng xuất khỏi phiên làm việc">
        🚪 Đăng xuất
      </button>
    </div>
  </header>

  <!-- Navigation Tabs Bar -->
  <nav class="tabs-bar">
    <button class="tab-btn active" onclick="switchTab('overview')" id="tabBtn-overview">
      <span>📊</span> <span>Tổng quan & Kết nối</span>
    </button>
    <button class="tab-btn" onclick="switchTab('speedtest')" id="tabBtn-speedtest">
      <span>⚡</span> <span>Đo kiểm Tốc độ</span>
    </button>
    <button class="tab-btn" onclick="switchTab('routing')" id="tabBtn-routing">
      <span>🔀</span> <span>Điều hướng Proxy</span>
    </button>
    <button class="tab-btn" onclick="switchTab('docker')" id="tabBtn-docker">
      <span>🐳</span> <span>Docker & Build</span>
    </button>
    <button class="tab-btn" onclick="switchTab('residential')" id="tabBtn-residential">
      <span>🏡</span> <span>Proxy Dân Cư</span>
    </button>
    <button class="tab-btn" onclick="switchTab('gitlab')" id="tabBtn-gitlab">
      <span>🦊</span> <span>GitLab CI/CD</span>
    </button>
    <button class="tab-btn" onclick="switchTab('logs')" id="tabBtn-logs">
      <span>📋</span> <span>Nhật ký & Chẩn đoán</span>
    </button>
  </nav>

  <!-- TAB 1: TỔNG QUAN & KẾT NỐI -->
  <div class="tab-pane active" id="tab-overview">
    <div class="dashboard-grid">
      <!-- Hero Status Card (col-12) -->
      <div class="card col-12">
        <div class="status-header">
          <div class="status-indicator">
            <div id="statusDot" class="status-pulse"></div>
            <div>
              <div id="statusText" class="status-title">Đang tải trạng thái...</div>
              <div id="statusSub" class="status-subtitle">Kiểm tra kết nối dịch vụ Cloudflare Anycast</div>
            </div>
          </div>
          <button id="toggleBtn" onclick="toggleWarp()" class="btn btn-primary">
            <span id="btnIcon">⚡</span> <span id="btnText">Ngắt kết nối</span>
          </button>
        </div>

        <div class="stats-row" style="grid-template-columns: repeat(4, 1fr);">
          <div class="stat-box">
            <div class="stat-label">Trạm Anycast PoP</div>
            <div id="coloValue" class="stat-value">--</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Cổng SOCKS5 Local</div>
            <div id="portValue" class="stat-value">127.0.0.1:40000</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Egress IP Public</div>
            <div id="ipValue" class="stat-value" style="font-size: 13px;">--</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Chế độ Proxy</div>
            <div class="stat-value" style="color: var(--success); font-size: 13px;">SOCKS5 (Safe for SSH)</div>
          </div>
        </div>
      </div>

      <!-- Quick Action Cards (4 x col-3) -->
      <div class="card col-3 metric-card">
        <div>
          <div class="metric-header">
            <span class="metric-title">🐳 Docker Proxy</span>
            <span id="ovDockerBadge" class="badge-status inactive">○ Đang kiểm tra...</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 14px 0; line-height: 1.5;">
            Cấu hình daemon proxy, reload daemon không gián đoạn, và chạy lệnh docker build trực tiếp.
          </p>
        </div>
        <button onclick="switchTab('docker')" class="btn btn-primary btn-sm" style="width: 100%;">
          Docker Console ➔
        </button>
      </div>

      <div class="card col-3 metric-card">
        <div>
          <div class="metric-header">
            <span class="metric-title">🏡 Proxy Dân Cư</span>
            <span id="ovResProxyBadge" class="badge-status inactive">○ Đang kiểm tra...</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 14px 0; line-height: 1.5;">
            Kết nối upstream proxy dân cư / private IP sạch, tốc độ tải vượt trội và chống chặn.
          </p>
        </div>
        <button onclick="switchTab('residential')" class="btn btn-secondary btn-sm" style="width: 100%;">
          Proxy Dân Cư ➔
        </button>
      </div>

      <div class="card col-3 metric-card">
        <div>
          <div class="metric-header">
            <span class="metric-title">🐙 Git & GitLab CLI</span>
            <span id="ovGitBadge" class="badge-status inactive">○ Đang kiểm tra...</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 14px 0; line-height: 1.5;">
            Chỉ định tuyến riêng git clone/push của GitHub & GitLab đi qua Proxy, không ảnh hưởng Git nội bộ.
          </p>
        </div>
        <button onclick="switchTab('routing')" class="btn btn-secondary btn-sm" style="width: 100%;">
          Cấu hình Git ➔
        </button>
      </div>

      <div class="card col-3 metric-card">
        <div>
          <div class="metric-header">
            <span class="metric-title">⚡ Đo Tốc Độ Mạng</span>
            <span class="badge-status active">8 Trạm Toàn Cầu</span>
          </div>
          <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 14px 0; line-height: 1.5;">
            Kiểm tra băng thông và độ trễ đến Singapore, Nhật Bản, Đức, Mỹ, Anh, Phần Lan.
          </p>
        </div>
        <button onclick="switchTab('speedtest')" class="btn btn-secondary btn-sm" style="width: 100%;">
          Kiểm tra tốc độ ➔
        </button>
      </div>

      <!-- Quick Commands Card (col-12) -->
      <div class="card col-12">
        <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 12px;">📌 Lệnh Dòng Lệnh Nhanh (Terminal CheatSheet)</h3>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;">
          <div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">Kiểm tra đường truyền cURL qua SOCKS5:</div>
            <div class="code-snippet">
              <code id="quickCurlCmd">curl --socks5-hostname 127.0.0.1:40000 https://cloudflare.com/cdn-cgi/trace</code>
              <button onclick="copyToClipboard(document.getElementById('quickCurlCmd').innerText)" class="btn btn-secondary btn-sm">Copy</button>
            </div>
          </div>
          <div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">Bật proxy tạm thời cho phiên Terminal / CI-CD:</div>
            <div class="code-snippet">
              <code id="quickExportCmd">export all_proxy="socks5://127.0.0.1:40000"</code>
              <button onclick="copyToClipboard(document.getElementById('quickExportCmd').innerText)" class="btn btn-secondary btn-sm">Copy</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 2: ĐO KIỂM TỐC ĐỘ -->
  <div class="tab-pane" id="tab-speedtest">
    <div class="dashboard-grid">
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; flex-wrap: wrap; gap: 12px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 6px 0;">⚡ Đo Kiểm Tốc Độ Mạng Đa Quốc Gia Qua WARP SOCKS5</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
              Đo kiểm tốc độ tải thực tế và độ trễ từ máy chủ của bạn đến các trạm Cloud Data Center lớn trên thế giới.
            </p>
          </div>
          <div class="badge-mode" style="background: rgba(249, 115, 22, 0.12); border-color: rgba(249, 115, 22, 0.3); color: var(--accent);">
            <span>8 Trạm Anycast Quốc Tế</span>
          </div>
        </div>

        <div style="background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 14px; padding: 18px; margin-bottom: 20px;">
          <div style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 260px;">
              <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 6px;">Chọn Data Center muốn đo kiểm:</label>
              <select id="regionSelect" class="select-style" style="font-size: 13px; padding: 10px 14px;">
                <option value="SG_SIN">🇸🇬 Singapore (Hetzner DC)</option>
                <option value="JP_TYO">🇯🇵 Nhật Bản (Tokyo, Linode)</option>
                <option value="DE_FSN" selected>🇩🇪 Đức (Falkenstein, Hetzner)</option>
                <option value="DE_NBG">🇩🇪 Đức (Nuremberg, Hetzner)</option>
                <option value="US_ASH">🇺🇸 Mỹ - Bờ Đông (Ashburn, Hetzner)</option>
                <option value="US_HIL">🇺🇸 Mỹ - Bờ Tây (Hillsboro, Hetzner)</option>
                <option value="UK_LON">🇬🇧 Anh Quốc (London, Linode)</option>
                <option value="FI_HEL">🇫🇮 Phần Lan (Helsinki, Hetzner)</option>
                <option value="ALL">🚀 Đo TOÀN BỘ các Data Center (Benchmark All)</option>
              </select>
            </div>
            <div style="align-self: flex-end;">
              <button onclick="runSpeedTest()" id="testSpeedBtn" class="btn btn-primary" style="padding: 10px 24px; font-size: 14px;">
                ▶ Bắt đầu kiểm tra tốc độ
              </button>
            </div>
          </div>

          <div class="quick-chips">
            <span style="font-size: 12px; color: var(--text-muted); align-self: center; margin-right: 4px;">Chọn nhanh:</span>
            <button type="button" onclick="selectAndRunSpeed('SG_SIN')" class="chip-btn">🇸🇬 Singapore</button>
            <button type="button" onclick="selectAndRunSpeed('JP_TYO')" class="chip-btn">🇯🇵 Nhật Bản</button>
            <button type="button" onclick="selectAndRunSpeed('DE_FSN')" class="chip-btn">🇩🇪 Đức (FSN)</button>
            <button type="button" onclick="selectAndRunSpeed('US_ASH')" class="chip-btn">🇺🇸 Mỹ (Ashburn)</button>
            <button type="button" onclick="selectAndRunSpeed('ALL')" class="chip-btn" style="background: rgba(249, 115, 22, 0.15); border-color: rgba(249, 115, 22, 0.4); color: #fdba74;">🚀 Benchmark All</button>
          </div>
        </div>

        <!-- Single Result Box -->
        <div id="singleResultBox" style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 14px; padding: 24px; text-align: center;">
          <div class="speed-gauge">
            <div id="speedResult" class="speed-number" style="font-size: 48px;">--</div>
            <div id="speedUnit" style="font-size: 14px; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">MB/s</div>
          </div>
          <div id="speedDetail" style="font-size: 13px; color: var(--text-muted); margin-top: 6px;">
            Chọn trạm kiểm tra và bấm "Bắt đầu kiểm tra tốc độ"
          </div>
        </div>

        <!-- All Results Table Box -->
        <div id="allResultsBox" style="display: none; background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 14px; padding: 20px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
            <h4 style="font-size: 15px; font-weight: 700; margin: 0;">Bảng Tổng Hợp Benchmark 8 Data Center Quốc Tế</h4>
            <span style="font-size: 12px; color: var(--text-muted);">Đường truyền: Cloudflare WARP SOCKS5</span>
          </div>
          <div style="overflow-x: auto;">
            <table class="benchmark-table">
              <thead>
                <tr>
                  <th>Data Center</th>
                  <th>Tốc độ tải</th>
                  <th>Độ trễ (Ping)</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody id="allResultsTbody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 3: ĐIỀU HƯỚNG PROXY -->
  <div class="tab-pane" id="tab-routing">
    <div class="dashboard-grid">
      <!-- Smart Routing Card (col-12) -->
      <div class="card col-12">
        <h3 style="font-size: 17px; font-weight: 700; margin-bottom: 6px;">🔀 Cấu hình Điều hướng Thông minh (Smart Routing)</h3>
        <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 18px;">
          Chỉ định tuyến riêng các ứng dụng và dịch vụ chỉ định đi qua WARP SOCKS5 mà không làm ảnh hưởng hay làm chậm lưu lượng nội bộ của máy chủ.
        </p>

        <div class="control-item">
          <div class="control-info">
            <h4>Proxy cho Docker Daemon (Kèm NO_PROXY Docker Hub)</h4>
            <p>Tự động cấu hình daemon để kéo các registry quốc tế (ghcr.io, quay.io, gcr.io) qua WARP, giữ nguyên tốc độ kéo trực tiếp Docker Hub (~200 Mbps). <a href="javascript:void(0)" onclick="switchTab('docker')" style="color:var(--accent); text-decoration:none; font-weight:600;">Mở Tab Docker & Build Console ➔</a></p>
          </div>
          <label class="switch">
            <input type="checkbox" id="dockerSwitch" onchange="toggleDockerProxy()">
            <span class="slider"></span>
          </label>
        </div>

        <div class="control-item">
          <div class="control-info">
            <h4>Tăng tốc Git CLI cho GitHub (https://github.com/)</h4>
            <p>Chỉ định tuyến riêng git clone/push/fetch của GitHub đi qua WARP SOCKS5, không ảnh hưởng Git nội bộ.</p>
          </div>
          <label class="switch">
            <input type="checkbox" id="gitSwitch" onchange="toggleGitProxy()">
            <span class="slider"></span>
          </label>
        </div>

        <div class="control-item">
          <div class="control-info">
            <h4>Tăng tốc Git CLI cho GitLab (https://gitlab.com/)</h4>
            <p>Chỉ định tuyến riêng git clone/fetch của GitLab quốc tế qua WARP SOCKS5.</p>
          </div>
          <label class="switch">
            <input type="checkbox" id="gitlabSwitch" onchange="toggleGitLabProxy()">
            <span class="slider"></span>
          </label>
        </div>
      </div>

      <!-- SOCKS5 Port Changer (col-6) -->
      <div class="card col-6">
        <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 8px;">⚙️ Đổi Cổng SOCKS5 Proxy</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
          Mặc định là <strong>40000</strong>. Bạn có thể đổi sang bất kỳ cổng nào từ 1024 đến 65535 nếu máy chủ bị xung đột cổng.
        </p>
        <div style="display: flex; gap: 10px; align-items: center;">
          <input type="number" id="customPortInput" class="input-style" style="width: 140px; font-family: 'JetBrains Mono', monospace;" value="40000" min="1024" max="65535">
          <button onclick="saveCustomPort()" class="btn btn-primary btn-sm">Lưu cổng mới</button>
        </div>
      </div>

      <!-- Privoxy Forwarder Info (col-6) -->
      <div class="card col-6">
        <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 8px;">🌐 Hỗ trợ Ứng dụng Chỉ Nhận HTTP Proxy</h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 10px;">
          Nếu ứng dụng của bạn chỉ hỗ trợ HTTP/HTTPS proxy mà không hỗ trợ SOCKS5, bạn có thể kết hợp với <strong>Privoxy</strong> để chuyển đổi:
        </p>
        <div class="code-snippet">
          <code style="font-size: 11px;">forward-socks5 .github.com 127.0.0.1:40000 .</code>
          <button onclick="copyToClipboard('forward-socks5 .github.com 127.0.0.1:40000 .\nforward-socks5 .gitlab.com 127.0.0.1:40000 .')" class="btn btn-secondary btn-sm">Copy</button>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB: DOCKER PROXY & BUILD CONSOLE -->
  <div class="tab-pane" id="tab-docker">
    <div class="dashboard-grid">

      <!-- Daemon Proxy Configuration Card (col-12) -->
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 6px 0;">🐳 Quản Lý Proxy Docker Daemon & Systemd Reload</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
              Cấu hình dịch vụ Docker Daemon đi qua Cloudflare WARP SOCKS5 để kéo base images từ GitHub Packages, Quay.io, GCR, Docker Hub không bị timeout.
            </p>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button onclick="fetchDockerStatus(true)" class="btn btn-secondary btn-sm" title="Làm mới trạng thái Docker">
              🔄 Làm Mới
            </button>
            <button onclick="reloadDockerProxy(true)" class="btn btn-primary btn-sm" id="btnApplyDockerProxy">
              ⚡ Áp Dụng & Reload Daemon
            </button>
            <button onclick="reloadDockerProxy(false)" class="btn btn-danger btn-sm" id="btnDisableDockerProxy">
              🛑 Tắt Proxy Docker
            </button>
          </div>
        </div>

        <!-- Docker Daemon Status Indicators -->
        <div class="stats-row" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 18px;">
          <div class="stat-box">
            <div class="stat-label">Trạng thái Daemon</div>
            <div id="dockerDaemonStatus" class="stat-value" style="color: var(--success); font-size: 14px;">Đang kiểm tra...</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Phiên bản Docker</div>
            <div id="dockerVersionValue" class="stat-value" style="font-size: 14px;">--</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">HTTP/HTTPS Proxy Daemon</div>
            <div id="dockerProxyValue" class="stat-value" style="font-size: 12px; color: var(--accent);">--</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">File Cấu hình Systemd</div>
            <div id="dockerConfStatus" class="stat-value" style="font-size: 12px;">--</div>
          </div>
        </div>

        <!-- NO_PROXY Configuration & Presets -->
        <div style="background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 12px; padding: 16px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
            <label style="font-size: 13px; font-weight: 600; color: var(--text);">
              Danh sách NO_PROXY (Không định tuyến qua WARP):
            </label>
            <div class="quick-chips" style="margin-top: 0;">
              <span style="font-size: 11px; color: var(--text-muted); align-self: center; margin-right: 4px;">Preset:</span>
              <button type="button" class="chip-btn" onclick="setDockerNoProxyPreset('default')">Khuyên dùng (Docker Hub + Mạng nội bộ)</button>
              <button type="button" class="chip-btn" onclick="setDockerNoProxyPreset('minimal')">Tất cả qua WARP</button>
              <button type="button" class="chip-btn" onclick="setDockerNoProxyPreset('cluster')">Kubernetes / Mạng nội bộ</button>
            </div>
          </div>
          <textarea id="dockerNoProxyInput" class="input-style" rows="2" style="font-family: 'JetBrains Mono', monospace; font-size: 12px; resize: vertical;" placeholder="localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24"></textarea>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">
            💡 <strong>Mẹo:</strong> Docker Hub tải trực tiếp tại máy chủ trong nước thường đạt tốc độ rất cao (~200 Mbps). Khuyến nghị giữ <code>docker.io,*.docker.io</code> trong NO_PROXY để kéo Docker Hub trực tiếp, các registry quốc tế khác tự động đi qua WARP.
          </div>
        </div>

        <!-- Raw Config preview -->
        <div class="code-snippet" style="margin-top: 8px;">
          <code id="dockerRawConfView" style="font-size: 11px;"># Chưa nạp thông tin cấu hình systemd</code>
          <button onclick="copyToClipboard(document.getElementById('dockerRawConfView').innerText)" class="btn btn-secondary btn-sm">Copy Systemd Conf</button>
        </div>
      </div>

      <!-- Docker Build Direct Execution Card (col-12) -->
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 6px 0;">🚀 Trình Thực Thi Lệnh Docker Build Trực Tiếp Trên Web UI</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
              Thử nghiệm và thực thi lệnh <code>docker build</code> với tham số Proxy WARP (<code>--network host</code>, <code>--build-arg HTTP_PROXY=socks5://127.0.0.1:40000</code>) ngay trên giao diện web.
            </p>
          </div>
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button onclick="runDockerBuild()" class="btn btn-primary" id="btnRunDockerBuild">
              <span id="buildSpinner" style="display: none;">⏳</span> <span>🚀 Bắt Đầu Build</span>
            </button>
            <button onclick="cleanupDockerImage()" class="btn btn-danger btn-sm" id="btnCleanupDockerImage" title="Xóa image vừa build để giải phóng dung lượng đĩa">
              🗑️ Dọn Image
            </button>
            <button onclick="clearDockerConsole()" class="btn btn-secondary btn-sm">
              🧹 Xóa Console
            </button>
          </div>
        </div>

        <!-- Directory / Project Dockerfile Discovery Section -->
        <div style="background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 14px 16px; margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 16px;">📂</span>
              <strong style="font-size: 13px; color: #fff;">Quét & Chọn Thư Mục Dự Án Chứa Dockerfile</strong>
              <span id="scanCountBadge" class="badge-status inactive" style="font-size: 11px;">Chưa quét</span>
            </div>
            <div class="quick-chips" style="margin-top: 0;">
              <span style="font-size: 11px; color: var(--text-muted); align-self: center;">Đường dẫn mẫu:</span>
              <button type="button" class="chip-btn" onclick="setScanPath('/root')">📁 /root</button>
              <button type="button" class="chip-btn" onclick="setScanPath('/home')">📁 /home</button>
              <button type="button" class="chip-btn" onclick="setScanPath('/var/www')">📁 /var/www</button>
              <button type="button" class="chip-btn" onclick="setScanPath('/root/linux-cloudflare-warp')">📁 Thư mục hiện tại</button>
            </div>
          </div>

          <!-- Scan Path Input & Scan Button -->
          <div style="display: grid; grid-template-columns: 1fr auto; gap: 10px; margin-bottom: 10px;">
            <input type="text" id="dockerScanPath" class="input-style" value="/root" placeholder="Nhập đường dẫn thư mục cần quét trên server (VD: /root hoặc /home/user)" style="font-family: 'JetBrains Mono', monospace; font-size: 12px;" />
            <button type="button" onclick="scanDockerDirectory()" class="btn btn-secondary btn-sm" id="btnScanDockerDir" style="white-space: nowrap; height: 38px;">
              <span id="scanSpinner" style="display: none;">⏳</span> <span>🔍 Quét Thư Mục</span>
            </button>
          </div>

          <!-- Discovered Dockerfiles Dropdown & Action Buttons -->
          <div style="display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center;">
            <select id="discoveredDockerfilesSelect" class="select-style" onchange="onDiscoveredDockerfileChange()" style="font-family: 'JetBrains Mono', monospace; font-size: 12px; height: 38px;">
              <option value="">-- Danh sách Dockerfile tìm thấy trên server (Nhấn '🔍 Quét Thư Mục') --</option>
            </select>
            <button type="button" onclick="loadSelectedDiscoveredDockerfile()" class="btn btn-primary btn-sm" id="btnLoadSelectedDf" style="white-space: nowrap; height: 38px;" title="Tải nội dung Dockerfile vào trình soạn thảo và đặt thư mục làm Context">
              📂 Nạp Vào Editor & Context
            </button>
            <button type="button" onclick="clearBuildContext()" class="btn btn-secondary btn-sm" style="white-space: nowrap; height: 38px;" title="Hủy chọn thư mục context, chuyển về chế độ build độc lập">
              ✕ Bỏ Chọn Context
            </button>
          </div>

          <!-- Active Build Context Banner -->
          <div id="buildContextBanner" style="margin-top: 10px; padding: 10px 14px; background: rgba(0, 210, 255, 0.08); border: 1px solid rgba(0, 210, 255, 0.2); border-radius: 8px; font-size: 12px; display: none; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span style="color: var(--accent); font-weight: 700;">🏗️ Thư mục Build Context:</span>
              <code id="activeContextDirText" style="color: #fff; font-weight: 700; background: rgba(0,0,0,0.4); padding: 2px 8px; border-radius: 4px;">--</code>
              <span id="activeDockerfileFileText" style="color: var(--text-muted); font-size: 11px;">(File: --)</span>
            </div>
            <span style="font-size: 11px; color: #6ee7b7; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.25); padding: 3px 10px; border-radius: 6px; font-weight: 600;">
              ✓ Các lệnh COPY / ADD cục bộ sẽ lấy từ thư mục này
            </span>
          </div>
        </div>

        <!-- Presets and Build Config Row -->
        <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 14px; margin-bottom: 14px;">
          <div>
            <label style="font-size: 12px; font-weight: 600; color: var(--text-muted); display: block; margin-bottom: 6px;">
              Mẫu Dockerfile có sẵn (Nhấp để chọn mẫu thử nghiệm nhanh):
            </label>
            <div class="quick-chips" style="margin-top: 0;">
              <button type="button" class="chip-btn" onclick="loadDockerfileTemplate('alpine')">🏔️ Alpine + cURL</button>
              <button type="button" class="chip-btn" onclick="loadDockerfileTemplate('python')">🐍 Python + Pip Packages</button>
              <button type="button" class="chip-btn" onclick="loadDockerfileTemplate('node')">🟩 Node.js + NPM Express</button>
              <button type="button" class="chip-btn" onclick="loadDockerfileTemplate('git')">🐙 Git Clone Repo Test</button>
              <button type="button" class="chip-btn" onclick="loadDockerfileTemplate('custom')">✏️ Tùy chỉnh trống</button>
            </div>
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 600; color: var(--text-muted); display: block; margin-bottom: 6px;">
              Tag Name Image:
            </label>
            <input type="text" id="dockerBuildTag" class="input-style" value="warp-build-test:latest" style="font-family: 'JetBrains Mono', monospace; font-size: 12px;" />
          </div>
        </div>

        <!-- Build Options Checkboxes -->
        <div style="display: flex; gap: 14px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; background: rgba(255, 255, 255, 0.02); padding: 10px 14px; border-radius: 10px; border: 1px solid rgba(255, 255, 255, 0.05);">
          <div style="display: flex; align-items: center; gap: 8px;">
            <label style="font-size: 12px; font-weight: 600; color: var(--text);">Nguồn Proxy:</label>
            <select id="dockerBuildProxySource" class="select-style" style="width: auto; padding: 4px 8px; font-size: 12px;">
              <option value="warp">⚡ Cloudflare WARP (127.0.0.1:40000)</option>
              <option value="residential">🏡 Proxy Dân Cư (Residential)</option>
            </select>
          </div>
          <label style="font-size: 12px; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="chkInjectProxy" checked>
            <span>Inject build-arg Proxy</span>
          </label>
          <label style="font-size: 12px; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="chkNetworkHost" checked>
            <span>Sử dụng <code>--network host</code></span>
          </label>
          <label style="font-size: 12px; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="chkNoCache" checked>
            <span>Sử dụng <code>--no-cache</code></span>
          </label>
          <label style="font-size: 12px; display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input type="checkbox" id="chkAutoCleanup">
            <span>Tự động dọn dẹp image</span>
          </label>
        </div>

        <!-- Dockerfile Editor Area -->
        <div style="margin-bottom: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <label style="font-size: 12px; font-weight: 600; color: var(--text-muted);">
              Nội dung Dockerfile:
            </label>
            <span style="font-size: 11px; color: var(--text-muted);">Hỗ trợ đầy đủ lệnh BuildKit</span>
          </div>
          <textarea id="dockerfileEditor" class="input-style" rows="7" style="font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; tab-size: 2; resize: vertical;" spellcheck="false"></textarea>
        </div>

        <!-- Live Terminal Console Log -->
        <div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <div style="font-size: 12px; font-weight: 600; color: var(--text-muted); display: flex; align-items: center; gap: 8px;">
              <span>📺 Live Terminal Console Output:</span>
              <span id="buildStatusBadge" class="badge-status inactive">○ Chờ lệnh build</span>
            </div>
            <div id="buildMetrics" style="font-size: 11px; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">
              --
            </div>
          </div>
          <div id="dockerBuildConsole" class="terminal-box" style="min-height: 220px; max-height: 380px;">
[Sẵn sàng] Hãy chọn một mẫu Dockerfile hoặc soạn thảo nội dung của bạn ở trên, sau đó nhấn "🚀 Bắt Đầu Build".
          </div>
        </div>

      </div>

    </div>
  </div>

  <!-- TAB: PROXY DÂN CƯ (RESIDENTIAL PROXY) -->
  <div class="tab-pane" id="tab-residential">
    <div class="dashboard-grid">

      <!-- Active Egress Control Card (col-12) -->
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 14px;">
          <div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 6px;">
              <h3 style="font-size: 18px; font-weight: 700; margin: 0;">🏡 Quản Lý Kết Nối Proxy Dân Cư (Residential / Clean ISP IP)</h3>
              <span id="resActiveBadge" class="badge-status active">● Đang dùng WARP</span>
            </div>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
              Kết nối đến máy chủ Proxy Dân Cư (IP sạch, băng thông cao, không bị chặn CAPTCHA) để tăng tốc tải mã nguồn, build container hoặc crawl dữ liệu.
            </p>
          </div>
          <div style="display: flex; gap: 10px; flex-wrap: wrap;">
            <button onclick="applyResidentialProxy('all')" class="btn btn-primary btn-sm" id="btnActivateResidential" title="Chuyển toàn bộ Docker và Git sang dùng Proxy Dân Cư">
              ⚡ Kích Hoạt Proxy Dân Cư (Docker + Git)
            </button>
            <button onclick="switchBackToWarp()" class="btn btn-secondary btn-sm" id="btnSwitchToWarp" title="Khôi phục lại Cloudflare WARP Anycast">
              🛡️ Khôi Phục Về Cloudflare WARP
            </button>
          </div>
        </div>

        <!-- Quick Summary Row -->
        <div class="stats-row" style="grid-template-columns: repeat(4, 1fr); margin-top: 18px;">
          <div class="stat-box">
            <div class="stat-label">Nguồn Egress Hoạt Động</div>
            <div id="resCurrentEgress" class="stat-value" style="color: var(--accent); font-size: 13px;">Cloudflare WARP Anycast</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Địa Chỉ Proxy Dân Cư</div>
            <div id="resMaskedUrl" class="stat-value" style="font-size: 13px;">Chưa cấu hình</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Nhà Mạng / ISP Egress</div>
            <div id="resIspValue" class="stat-value" style="font-size: 13px;">--</div>
          </div>
          <div class="stat-box">
            <div class="stat-label">Tốc Độ Đo Gần Nhất</div>
            <div id="resSpeedValue" class="stat-value" style="font-size: 13px; color: var(--success);">--</div>
          </div>
        </div>
      </div>

      <!-- Config Form Card (col-7) -->
      <div class="card col-7">
        <h4 style="font-size: 15px; font-weight: 700; margin-bottom: 6px;">⚙️ Thông Tin Kết Nối Proxy Dân Cư</h4>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
          Hỗ trợ nhập trực tiếp hoặc dán chuỗi proxy từ các nhà cung cấp (BrightData, Oxylabs, Smartproxy, Webshare, IPRoyal, Proxy-Seller,...).
        </p>

        <!-- Quick Auto-Parse Box -->
        <div style="background: rgba(0, 0, 0, 0.3); border: 1px dashed rgba(255, 255, 255, 0.15); border-radius: 10px; padding: 12px; margin-bottom: 16px;">
          <label style="font-size: 12px; font-weight: 600; color: var(--accent); display: block; margin-bottom: 6px;">
            📋 Nhập nhanh chuỗi Proxy (Tự động bóc tách):
          </label>
          <div style="display: flex; gap: 8px;">
            <input type="text" id="resQuickInput" class="input-style" placeholder="VD: 103.186.x.x:8080:username:password hoặc user:pass@host:port" style="font-family: 'JetBrains Mono', monospace; font-size: 12px;" />
            <button type="button" onclick="autoParseProxyInput()" class="btn btn-primary btn-sm" style="white-space: nowrap;">
              ⚡ Phân Tích
            </button>
          </div>
          <div style="font-size: 11px; color: var(--text-muted); margin-top: 5px;">
            Hỗ trợ định dạng: <code>IP:PORT:USER:PASS</code>, <code>USER:PASS@HOST:PORT</code>, hoặc URL <code>socks5://...</code>
          </div>
        </div>

        <!-- Detail Form -->
        <div style="display: grid; grid-template-columns: 1fr 2fr 1fr; gap: 10px; margin-bottom: 12px;">
          <div>
            <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Giao thức</label>
            <select id="resProto" class="select-style">
              <option value="socks5">SOCKS5 (Khuyên dùng)</option>
              <option value="http">HTTP</option>
              <option value="https">HTTPS</option>
            </select>
          </div>
          <div>
            <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Host / IP Máy Chủ Proxy</label>
            <input type="text" id="resHost" class="input-style" placeholder="VD: res.proxyprovider.com hoặc 103.x.x.x" style="font-family: 'JetBrains Mono';" />
          </div>
          <div>
            <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Port</label>
            <input type="number" id="resPort" class="input-style" placeholder="1080" value="1080" style="font-family: 'JetBrains Mono';" />
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px;">
          <div>
            <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Tài khoản (Username - Tùy chọn)</label>
            <input type="text" id="resUser" class="input-style" placeholder="Để trống nếu IP Whitelist" />
          </div>
          <div>
            <label style="font-size: 12px; color: var(--text-muted); display: block; margin-bottom: 4px;">Mật khẩu (Password - Tùy chọn)</label>
            <input type="password" id="resPass" class="input-style" placeholder="Nhập mật khẩu proxy" />
          </div>
        </div>

        <!-- NO_PROXY Input -->
        <div style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <label style="font-size: 12px; color: var(--text-muted);">Danh sách NO_PROXY (Không qua proxy dân cư):</label>
            <div class="quick-chips" style="margin-top:0;">
              <button type="button" class="chip-btn" onclick="document.getElementById('resNoProxy').value='localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24';">Khuyên dùng</button>
              <button type="button" class="chip-btn" onclick="document.getElementById('resNoProxy').value='localhost,127.0.0.1';">Tối thiểu</button>
            </div>
          </div>
          <input type="text" id="resNoProxy" class="input-style" value="localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24" style="font-family: 'JetBrains Mono'; font-size: 11px;" />
        </div>

        <!-- Form Buttons -->
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">
          <button onclick="saveResidentialProxy()" class="btn btn-primary btn-sm" id="btnSaveResProxy">
            💾 Lưu Cấu Hình
          </button>
          <button onclick="testResidentialProxy()" class="btn btn-secondary btn-sm" id="btnTestResProxy">
            <span id="resTestSpinner" style="display: none;">⏳</span> <span>🔍 Kiểm Tra Kết Nối & Đo Tốc Độ</span>
          </button>
          <button onclick="applyResidentialProxy('docker')" class="btn btn-secondary btn-sm" title="Chỉ áp dụng riêng cho Docker Daemon">
            🐳 Áp Dụng Docker
          </button>
          <button onclick="applyResidentialProxy('git')" class="btn btn-secondary btn-sm" title="Chỉ áp dụng riêng cho GitHub/GitLab">
            🐙 Áp Dụng Git
          </button>
        </div>
      </div>

      <!-- Test Result & Diagnostics Card (col-5) -->
      <div class="card col-5">
        <h4 style="font-size: 15px; font-weight: 700; margin-bottom: 6px;">📊 Kết Quả Kiểm Tra Proxy</h4>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 14px;">
          Thông tin Egress IP thực tế, nhà mạng ISP, độ trễ và băng thông tải xuống khi qua proxy dân cư.
        </p>

        <div id="resTestResultBox" style="background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 16px; min-height: 220px; display: flex; flex-direction: column; justify-content: center;">
          <div id="resTestWaiting" style="text-align: center; color: var(--text-muted); font-size: 13px;">
            <div style="font-size: 32px; margin-bottom: 8px;">🏡</div>
            Nhấn <strong>"🔍 Kiểm Tra Kết Nối & Đo Tốc Độ"</strong> để đo kiểm thông số thực tế của Proxy Dân Cư.
          </div>

          <div id="resTestDetails" style="display: none;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); padding-bottom: 8px;">
              <span style="font-size: 12px; color: var(--text-muted);">Trạng thái kết nối:</span>
              <span id="resDiagBadge" class="badge-status active">✓ Kết nối thành công</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px;">
              <span style="color: var(--text-muted);">Egress IP Public:</span>
              <strong id="resDiagIp" style="font-family: 'JetBrains Mono'; color: var(--accent);">--</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px;">
              <span style="color: var(--text-muted);">Nhà mạng (ISP):</span>
              <strong id="resDiagIsp">--</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px;">
              <span style="color: var(--text-muted);">Vị trí / Quốc gia:</span>
              <strong id="resDiagLocation">--</strong>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 12px;">
              <span style="color: var(--text-muted);">Độ trễ TTFB (Ping):</span>
              <strong id="resDiagLatency" style="font-family: 'JetBrains Mono'; color: #6ee7b7;">-- ms</strong>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.2); padding: 8px 12px; border-radius: 8px;">
              <span style="font-size: 12px; color: #6ee7b7; font-weight: 600;">Tốc độ tải đo được:</span>
              <span id="resDiagSpeed" style="font-family: 'JetBrains Mono'; font-size: 16px; font-weight: 800; color: #6ee7b7;">-- MB/s</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Quick Commands CheatSheet (col-12) -->
      <div class="card col-12">
        <h4 style="font-size: 15px; font-weight: 700; margin-bottom: 10px;">📌 Lệnh Dòng Lệnh Nhanh Cho Proxy Dân Cư</h4>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px;">
          <div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">Lệnh cURL kiểm tra Egress IP qua Proxy Dân Cư:</div>
            <div class="code-snippet">
              <code id="resCurlSnippet">curl -x "socks5://user:pass@host:port" https://cloudflare.com/cdn-cgi/trace</code>
              <button onclick="copyToClipboard(document.getElementById('resCurlSnippet').innerText)" class="btn btn-secondary btn-sm">Copy</button>
            </div>
          </div>
          <div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 6px;">Biến môi trường Terminal / CI-CD Pipeline:</div>
            <div class="code-snippet">
              <code id="resExportSnippet">export all_proxy="socks5://user:pass@host:port"</code>
              <button onclick="copyToClipboard(document.getElementById('resExportSnippet').innerText)" class="btn btn-secondary btn-sm">Copy</button>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- TAB 4: GITLAB CI/CD -->
  <div class="tab-pane" id="tab-gitlab">
    <div class="dashboard-grid">
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 6px 0;">🦊 Tăng Tốc GitLab CI/CD Pipeline & GitLab Runner</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
              Khắc phục triệt để tình trạng kéo code từ gitlab.com bị treo, kéo container images hoặc tải dependencies (NPM, PyPI, Go) trong pipeline bị chậm.
            </p>
          </div>
          <span style="font-size: 12px; color: var(--accent); font-weight: 600; background: rgba(249, 115, 22, 0.1); padding: 6px 12px; border-radius: 8px; border: 1px solid rgba(249, 115, 22, 0.2);">
            Proxy Endpoint: 127.0.0.1:40000
          </span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; margin-top: 16px;">
          <div style="background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 14px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <h4 style="font-size: 14px; font-weight: 700; color: #fff; margin: 0;">1. Cấu hình cho .gitlab-ci.yml</h4>
              <button onclick="copyToClipboard('variables:\n  ALL_PROXY: \x22socks5://127.0.0.1:40000\x22\n  NO_PROXY: \x22localhost,127.0.0.1,docker.io,*.docker.com\x22')" class="btn btn-secondary btn-sm">Copy YAML</button>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 10px 0;">Thêm khối variables vào đầu file để áp dụng cho mọi stage/job:</p>
            <div class="code-snippet" style="flex-direction: column; align-items: stretch; gap: 8px; margin: 0;">
              <code style="white-space: pre; font-size: 12px; line-height: 1.6;">variables:
  ALL_PROXY: "socks5://127.0.0.1:40000"
  HTTP_PROXY: "socks5://127.0.0.1:40000"
  HTTPS_PROXY: "socks5://127.0.0.1:40000"
  NO_PROXY: "localhost,127.0.0.1,docker.io,*.docker.com"</code>
            </div>
          </div>

          <div style="background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 14px; padding: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
              <h4 style="font-size: 14px; font-weight: 700; color: #fff; margin: 0;">2. Cấu hình cho config.toml của Runner</h4>
              <button onclick="copyToClipboard('[runners.docker]\n  network_mode = \x22host\x22\nenvironment = [\n  \x22ALL_PROXY=socks5://127.0.0.1:40000\x22\n]')" class="btn btn-secondary btn-sm">Copy TOML</button>
            </div>
            <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 10px 0;">Trong <code>/etc/gitlab-runner/config.toml</code> (Bắt buộc dùng network_mode = "host"):</p>
            <div class="code-snippet" style="flex-direction: column; align-items: stretch; gap: 8px; margin: 0;">
              <code style="white-space: pre; font-size: 12px; line-height: 1.6;">[[runners]]
  environment = ["ALL_PROXY=socks5://127.0.0.1:40000"]
  [runners.docker]
    network_mode = "host"</code>
            </div>
          </div>
        </div>

        <div style="background: rgba(249, 115, 22, 0.06); border: 1px solid rgba(249, 115, 22, 0.2); border-radius: 12px; padding: 14px 18px; margin-top: 18px;">
          <div style="font-size: 13px; font-weight: 600; color: #fdba74; margin-bottom: 4px;">💡 File Mẫu Đầy Đủ Có Sẵn Trong Thư Mục Cài Đặt:</div>
          <div style="font-size: 12px; color: var(--text-muted);">
            Bạn có thể tham khảo trực tiếp 2 file mẫu: <strong><code>gitlab-ci.example.yml</code></strong> (tích hợp sẵn cache, Node, Python, Docker) và <strong><code>gitlab-runner.example.toml</code></strong>.
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 5: NHẬT KÝ & CHẨN ĐOÁN -->
  <div class="tab-pane" id="tab-logs">
    <div class="dashboard-grid">
      <div class="card col-12">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
          <div>
            <h3 style="font-size: 17px; font-weight: 700; margin: 0 0 4px 0;">📋 Nhật Ký Dịch Vụ Hệ Thống (warp-svc)</h3>
            <p style="font-size: 13px; color: var(--text-muted); margin: 0;">Xem nhật ký hoạt động thời gian thực của daemon Cloudflare WARP trên máy chủ.</p>
          </div>
          <div style="display: flex; gap: 10px; align-items: center;">
            <label style="font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 6px; cursor: pointer;">
              <input type="checkbox" id="autoLogsCheck" onchange="toggleAutoLogs()"> Tự động làm mới (5s)
            </label>
            <button onclick="loadLogs()" class="btn btn-secondary btn-sm">🔄 Làm mới ngay</button>
          </div>
        </div>
        <div id="logsBox" class="terminal-box" style="max-height: 420px; font-size: 12px; line-height: 1.6;">Đang tải nhật ký hệ thống...</div>
      </div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
  let currentStatus = {};
  let autoLogTimer = null;

  function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));

    const btn = document.getElementById('tabBtn-' + tabId);
    const pane = document.getElementById('tab-' + tabId);

    if (btn) btn.classList.add('active');
    if (pane) pane.classList.add('active');

    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, null, '#' + tabId);
    }

    if (tabId === 'logs') {
      loadLogs();
    }
    if (tabId === 'docker') {
      fetchDockerStatus();
      if (discoveredDockerfiles.length === 0) {
        scanDockerDirectory();
      }
    }
    if (tabId === 'residential') {
      loadResidentialProxy();
    }
  }

  function selectAndRunSpeed(region) {
    document.getElementById('regionSelect').value = region;
    runSpeedTest();
  }

  function toggleAutoLogs() {
    const chk = document.getElementById('autoLogsCheck');
    if (chk && chk.checked) {
      loadLogs();
      if (!autoLogTimer) autoLogTimer = setInterval(loadLogs, 5000);
    } else {
      if (autoLogTimer) {
        clearInterval(autoLogTimer);
        autoLogTimer = null;
      }
    }
  }

  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      const data = await res.json();
      currentStatus = data;
      renderStatus(data);
    } catch (e) {
      console.error(e);
    }
  }

  function renderStatus(data) {
    const isConn = data.connected && data.warp_active;
    const dot = document.getElementById('statusDot');
    const title = document.getElementById('statusText');
    const sub = document.getElementById('statusSub');
    const btn = document.getElementById('toggleBtn');
    const btnText = document.getElementById('btnText');

    if (isConn) {
      dot.className = 'status-pulse';
      title.innerText = 'Đang Kết Nối WARP';
      sub.innerText = `Đường truyền bảo vệ qua Cloudflare Anycast Backbone (warp=on)`;
      btnText.innerText = 'Ngắt kết nối';
      btn.className = 'btn btn-secondary';
    } else {
      dot.className = 'status-pulse disconnected';
      title.innerText = 'Đang Ngắt Kết Nối';
      sub.innerText = 'Toàn bộ lưu lượng đang đi trực tiếp qua mạng thông thường';
      btnText.innerText = 'Bật kết nối';
      btn.className = 'btn btn-primary';
    }

    document.getElementById('coloValue').innerText = data.colo || '--';
    document.getElementById('portValue').innerText = `127.0.0.1:${data.port}`;
    document.getElementById('ipValue').innerText = data.ip || '--';
    document.getElementById('customPortInput').value = data.port;
    document.getElementById('dockerSwitch').checked = data.docker_proxy;
    document.getElementById('gitSwitch').checked = data.git_proxy;
    document.getElementById('gitlabSwitch').checked = data.gitlab_proxy;

    // Cập nhật Docker UI nếu có thông tin docker_info
    if (data.docker_info) {
      updateDockerUI(data.docker_info);
    }

    // Cập nhật badges trên Overview
    const ovDocker = document.getElementById('ovDockerBadge');
    if (ovDocker) {
      ovDocker.className = data.docker_proxy ? 'badge-status active' : 'badge-status inactive';
      ovDocker.innerText = data.docker_proxy ? '● Đang Bật' : '○ Đang Tắt';
    }
    const ovGit = document.getElementById('ovGitBadge');
    if (ovGit) {
      const isAnyGit = data.git_proxy || data.gitlab_proxy;
      ovGit.className = isAnyGit ? 'badge-status active' : 'badge-status inactive';
      ovGit.innerText = isAnyGit ? '● Đang Bật' : '○ Đang Tắt';
    }

    // Cập nhật lệnh cURL & Export trên Overview
    const curlEl = document.getElementById('quickCurlCmd');
    if (curlEl) curlEl.innerText = `curl --socks5-hostname 127.0.0.1:${data.port} https://cloudflare.com/cdn-cgi/trace`;
    const expEl = document.getElementById('quickExportCmd');
    if (expEl) expEl.innerText = `export all_proxy="socks5://127.0.0.1:${data.port}"`;

    // Cập nhật Proxy Dân Cư UI nếu có
    if (data.residential_proxy) {
      updateResidentialProxyUI(data.residential_proxy);
    }
  }

  async function toggleWarp() {
    const isConn = currentStatus.connected;
    const action = isConn ? 'disconnect' : 'connect';
    showToast(isConn ? 'Đang ngắt kết nối...' : 'Đang bật kết nối WARP...');
    try {
      await fetch('/api/' + action, { method: 'POST' });
      setTimeout(fetchStatus, 2000);
      showToast(isConn ? 'Đã ngắt kết nối!' : 'Đã kết nối thành công!');
    } catch (e) {
      showToast('Lỗi khi thao tác: ' + e);
    }
  }

  function updateDockerUI(info) {
    if (!info) return;
    const daemonEl = document.getElementById('dockerDaemonStatus');
    const verEl = document.getElementById('dockerVersionValue');
    const proxyEl = document.getElementById('dockerProxyValue');
    const confEl = document.getElementById('dockerConfStatus');
    const noProxyInput = document.getElementById('dockerNoProxyInput');
    const rawConfView = document.getElementById('dockerRawConfView');

    if (daemonEl) {
      if (info.running) {
        daemonEl.innerText = '● Đang Hoạt Động';
        daemonEl.style.color = 'var(--success)';
      } else if (info.installed) {
        daemonEl.innerText = '○ Đã Dừng';
        daemonEl.style.color = 'var(--danger)';
      } else {
        daemonEl.innerText = '✕ Chưa Cài Đặt';
        daemonEl.style.color = 'var(--text-muted)';
      }
    }
    if (verEl) verEl.innerText = info.version || (info.installed ? 'Đang chạy' : 'Không có');
    if (proxyEl) {
      if (info.http_proxy) {
        proxyEl.innerText = info.http_proxy;
        proxyEl.style.color = 'var(--accent)';
      } else {
        proxyEl.innerText = 'Không có (Trực tiếp)';
        proxyEl.style.color = 'var(--text-muted)';
      }
    }
    if (confEl) {
      confEl.innerText = info.conf_exists ? '● Đã Cài Đặt' : '○ Chưa Tạo';
      confEl.style.color = info.conf_exists ? 'var(--success)' : 'var(--text-muted)';
    }
    if (noProxyInput && !noProxyInput.dataset.userEdited && info.no_proxy) {
      noProxyInput.value = info.no_proxy;
    }
    if (rawConfView) {
      rawConfView.innerText = info.raw_conf || '# Chưa có file cấu hình /etc/systemd/system/docker.service.d/http-proxy.conf';
    }
  }

  async function fetchDockerStatus(showNotification = false) {
    if (showNotification) showToast('Đang kiểm tra trạng thái Docker daemon...');
    try {
      const res = await fetch('/api/docker/status');
      const data = await res.json();
      if (data.success && data.info) {
        updateDockerUI(data.info);
        if (showNotification) showToast('Đã làm mới thông tin Docker thành công!');
      }
    } catch (e) {
      if (showNotification) showToast('Lỗi lấy thông tin Docker: ' + e);
    }
  }

  async function reloadDockerProxy(enable = true) {
    const btn = enable ? document.getElementById('btnApplyDockerProxy') : document.getElementById('btnDisableDockerProxy');
    const origText = btn ? btn.innerText : '';
    if (btn) {
      btn.disabled = true;
      btn.innerText = enable ? 'Đang reload daemon...' : 'Đang tắt proxy...';
    }
    showToast(enable ? 'Đang cấu hình & reload Docker daemon...' : 'Đang tắt proxy Docker & restart daemon...');

    const noProxyInput = document.getElementById('dockerNoProxyInput');
    const noProxyVal = noProxyInput ? noProxyInput.value : '';

    try {
      const res = await fetch('/api/docker/reload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable, no_proxy: noProxyVal })
      });
      const data = await res.json();
      if (data.success) {
        showToast(enable ? 'Reload Docker daemon thành công! Proxy đã hoạt động.' : 'Đã tắt proxy Docker daemon và khôi phục mặc định!');
        if (data.info) updateDockerUI(data.info);
        const switchEl = document.getElementById('dockerSwitch');
        if (switchEl) switchEl.checked = enable;
        setTimeout(fetchStatus, 1000);
      } else {
        showToast('Lỗi: ' + (data.error || 'Không thể reload Docker'));
      }
    } catch (e) {
      showToast('Lỗi kết nối máy chủ: ' + e);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerText = origText;
      }
    }
  }

  function toggleDockerProxy() {
    const enable = document.getElementById('dockerSwitch').checked;
    reloadDockerProxy(enable);
  }

  function setDockerNoProxyPreset(preset) {
    const input = document.getElementById('dockerNoProxyInput');
    if (!input) return;
    input.dataset.userEdited = 'true';
    if (preset === 'default') {
      input.value = 'localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24';
      showToast('Đã chọn Preset Khuyên dùng (Docker Hub kéo trực tiếp, Registry quốc tế qua WARP)');
    } else if (preset === 'minimal') {
      input.value = 'localhost,127.0.0.1';
      showToast('Đã chọn Preset Toàn bộ qua WARP');
    } else if (preset === 'cluster') {
      input.value = 'localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,*.local,*.cluster.local';
      showToast('Đã chọn Preset Kubernetes / Internal LAN');
    }
  }

  const DOCKER_TEMPLATES = {
    alpine: `FROM alpine:latest
# 1. Kiểm tra tải package apk qua Cloudflare WARP SOCKS5
RUN apk update && apk add --no-cache curl ca-certificates
# 2. Kiểm tra IP Egress Anycast của Cloudflare
RUN curl -s --connect-timeout 8 https://cloudflare.com/cdn-cgi/trace
CMD ["sh", "-c", "echo 'Container chạy thành công!'"]`,

    python: `FROM python:3.11-alpine
# Kiểm tra cài đặt Pip packages quốc tế qua WARP
RUN pip install --no-cache-dir requests urllib3
RUN python -c "import requests; print('>>> [WARP-OK] Python requests hoạt động tốt! Egress IP:', requests.get('https://cloudflare.com/cdn-cgi/trace').text.splitlines()[2])"
CMD ["python", "-c", "print('Python Container Ready')"]`,

    node: `FROM node:20-alpine
WORKDIR /app
# Kiểm tra tải npm packages qua WARP Proxy
RUN npm init -y && npm install --no-audit axios
RUN node -e "const axios = require('axios'); axios.get('https://cloudflare.com/cdn-cgi/trace').then(r => console.log('>>> [WARP-OK] Axios trace:\\n' + r.data.split('\\n').slice(0,3).join('\\n')));"
CMD ["node", "-v"]`,

    git: `FROM alpine:latest
RUN apk update && apk add --no-cache git ca-certificates
# Thử nghiệm clone repository quốc tế qua WARP Proxy
RUN git clone --depth 1 https://github.com/Datahub-DC/cloudflare-warp-app.git /tmp/repo
RUN ls -la /tmp/repo
CMD ["ls", "-la", "/tmp/repo"]`,

    custom: `FROM alpine:latest
# Soạn thảo các chỉ thị build của bạn tại đây
RUN echo "Hello from Cloudflare WARP Docker Build!"
`
  };

  function loadDockerfileTemplate(tpl) {
    const editor = document.getElementById('dockerfileEditor');
    if (editor && DOCKER_TEMPLATES[tpl]) {
      editor.value = DOCKER_TEMPLATES[tpl];
      clearBuildContext();
      showToast(`Đã tải mẫu Dockerfile: ${tpl.toUpperCase()} (Chế độ độc lập)`);
    }
  }

  // --- DOCKER DIRECTORY SCAN & CONTEXT SELECTION ---
  let discoveredDockerfiles = [];
  let selectedBuildContextDir = null;
  let selectedDockerfileFile = null;

  function setScanPath(path) {
    const input = document.getElementById('dockerScanPath');
    if (input) {
      input.value = path;
      scanDockerDirectory();
    }
  }

  async function scanDockerDirectory() {
    const pathInput = document.getElementById('dockerScanPath');
    const scanPath = (pathInput ? pathInput.value.trim() : '') || '/root';
    const btn = document.getElementById('btnScanDockerDir');
    const spinner = document.getElementById('scanSpinner');
    const select = document.getElementById('discoveredDockerfilesSelect');
    const badge = document.getElementById('scanCountBadge');

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = 'inline';
    showToast(`Đang quét thư mục '${scanPath}' tìm Dockerfile...`);

    try {
      const res = await fetch('/api/docker/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: scanPath, max_depth: 4 })
      });
      const data = await res.json();
      if (data.success) {
        discoveredDockerfiles = data.dockerfiles || [];
        if (select) {
          select.innerHTML = '';
          const defaultOpt = document.createElement('option');
          defaultOpt.value = '';
          defaultOpt.innerText = `-- Chọn Dockerfile đã tìm thấy (${discoveredDockerfiles.length} tệp) --`;
          select.appendChild(defaultOpt);

          discoveredDockerfiles.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.full_path;
            const sizeKb = Math.round(item.size_bytes / 1024 * 10) / 10;
            opt.innerText = `📦 [${item.dir_name}] ${item.name} (${sizeKb} KB) - ${item.rel_path}`;
            select.appendChild(opt);
          });
        }

        if (badge) {
          badge.className = discoveredDockerfiles.length > 0 ? 'badge-status active' : 'badge-status inactive';
          badge.innerText = discoveredDockerfiles.length > 0 ? `● Tìm thấy ${discoveredDockerfiles.length} Dockerfile` : '○ Không tìm thấy';
        }

        if (discoveredDockerfiles.length > 0) {
          showToast(`Tìm thấy ${discoveredDockerfiles.length} Dockerfile trong '${data.base_path}'!`);
          if (select && !selectedBuildContextDir) {
            select.selectedIndex = 1;
            loadSelectedDiscoveredDockerfile();
          }
        } else {
          showToast(`Không tìm thấy Dockerfile nào trong '${data.base_path}'. Hãy thử thư mục khác!`);
        }
      } else {
        showToast('✕ Lỗi quét: ' + (data.error || 'Thao tác thất bại'));
      }
    } catch (e) {
      showToast('Lỗi kết nối khi quét thư mục: ' + e);
    } finally {
      if (btn) btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  function onDiscoveredDockerfileChange() {
    const select = document.getElementById('discoveredDockerfilesSelect');
    if (select && select.value) {
      loadSelectedDiscoveredDockerfile();
    }
  }

  async function loadSelectedDiscoveredDockerfile() {
    const select = document.getElementById('discoveredDockerfilesSelect');
    if (!select || !select.value) {
      showToast('Vui lòng chọn một Dockerfile từ danh sách tìm thấy!');
      return;
    }
    const filePath = select.value;
    const btn = document.getElementById('btnLoadSelectedDf');
    if (btn) btn.disabled = true;
    showToast('Đang đọc nội dung Dockerfile...');

    try {
      const res = await fetch('/api/docker/read-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath })
      });
      const data = await res.json();
      if (data.success && data.content !== undefined) {
        document.getElementById('dockerfileEditor').value = data.content;
        selectedBuildContextDir = data.dir_path;
        selectedDockerfileFile = data.file_name;

        const banner = document.getElementById('buildContextBanner');
        const ctxText = document.getElementById('activeContextDirText');
        const fileText = document.getElementById('activeDockerfileFileText');
        if (ctxText) ctxText.innerText = data.dir_path;
        if (fileText) fileText.innerText = `(File: ${data.file_name})`;
        if (banner) banner.style.display = 'flex';

        const tagInput = document.getElementById('dockerBuildTag');
        if (tagInput && data.dir_name) {
          tagInput.value = `${data.dir_name}:latest`;
        }

        showToast(`✓ Đã nạp Dockerfile từ dự án [${data.dir_name}]! Context: ${data.dir_path}`);
      } else {
        showToast('✕ Lỗi: ' + (data.error || 'Không thể đọc tệp Dockerfile'));
      }
    } catch (e) {
      showToast('Lỗi khi nạp Dockerfile: ' + e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function clearBuildContext() {
    selectedBuildContextDir = null;
    selectedDockerfileFile = null;
    const banner = document.getElementById('buildContextBanner');
    if (banner) banner.style.display = 'none';
    const select = document.getElementById('discoveredDockerfilesSelect');
    if (select) select.value = '';
    showToast('Đã bỏ chọn Context. Chế độ build độc lập trong thư mục tạm.');
  }

  async function runDockerBuild() {
    const editor = document.getElementById('dockerfileEditor');
    const tagInput = document.getElementById('dockerBuildTag');
    const chkProxy = document.getElementById('chkInjectProxy');
    const chkNet = document.getElementById('chkNetworkHost');
    const chkCache = document.getElementById('chkNoCache');
    const chkCleanup = document.getElementById('chkAutoCleanup');
    const consoleBox = document.getElementById('dockerBuildConsole');
    const badge = document.getElementById('buildStatusBadge');
    const metrics = document.getElementById('buildMetrics');
    const btn = document.getElementById('btnRunDockerBuild');
    const spinner = document.getElementById('buildSpinner');

    const dockerfile = editor.value.trim();
    const tag = tagInput.value.trim() || 'warp-build-test:latest';

    if (!dockerfile) {
      showToast('Vui lòng nhập nội dung Dockerfile!');
      return;
    }

    btn.disabled = true;
    if (spinner) spinner.style.display = 'inline';
    badge.className = 'badge-status active';
    badge.style.color = '';
    badge.style.background = '';
    badge.innerText = '⏳ Đang Build...';
    metrics.innerText = `Tag: ${tag} | Bắt đầu...`;

    const warpPort = (currentStatus && currentStatus.port) ? currentStatus.port : 40000;
    const proxySourceEl = document.getElementById('dockerBuildProxySource');
    const proxySource = proxySourceEl ? proxySourceEl.value : 'warp';
    const proxySrcText = proxySource === 'residential' ? 'Proxy Dân Cư' : `Cloudflare WARP (socks5://127.0.0.1:${warpPort})`;
    const contextText = selectedBuildContextDir ? `${selectedBuildContextDir} (Dự án thực tế)` : 'Tạm thời (Chế độ độc lập)';

    consoleBox.innerText = `[Bắt đầu] docker build ${chkNet.checked ? '--network host ' : ''}${chkCache.checked ? '--no-cache ' : ''}-t ${tag} ...\n` +
      `[Thông số] Thư mục Context: ${contextText}\n` +
      `[Thông số] Nguồn Proxy: ${proxySrcText} | Inject Proxy: ${chkProxy.checked ? 'BẬT' : 'TẮT'}\n` +
      `[Lưu ý] Tiến trình có thể mất từ 5-30 giây tùy theo kích thước base image...\n------------------------------------------------------------\n`;

    showToast(`Đang thực hiện docker build image ${tag}...`);

    try {
      const res = await fetch('/api/docker/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dockerfile: dockerfile,
          tag: tag,
          context_dir: selectedBuildContextDir || '',
          proxy_source: proxySource,
          network_host: chkNet.checked,
          inject_proxy: chkProxy.checked,
          no_cache: chkCache.checked,
          cleanup: chkCleanup.checked
        })
      });

      const data = await res.json();
      if (data.success) {
        badge.className = 'badge-status active';
        badge.innerText = `✓ Hoàn tất (0)`;
        metrics.innerText = `Thời gian: ${data.duration}s | Exit: 0`;
        consoleBox.innerText += (data.output || 'Build thành công không có output.') + `\n\n[✓ THÀNH CÔNG] Build hoàn tất trong ${data.duration} giây!`;
        showToast(`Docker build ${tag} thành công trong ${data.duration}s!`);
      } else {
        badge.className = 'badge-status inactive';
        badge.style.color = '#ef4444';
        badge.style.background = 'rgba(239, 68, 68, 0.15)';
        badge.innerText = `✕ Thất bại (${data.exit_code})`;
        metrics.innerText = `Thời gian: ${data.duration || '--'}s | Lỗi`;
        consoleBox.innerText += (data.output || data.error || 'Đã có lỗi xảy ra trong quá trình build.');
        showToast('Docker build thất bại! Kiểm tra console log.');
      }
    } catch (e) {
      badge.className = 'badge-status inactive';
      badge.style.color = '#ef4444';
      badge.innerText = '✕ Lỗi kết nối';
      consoleBox.innerText += `\n[Lỗi kết nối]: ${e}`;
      showToast('Lỗi khi gọi API build: ' + e);
    } finally {
      btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
      consoleBox.scrollTop = consoleBox.scrollHeight;
    }
  }

  async function cleanupDockerImage() {
    const tag = document.getElementById('dockerBuildTag').value.trim() || 'warp-build-test:latest';
    showToast(`Đang xóa image ${tag}...`);
    try {
      const res = await fetch('/api/docker/cleanup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag })
      });
      const data = await res.json();
      const consoleBox = document.getElementById('dockerBuildConsole');
      if (data.success) {
        showToast(`Đã xóa image ${tag} thành công!`);
        consoleBox.innerText += `\n[Dọn dẹp]: Đã xóa image ${tag}\n${data.output || ''}`;
      } else {
        showToast(`Không thể xóa image: ${data.error || 'Lỗi'}`);
        consoleBox.innerText += `\n[Lỗi dọn dẹp]: ${data.error || ''}`;
      }
      consoleBox.scrollTop = consoleBox.scrollHeight;
    } catch (e) {
      showToast('Lỗi khi dọn image: ' + e);
    }
  }

  function clearDockerConsole() {
    const consoleBox = document.getElementById('dockerBuildConsole');
    consoleBox.innerText = '[Sẵn sàng] Console đã được xóa. Nhấn "🚀 Bắt Đầu Build" để chạy lệnh mới.';
    const badge = document.getElementById('buildStatusBadge');
    badge.className = 'badge-status inactive';
    badge.innerText = '○ Chờ lệnh build';
    badge.style.color = '';
    badge.style.background = '';
    document.getElementById('buildMetrics').innerText = '--';
  }

  async function toggleGitProxy() {
    const enable = document.getElementById('gitSwitch').checked;
    showToast(enable ? 'Đang cấu hình Proxy cho GitHub...' : 'Đang hủy Proxy cho GitHub...');
    try {
      await fetch('/api/toggle-git', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable })
      });
      showToast('Cập nhật cấu hình GitHub thành công!');
      setTimeout(fetchStatus, 1000);
    } catch (e) {
      showToast('Lỗi cấu hình GitHub: ' + e);
    }
  }

  async function toggleGitLabProxy() {
    const enable = document.getElementById('gitlabSwitch').checked;
    showToast(enable ? 'Đang cấu hình Proxy cho GitLab...' : 'Đang hủy Proxy cho GitLab...');
    try {
      await fetch('/api/toggle-gitlab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable })
      });
      showToast('Cập nhật cấu hình GitLab thành công!');
      setTimeout(fetchStatus, 1000);
    } catch (e) {
      showToast('Lỗi cấu hình GitLab: ' + e);
    }
  }

  async function saveCustomPort() {
    const port = document.getElementById('customPortInput').value;
    showToast(`Đang chuyển SOCKS5 Proxy sang port ${port}...`);
    try {
      await fetch('/api/set-port', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port: parseInt(port) })
      });
      showToast(`Đã đổi sang port ${port}!`);
      setTimeout(fetchStatus, 1500);
    } catch (e) {
      showToast('Lỗi đổi port: ' + e);
    }
  }

  async function runSpeedTest() {
    const region = document.getElementById('regionSelect').value;
    const btn = document.getElementById('testSpeedBtn');
    const singleBox = document.getElementById('singleResultBox');
    const allBox = document.getElementById('allResultsBox');
    const resultBox = document.getElementById('speedResult');
    const detailBox = document.getElementById('speedDetail');

    btn.disabled = true;
    btn.innerText = 'Đang đo...';
    showToast('Đang kết nối đo kiểm tốc độ...');

    if (region === 'ALL') {
      singleBox.style.display = 'none';
      allBox.style.display = 'block';
      const tbody = document.getElementById('allResultsTbody');
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:#9ca3af; padding:20px;">Đang song song đo kiểm 8 trạm Anycast toàn cầu...</td></tr>';

      try {
        const res = await fetch('/api/test-speed', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ region: 'ALL' })
        });
        const data = await res.json();
        tbody.innerHTML = '';
        data.results.forEach(r => {
          const row = document.createElement('tr');
          const pct = Math.min(100, Math.max(8, Math.round((r.speed_mb_s / 50) * 100)));
          row.innerHTML = `
            <td style="padding: 10px 12px;"><strong>${r.flag}</strong> ${r.name}</td>
            <td style="font-family:'JetBrains Mono'; color:#00d2ff; font-weight:700; padding: 10px 12px;">
              ${r.speed_mb_s} MB/s
              <div style="background:rgba(255,255,255,0.06); height:4px; border-radius:2px; margin-top:4px; width:130px;">
                <div style="background:linear-gradient(90deg, #00d2ff, #3a7bd5); height:100%; border-radius:2px; width:${pct}%;"></div>
              </div>
            </td>
            <td style="font-family:'JetBrains Mono'; color:#9ca3af; padding: 10px 12px;">${r.latency_ms} ms</td>
            <td style="padding: 10px 12px;"><span class="badge-status active">✓ Hoàn tất</span></td>
          `;
          tbody.appendChild(row);
        });
        showToast('Đã đo xong toàn bộ các Data Center!');
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="4" style="color:#ef4444; padding:15px;">Lỗi: ${e}</td></tr>`;
      } finally {
        btn.disabled = false;
        btn.innerText = '▶ Bắt đầu kiểm tra tốc độ';
      }
    } else {
      allBox.style.display = 'none';
      singleBox.style.display = 'block';
      resultBox.innerText = '...';

      try {
        const res = await fetch('/api/test-speed', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ region })
        });
        const r = await res.json();
        resultBox.innerText = r.speed_mb_s ? r.speed_mb_s.toFixed(2) : '0';
        detailBox.innerText = `${r.flag} ${r.name} | Độ trễ: ${r.latency_ms}ms | Thời gian: ${r.duration_sec}s`;
        showToast(`Đo tốc độ trạm ${r.country} hoàn tất!`);
      } catch (e) {
        resultBox.innerText = 'Lỗi';
        detailBox.innerText = 'Không thể đo kiểm: ' + e;
      } finally {
        btn.disabled = false;
        btn.innerText = '▶ Bắt đầu kiểm tra tốc độ';
      }
    }
  }

  async function loadLogs() {
    const box = document.getElementById('logsBox');
    box.innerText = 'Đang tải...';
    try {
      const res = await fetch('/api/logs');
      if (res.status === 401) {
        window.location.href = '/login';
        return;
      }
      const data = await res.json();
      box.innerText = data.logs || 'Không có log.';
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerText = 'Không thể tải log: ' + e;
    }
  }

  async function logout() {
    try {
      await fetch('/api/logout', { method: 'POST' });
    } catch (e) {}
    window.location.href = '/login';
  }

  function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.style.display = 'flex';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
  }

  function copyToClipboard(text) {
    navigator.clipboard.writeText(text);
    showToast('Đã sao chép vào bộ nhớ tạm!');
  }

  function openChangePasswordModal() {
    document.getElementById('modalCurrentPass').value = '';
    document.getElementById('modalNewPass').value = '';
    document.getElementById('modalConfirmPass').value = '';
    const alert = document.getElementById('modalAlert');
    alert.style.display = 'none';
    alert.className = 'modal-alert';
    document.getElementById('changePasswordModal').style.display = 'flex';
  }

  function closeChangePasswordModal() {
    document.getElementById('changePasswordModal').style.display = 'none';
  }

  async function submitChangePassword() {
    const cur = document.getElementById('modalCurrentPass').value;
    const np = document.getElementById('modalNewPass').value;
    const cp = document.getElementById('modalConfirmPass').value;
    const alert = document.getElementById('modalAlert');
    const btn = document.getElementById('btnSubmitPass');

    alert.style.display = 'none';

    if (!cur || !np || !cp) {
      alert.innerText = 'Vui lòng điền đầy đủ các thông tin!';
      alert.className = 'modal-alert modal-alert-error';
      alert.style.display = 'block';
      return;
    }
    if (np.length < 6) {
      alert.innerText = 'Mật khẩu mới phải có ít nhất 6 ký tự!';
      alert.className = 'modal-alert modal-alert-error';
      alert.style.display = 'block';
      return;
    }
    if (np !== cp) {
      alert.innerText = 'Mật khẩu xác nhận không khớp!';
      alert.className = 'modal-alert modal-alert-error';
      alert.style.display = 'block';
      return;
    }

    btn.disabled = true;
    btn.innerText = 'Đang xử lý...';

    try {
      const res = await fetch('/api/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: cur, new_password: np })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        alert.innerText = 'Đổi mật khẩu thành công! Đang chuyển về trang đăng nhập...';
        alert.className = 'modal-alert modal-alert-success';
        alert.style.display = 'block';
        setTimeout(() => {
          window.location.href = '/login';
        }, 1500);
      } else {
        alert.innerText = data.error || 'Đổi mật khẩu thất bại!';
        alert.className = 'modal-alert modal-alert-error';
        alert.style.display = 'block';
        btn.disabled = false;
        btn.innerText = 'Cập nhật mật khẩu';
      }
    } catch (e) {
      alert.innerText = 'Lỗi kết nối máy chủ: ' + e;
      alert.className = 'modal-alert modal-alert-error';
      alert.style.display = 'block';
      btn.disabled = false;
      btn.innerText = 'Cập nhật mật khẩu';
    }
  }

  // --- RESIDENTIAL PROXY FUNCTIONS ---
  async function loadResidentialProxy() {
    try {
      const res = await fetch('/api/residential-proxy');
      if (res.status === 401) { window.location.href = '/login'; return; }
      const data = await res.json();
      if (data.success && data.config) {
        const c = data.config;
        if (c.proto) document.getElementById('resProto').value = c.proto;
        if (c.host) document.getElementById('resHost').value = c.host;
        if (c.port) document.getElementById('resPort').value = c.port;
        if (c.username) document.getElementById('resUser').value = c.username;
        if (c.has_password) {
          document.getElementById('resPass').placeholder = '●●●●●● (Đã lưu mật khẩu, nhập mới nếu muốn đổi)';
        }
        if (c.no_proxy) document.getElementById('resNoProxy').value = c.no_proxy;
        updateResidentialProxyUI(c);
      }
    } catch (e) {
      console.error('Lỗi tải cấu hình proxy dân cư:', e);
    }
  }

  function updateResidentialProxyUI(resData) {
    if (!resData) return;
    const isResActive = (resData.active_source === 'residential') || resData.enabled;
    const badge = document.getElementById('resActiveBadge');
    const curEgress = document.getElementById('resCurrentEgress');
    const maskedUrl = document.getElementById('resMaskedUrl');
    const ispVal = document.getElementById('resIspValue');
    const spdVal = document.getElementById('resSpeedValue');
    const ovBadge = document.getElementById('ovResProxyBadge');

    if (badge) {
      badge.className = isResActive ? 'badge-status active' : 'badge-status inactive';
      badge.innerText = isResActive ? '● Đang dùng Proxy Dân Cư' : '○ Đang dùng WARP';
    }
    if (curEgress) {
      curEgress.innerText = isResActive ? '🏡 Proxy Dân Cư (Egress Riêng)' : '🛡️ Cloudflare WARP Anycast';
      curEgress.style.color = isResActive ? 'var(--accent)' : '#3a7bd5';
    }
    if (maskedUrl) {
      maskedUrl.innerText = resData.proxy_url_masked || (resData.host ? `${resData.proto}://${resData.host}:${resData.port}` : 'Chưa cấu hình');
    }

    if (resData.last_test) {
      const lt = resData.last_test;
      if (ispVal) ispVal.innerText = (lt.isp ? lt.isp : '') + (lt.country ? ` (${lt.country})` : '');
      if (spdVal) spdVal.innerText = lt.speed_mb_s ? `${lt.speed_mb_s} MB/s` : '--';
      renderResidentialTestResult(lt);
    }

    if (ovBadge) {
      if (isResActive) {
        ovBadge.className = 'badge-status active';
        ovBadge.innerText = '● Đang Bật';
      } else if (resData.configured || resData.host) {
        ovBadge.className = 'badge-status inactive';
        ovBadge.innerText = '○ Sẵn sàng';
      } else {
        ovBadge.className = 'badge-status inactive';
        ovBadge.innerText = '○ Chưa cài đặt';
      }
    }

    // Snippets
    const rawMasked = resData.proxy_url_masked || 'socks5://user:pass@host:port';
    const curlEl = document.getElementById('resCurlSnippet');
    if (curlEl) curlEl.innerText = `curl -x "${rawMasked}" https://cloudflare.com/cdn-cgi/trace`;
    const expEl = document.getElementById('resExportSnippet');
    if (expEl) expEl.innerText = `export all_proxy="${rawMasked}"`;
  }

  async function autoParseProxyInput() {
    const raw = document.getElementById('resQuickInput').value.trim();
    if (!raw) {
      showToast('Vui lòng dán chuỗi proxy cần phân tích!');
      return;
    }
    showToast('Đang phân tích định dạng proxy...');
    try {
      const res = await fetch('/api/residential-proxy/parse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ raw })
      });
      const data = await res.json();
      if (data.success && data.parsed) {
        const p = data.parsed;
        if (p.proto) document.getElementById('resProto').value = p.proto;
        if (p.host) document.getElementById('resHost').value = p.host;
        if (p.port) document.getElementById('resPort').value = p.port;
        if (p.username) document.getElementById('resUser').value = p.username;
        if (p.password) document.getElementById('resPass').value = p.password;
        showToast('✓ Đã phân tích và điền tự động thông tin Proxy!');
      } else {
        showToast('✕ ' + (data.error || 'Định dạng không hợp lệ!'));
      }
    } catch (e) {
      showToast('Lỗi phân tích: ' + e);
    }
  }

  function getResidentialFormConfig() {
    return {
      proto: document.getElementById('resProto').value,
      host: document.getElementById('resHost').value.trim(),
      port: parseInt(document.getElementById('resPort').value.trim()) || 1080,
      username: document.getElementById('resUser').value.trim(),
      password: document.getElementById('resPass').value,
      no_proxy: document.getElementById('resNoProxy').value.trim()
    };
  }

  async function saveResidentialProxy() {
    const cfg = getResidentialFormConfig();
    if (!cfg.host) {
      showToast('Vui lòng nhập Host hoặc IP của Proxy Dân Cư!');
      return;
    }
    const btn = document.getElementById('btnSaveResProxy');
    btn.disabled = true;
    showToast('Đang lưu thông tin proxy dân cư...');
    try {
      const res = await fetch('/api/residential-proxy/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: cfg })
      });
      const data = await res.json();
      if (data.success) {
        showToast('✓ ' + data.message);
        if (data.config) updateResidentialProxyUI(data.config);
        setTimeout(fetchStatus, 1000);
      } else {
        showToast('✕ Lỗi: ' + (data.error || 'Không thể lưu'));
      }
    } catch (e) {
      showToast('Lỗi lưu cấu hình: ' + e);
    } finally {
      btn.disabled = false;
    }
  }

  function renderResidentialTestResult(r) {
    const box = document.getElementById('resTestDetails');
    const waiting = document.getElementById('resTestWaiting');
    if (!box || !r) return;

    if (waiting) waiting.style.display = 'none';
    box.style.display = 'block';

    const badge = document.getElementById('resDiagBadge');
    if (badge) {
      badge.className = r.success ? 'badge-status active' : 'badge-status inactive';
      badge.innerText = r.success ? '✓ Kết nối thành công' : '✕ Kết nối thất bại';
      badge.style.color = r.success ? '' : '#ef4444';
      badge.style.background = r.success ? '' : 'rgba(239, 68, 68, 0.15)';
    }

    document.getElementById('resDiagIp').innerText = r.ip || '--';
    document.getElementById('resDiagIsp').innerText = (r.isp || '--') + (r.city ? ` (${r.city})` : '');
    document.getElementById('resDiagLocation').innerText = (r.country || '--') + (r.colo ? ` [Colo: ${r.colo}]` : '');
    document.getElementById('resDiagLatency').innerText = (r.latency_ms ? `${r.latency_ms} ms` : '--');
    document.getElementById('resDiagSpeed').innerText = (r.speed_mb_s ? `${r.speed_mb_s} MB/s` : '--');
  }

  async function testResidentialProxy() {
    const cfg = getResidentialFormConfig();
    const btn = document.getElementById('btnTestResProxy');
    const spinner = document.getElementById('resTestSpinner');
    btn.disabled = true;
    if (spinner) spinner.style.display = 'inline';
    showToast('Đang kết nối thử nghiệm đến Proxy Dân Cư & đo tốc độ...');

    try {
      const res = await fetch('/api/residential-proxy/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config: cfg })
      });
      const data = await res.json();
      if (data.success) {
        renderResidentialTestResult(data);
        const ispVal = document.getElementById('resIspValue');
        const spdVal = document.getElementById('resSpeedValue');
        if (ispVal) ispVal.innerText = (data.isp || '') + (data.country ? ` (${data.country})` : '');
        if (spdVal) spdVal.innerText = data.speed_mb_s ? `${data.speed_mb_s} MB/s` : '--';
        showToast(`✓ Kết nối proxy tốt! Tốc độ: ${data.speed_mb_s} MB/s, Ping: ${data.latency_ms}ms`);
      } else {
        const waiting = document.getElementById('resTestWaiting');
        const box = document.getElementById('resTestDetails');
        if (waiting) {
          waiting.style.display = 'block';
          waiting.innerHTML = `<div style="color: #ef4444; font-size: 28px; margin-bottom: 6px;">✕</div>` +
            `<div style="color: #ef4444; font-weight: 600; margin-bottom: 4px;">Kết nối thất bại</div>` +
            `<div style="font-size: 11px; color: var(--text-muted); word-break: break-all;">${data.error || 'Không kết nối được'}</div>`;
        }
        if (box) box.style.display = 'none';
        showToast('✕ Kiểm tra thất bại: ' + (data.error || 'Lỗi kết nối'));
      }
    } catch (e) {
      showToast('Lỗi kiểm tra proxy: ' + e);
    } finally {
      btn.disabled = false;
      if (spinner) spinner.style.display = 'none';
    }
  }

  async function applyResidentialProxy(target = 'all') {
    const targetName = target === 'docker' ? 'Docker' : (target === 'git' ? 'Git CLI' : 'Docker & Git');
    showToast(`Đang kích hoạt Proxy Dân Cư cho ${targetName}...`);
    try {
      const res = await fetch('/api/residential-proxy/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target })
      });
      const data = await res.json();
      if (data.success) {
        showToast('✓ ' + data.message);
        setTimeout(fetchStatus, 1000);
        setTimeout(fetchDockerStatus, 1500);
      } else {
        showToast('✕ Lỗi: ' + (data.error || 'Không thể kích hoạt'));
      }
    } catch (e) {
      showToast('Lỗi kích hoạt: ' + e);
    }
  }

  async function switchBackToWarp() {
    showToast('Đang khôi phục toàn bộ hệ thống về Cloudflare WARP Anycast...');
    try {
      const res = await fetch('/api/residential-proxy/switch-warp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      const data = await res.json();
      if (data.success) {
        showToast('✓ ' + data.message);
        setTimeout(fetchStatus, 1000);
        setTimeout(fetchDockerStatus, 1500);
      } else {
        showToast('✕ Lỗi: ' + (data.error || 'Không thể khôi phục WARP'));
      }
    } catch (e) {
      showToast('Lỗi khôi phục: ' + e);
    }
  }

  fetchStatus();
  loadLogs();
  setInterval(fetchStatus, 10000);

  // Khôi phục tab từ URL hash nếu có
  function initTabFromHash() {
    const hash = window.location.hash.replace('#', '');
    if (['overview', 'speedtest', 'routing', 'docker', 'residential', 'gitlab', 'logs'].includes(hash)) {
      switchTab(hash);
    }
  }
  window.addEventListener('DOMContentLoaded', () => {
    initTabFromHash();
    loadDockerfileTemplate('alpine');
    loadResidentialProxy();
    const noProxyInput = document.getElementById('dockerNoProxyInput');
    if (noProxyInput) {
      noProxyInput.addEventListener('input', () => {
        noProxyInput.dataset.userEdited = 'true';
      });
    }
  });
  window.addEventListener('hashchange', initTabFromHash);
  initTabFromHash();
  loadDockerfileTemplate('alpine');
</script>

<!-- Modal Đổi Mật Khẩu -->
<div id="changePasswordModal" class="modal-backdrop">
  <div class="modal-card">
    <div class="modal-header">
      <h3>🔐 Đổi Mật Khẩu Quản Trị</h3>
      <button onclick="closeChangePasswordModal()" class="modal-close">&times;</button>
    </div>
    <div id="modalAlert" class="modal-alert"></div>
    <div style="margin-bottom: 14px;">
      <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:6px;">Mật khẩu hiện tại</label>
      <input type="password" id="modalCurrentPass" class="input-style" placeholder="Nhập mật khẩu hiện tại" />
    </div>
    <div style="margin-bottom: 14px;">
      <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:6px;">Mật khẩu mới (ít nhất 6 ký tự)</label>
      <input type="password" id="modalNewPass" class="input-style" placeholder="Nhập mật khẩu mới" />
    </div>
    <div style="margin-bottom: 20px;">
      <label style="font-size:12px; color:var(--text-muted); display:block; margin-bottom:6px;">Xác nhận mật khẩu mới</label>
      <input type="password" id="modalConfirmPass" class="input-style" placeholder="Nhập lại mật khẩu mới" />
    </div>
    <div style="display:flex; justify-content:flex-end; gap:10px;">
      <button onclick="closeChangePasswordModal()" class="btn btn-secondary btn-sm">Hủy</button>
      <button onclick="submitChangePassword()" class="btn btn-primary btn-sm" id="btnSubmitPass">Cập nhật mật khẩu</button>
    </div>
  </div>
</div>

</body>
</html>
"""

# ==============================================================================
# HTTP REQUEST HANDLER
# ==============================================================================

class WarpAPIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def get_client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def send_json(self, data, code=200):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        user = get_authenticated_user(self.headers)

        # 1. Trang Login
        if path == "/login":
            if user:
                self.send_redirect("/")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(LOGIN_HTML.encode("utf-8"))
            return

        # 2. Trang Dashboard chính (Yêu cầu đăng nhập)
        if path == "/" or path == "/index.html":
            if not user:
                self.send_redirect("/login")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        # 3. API Endpoints (Bảo vệ bằng Session Cookie)
        if path.startswith("/api/"):
            if not user:
                self.send_json({"error": "Unauthorized", "login_required": True}, code=401)
                return

            if path == "/api/status":
                status = get_warp_status()
                status["user"] = user
                self.send_json(status)
                return

            if path == "/api/regions":
                self.send_json(DATA_CENTERS)
                return

            if path == "/api/logs":
                _, logs, _ = run_cmd("journalctl -u warp-svc -n 40 --no-pager 2>/dev/null", timeout=5)
                self.send_json({"logs": logs})
                return

            if path == "/api/residential-proxy":
                cfg = load_residential_proxy()
                safe_cfg = dict(cfg)
                safe_cfg["has_password"] = bool(cfg.get("password"))
                safe_cfg["password"] = ""
                safe_cfg["proxy_url_masked"] = get_proxy_url(cfg, hide_password=True)
                self.send_json({"success": True, "config": safe_cfg})
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        client_ip = self.get_client_ip()

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        # 1. API Đăng Nhập (Công khai, có chống Brute-force)
        if path == "/api/login":
            if check_rate_limit(client_ip):
                self.send_json({"success": False, "error": "Đã thử sai quá 5 lần. Vui lòng đợi 5 phút để thử lại!"}, code=429)
                return

            username = req_data.get("username", "").strip()
            password = req_data.get("password", "")
            remember = req_data.get("remember", True)

            if verify_credentials(username, password):
                clear_failed_attempts(client_ip)
                token = secrets.token_hex(32)
                # 7 ngày nếu remember, 24 giờ nếu không
                ttl = 86400 * 7 if remember else 86400
                SESSIONS[token] = {
                    "username": username,
                    "expires": time.time() + ttl
                }

                cookie = http.cookies.SimpleCookie()
                cookie["warp_session"] = token
                cookie["warp_session"]["path"] = "/"
                cookie["warp_session"]["httponly"] = True
                cookie["warp_session"]["max-age"] = ttl
                cookie["warp_session"]["samesite"] = "Lax"

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", cookie.output(header="").strip())
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                return
            else:
                record_failed_attempt(client_ip)
                self.send_json({"success": False, "error": "Sai tên đăng nhập hoặc mật khẩu!"}, code=401)
                return

        # 2. API Đăng Xuất
        if path == "/api/logout":
            cookie_header = self.headers.get("Cookie", "")
            if cookie_header:
                c = http.cookies.SimpleCookie()
                try:
                    c.load(cookie_header)
                    if "warp_session" in c:
                        token = c["warp_session"].value
                        if token in SESSIONS:
                            del SESSIONS[token]
                except Exception:
                    pass

            cookie = http.cookies.SimpleCookie()
            cookie["warp_session"] = ""
            cookie["warp_session"]["path"] = "/"
            cookie["warp_session"]["httponly"] = True
            cookie["warp_session"]["max-age"] = 0

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", cookie.output(header="").strip())
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
            return

        # 3. Tất cả các API quản trị bên dưới BẮT BUỘC ĐÃ ĐĂNG NHẬP
        user = get_authenticated_user(self.headers)
        if not user:
            self.send_json({"error": "Unauthorized", "login_required": True}, code=401)
            return

        # Đổi mật khẩu tài khoản
        if path == "/api/change-password":
            cur_pass = req_data.get("current_password", "")
            new_pass = req_data.get("new_password", "")
            if not verify_credentials(user, cur_pass):
                self.send_json({"success": False, "error": "Mật khẩu hiện tại không chính xác!"}, code=400)
                return
            if len(new_pass) < 6:
                self.send_json({"success": False, "error": "Mật khẩu mới phải có tối thiểu 6 ký tự!"}, code=400)
                return
            set_password(new_pass, username=user)
            self.send_json({"success": True, "message": "Đã cập nhật mật khẩu thành công!"})
            return

        if path == "/api/connect":
            run_cmd("warp-cli --accept-tos connect 2>/dev/null || warp-cli connect 2>/dev/null")
            time.sleep(1)
            self.send_json({"success": True})
            return

        if path == "/api/disconnect":
            run_cmd("warp-cli --accept-tos disconnect 2>/dev/null || warp-cli disconnect 2>/dev/null")
            time.sleep(1)
            self.send_json({"success": True})
            return

        if path == "/api/set-port":
            port = int(req_data.get("port", 40000))
            run_cmd(f"warp-cli --accept-tos proxy port {port} 2>/dev/null || warp-cli proxy port {port} 2>/dev/null")
            self.send_json({"success": True, "port": port})
            return

        # API Quản lý Docker Daemon & Proxy
        if path == "/api/docker/status":
            self.send_json({"success": True, "info": get_docker_info()})
            return

        if path == "/api/docker/scan":
            scan_path = req_data.get("path", "/root").strip()
            max_depth = int(req_data.get("max_depth", 3))
            max_depth = max(1, min(max_depth, 6))
            results = scan_dockerfiles(scan_path, max_depth=max_depth)
            self.send_json({
                "success": True,
                "base_path": scan_path,
                "count": len(results),
                "dockerfiles": results
            })
            return

        if path == "/api/docker/read-file":
            file_path = req_data.get("file_path", "").strip()
            res = read_dockerfile_content(file_path)
            if res.get("success"):
                self.send_json(res)
            else:
                self.send_json(res, code=400)
            return

        if path == "/api/docker/reload" or path == "/api/toggle-docker":
            enable = req_data.get("enable", True)
            no_proxy = req_data.get("no_proxy", "").strip()
            if not no_proxy:
                no_proxy = "localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23,192.168.200.0/24"
            
            status = get_warp_status()
            port = status.get("port", 40000)
            conf_dir = "/etc/systemd/system/docker.service.d"
            conf_path = f"{conf_dir}/http-proxy.conf"

            if enable:
                os.makedirs(conf_dir, exist_ok=True)
                content = f"""[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:{port}"
Environment="HTTPS_PROXY=socks5://127.0.0.1:{port}"
Environment="NO_PROXY={no_proxy}"
"""
                with open(conf_path, "w") as f:
                    f.write(content)
            else:
                if os.path.exists(conf_path):
                    os.remove(conf_path)

            run_cmd("systemctl daemon-reload && systemctl restart docker", timeout=30)
            time.sleep(1)
            info = get_docker_info()
            self.send_json({"success": True, "docker_proxy": enable, "info": info})
            return

        # API Thực hiện lệnh Docker Build
        if path == "/api/docker/build":
            dockerfile = req_data.get("dockerfile", "").strip()
            tag = req_data.get("tag", "warp-build-test:latest").strip()
            context_dir = req_data.get("context_dir", "").strip()
            network_host = req_data.get("network_host", True)
            inject_proxy = req_data.get("inject_proxy", True)
            no_cache = req_data.get("no_cache", True)
            cleanup = req_data.get("cleanup", False)

            if not dockerfile:
                self.send_json({"success": False, "error": "Nội dung Dockerfile không được để trống!"}, code=400)
                return

            if context_dir and not os.path.isdir(context_dir):
                self.send_json({"success": False, "error": f"Thư mục build context không tồn tại: {context_dir}"}, code=400)
                return

            status = get_warp_status()
            port = status.get("port", 40000)
            proxy_source = req_data.get("proxy_source", "warp")
            build_proxy_url = f"socks5://127.0.0.1:{port}"
            build_no_proxy = "localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,deb.debian.org,*.debian.org,archive.ubuntu.com,security.ubuntu.com,103.186.100.0/23,192.168.200.0/24"

            if proxy_source == "residential":
                res_cfg = load_residential_proxy()
                res_url = get_proxy_url(res_cfg, hide_password=False)
                if res_url:
                    build_proxy_url = res_url
                    if res_cfg.get("no_proxy"):
                        build_no_proxy = res_cfg.get("no_proxy")

            t0 = time.time()
            tmp_df_dir = None
            try:
                cmd = ["docker", "build"]
                if network_host:
                    cmd += ["--network", "host"]
                if no_cache:
                    cmd += ["--no-cache"]
                if inject_proxy:
                    cmd += [
                        "--build-arg", f"HTTP_PROXY={build_proxy_url}",
                        "--build-arg", f"HTTPS_PROXY={build_proxy_url}",
                        "--build-arg", f"ALL_PROXY={build_proxy_url}",
                        "--build-arg", f"http_proxy={build_proxy_url}",
                        "--build-arg", f"https_proxy={build_proxy_url}",
                        "--build-arg", f"all_proxy={build_proxy_url}",
                        "--build-arg", f"NO_PROXY={build_no_proxy}",
                        "--build-arg", f"no_proxy={build_no_proxy}"
                    ]

                tmp_df_dir = tempfile.mkdtemp(prefix="warp_build_")
                df_path = os.path.join(tmp_df_dir, "Dockerfile")
                with open(df_path, "w", encoding="utf-8") as f:
                    f.write(dockerfile)

                if context_dir and os.path.isdir(context_dir):
                    cmd += ["-t", tag, "-f", df_path, context_dir]
                else:
                    cmd += ["-t", tag, tmp_df_dir]

                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=300)
                dur = round(time.time() - t0, 2)
                output_text = p.stdout

                if cleanup and p.returncode == 0:
                    subprocess.run(["docker", "rmi", "-f", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    output_text += f"\n\n[Đã tự động dọn dẹp image: {tag}]"

                self.send_json({
                    "success": (p.returncode == 0),
                    "exit_code": p.returncode,
                    "duration": dur,
                    "output": output_text,
                    "context_dir": context_dir or "scratch"
                })
                return
            except subprocess.TimeoutExpired:
                dur = round(time.time() - t0, 2)
                self.send_json({
                    "success": False,
                    "exit_code": -1,
                    "duration": dur,
                    "output": "Lệnh docker build bị timeout sau 300 giây!"
                }, code=408)
                return
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, code=500)
                return
            finally:
                if tmp_df_dir and os.path.exists(tmp_df_dir):
                    shutil.rmtree(tmp_df_dir, ignore_errors=True)

        if path == "/api/docker/cleanup":
            tag = req_data.get("tag", "").strip()
            if not tag:
                self.send_json({"success": False, "error": "Thiếu tag image!"}, code=400)
                return
            _, out, _ = run_cmd(f"docker rmi -f {tag}")
            self.send_json({"success": True, "output": out})
            return

        if path == "/api/toggle-git":
            enable = req_data.get("enable", True)
            status = get_warp_status()
            port = status.get("port", 40000)
            if enable:
                run_cmd(f"git config --global http.\"https://github.com/\".proxy \"socks5://127.0.0.1:{port}\"")
            else:
                run_cmd("git config --global --unset http.\"https://github.com/\".proxy")
            self.send_json({"success": True, "git_proxy": enable})
            return

        if path == "/api/toggle-gitlab":
            enable = req_data.get("enable", True)
            status = get_warp_status()
            port = status.get("port", 40000)
            if enable:
                run_cmd(f"git config --global http.\"https://gitlab.com/\".proxy \"socks5://127.0.0.1:{port}\"")
            else:
                run_cmd("git config --global --unset http.\"https://gitlab.com/\".proxy")
            self.send_json({"success": True, "gitlab_proxy": enable})
            return

        if path == "/api/test-speed":
            region = req_data.get("region", "DE_FSN")
            status = get_warp_status()
            port = status.get("port", 40000)

            if region == "ALL":
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    future_to_key = {executor.submit(benchmark_single_dc, k, port): k for k in DATA_CENTERS.keys()}
                    for future in concurrent.futures.as_completed(future_to_key):
                        res = future.result()
                        if res:
                            results.append(res)
                order = list(DATA_CENTERS.keys())
                results.sort(key=lambda x: order.index(x["id"]) if x["id"] in order else 99)
                self.send_json({"success": True, "results": results})
                return
            else:
                target_key = region if region in DATA_CENTERS else "DE_FSN"
                res = benchmark_single_dc(target_key, port)
                if res:
                    self.send_json(res)
                else:
                    self.send_json({"success": False, "error": "Invalid region"}, code=400)
                return

        # API Quản lý Proxy Dân Cư (Residential Proxy)
        if path == "/api/residential-proxy/parse":
            raw = req_data.get("raw", "").strip()
            parsed = parse_proxy_string(raw)
            if parsed:
                self.send_json({"success": True, "parsed": parsed})
            else:
                self.send_json({"success": False, "error": "Không thể nhận diện định dạng proxy. Vui lòng nhập: ip:port:user:pass, user:pass@host:port, hoặc host:port"}, code=400)
            return

        if path == "/api/residential-proxy/save":
            cfg = req_data.get("config", {})
            save_residential_proxy(cfg)
            saved = load_residential_proxy()
            safe_cfg = dict(saved)
            safe_cfg["has_password"] = bool(saved.get("password"))
            safe_cfg["password"] = ""
            safe_cfg["proxy_url_masked"] = get_proxy_url(saved, hide_password=True)
            self.send_json({"success": True, "message": "Đã lưu cấu hình Proxy Dân Cư thành công!", "config": safe_cfg})
            return

        if path == "/api/residential-proxy/test":
            cfg = req_data.get("config")
            if not cfg or not cfg.get("host"):
                cfg = load_residential_proxy()
            else:
                if not cfg.get("password"):
                    saved = load_residential_proxy()
                    cfg["password"] = saved.get("password", "")
            res = test_residential_proxy(cfg)
            if res.get("success"):
                saved = load_residential_proxy()
                saved["last_test"] = res
                save_residential_proxy(saved)
            self.send_json(res)
            return

        if path == "/api/residential-proxy/apply":
            target = req_data.get("target", "all")
            saved = load_residential_proxy()
            proxy_url = get_proxy_url(saved, hide_password=False)
            if not proxy_url:
                self.send_json({"success": False, "error": "Chưa cấu hình host hoặc port của Proxy Dân Cư!"}, code=400)
                return
            no_proxy = saved.get("no_proxy", "")
            if target in ("all", "docker"):
                apply_proxy_to_docker(proxy_url, no_proxy)
            if target in ("all", "git"):
                apply_proxy_to_git(proxy_url)
            saved["active_source"] = "residential"
            saved["enabled"] = True
            save_residential_proxy(saved)
            self.send_json({
                "success": True,
                "message": f"Đã áp dụng Proxy Dân Cư thành công cho {target.upper()}!",
                "active_source": "residential",
                "proxy_url_masked": get_proxy_url(saved, hide_password=True)
            })
            return

        if path == "/api/residential-proxy/switch-warp":
            restore_warp_proxy()
            self.send_json({
                "success": True,
                "message": "Đã khôi phục toàn bộ hệ thống (Docker + Git) về Cloudflare WARP Anycast!",
                "active_source": "warp"
            })
            return

        self.send_response(404)
        self.end_headers()

def main():
    if "--set-password" in sys.argv:
        idx = sys.argv.index("--set-password")
        if idx + 1 < len(sys.argv):
            new_pass = sys.argv[idx + 1]
            set_password(new_pass)
            print(f"Đã cập nhật mật khẩu Web Dashboard thành công!")
            sys.exit(0)
        else:
            print("Lỗi: Thiếu tham số mật khẩu! Cú pháp: python3 web_dashboard.py --set-password <new_password>")
            sys.exit(1)

    # Khởi tạo thông tin xác thực nếu chưa có
    auth_data = init_auth()
    
    print("=" * 64)
    print("  CLOUDFLARE WARP WEB DASHBOARD & REST API")
    print(f"  Listening on: http://{HOST}:{PORT}")
    print(f"  Access locally: http://127.0.0.1:{PORT}")
    print(f"  Default Login: Username: '{auth_data.get('username')}'")
    print(f"  Auth Config  : {AUTH_FILE}")
    print("=" * 64)

    class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with ThreadedTCPServer((HOST, PORT), WarpAPIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
            sys.exit(0)

if __name__ == "__main__":
    main()
