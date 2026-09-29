#!/usr/bin/env python3
"""
Cloudflare WARP Web Dashboard & Management API
Multi-region Speed Test support (Germany, Singapore, Japan, USA, UK, Finland).
Zero external dependencies - Uses Python 3 standard library.
"""

import concurrent.futures
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import time
import urllib.parse

PORT = int(os.environ.get("WARP_DASHBOARD_PORT", "8888"))
HOST = os.environ.get("WARP_DASHBOARD_HOST", "0.0.0.0")

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

def run_cmd(cmd, timeout=15):
    """Run shell command and return stdout/stderr."""
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

def get_warp_status():
    """Retrieve full status of WARP and system integrations."""
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

    return {
        "connected": is_connected,
        "warp_active": warp_on,
        "port": proxy_port,
        "colo": colo,
        "ip": ip,
        "docker_proxy": docker_proxy_enabled,
        "git_proxy": git_proxy_enabled,
        "raw_status": status_out or "WARP Service Offline"
    }

def benchmark_single_dc(dc_key, port):
    """Benchmark a single datacenter endpoint."""
    dc = DATA_CENTERS.get(dc_key)
    if not dc:
        return None
    url = dc["url"]
    t0 = time.time()
    # Download 3MB chunk for snappy and accurate measurement
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

    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; }

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

    .badge-mode {
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: var(--success);
      font-size: 12px; font-weight: 600;
      padding: 4px 10px; border-radius: 20px;
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

    .col-7 { grid-column: span 7; }
    .col-5 { grid-column: span 5; }
    .col-6 { grid-column: span 6; }
    .col-12 { grid-column: span 12; }

    @media (max-width: 820px) {
      .col-7, .col-5, .col-6 { grid-column: span 12; }
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
    .btn-accent { background: rgba(0, 210, 255, 0.15); color: var(--accent); border: 1px solid rgba(0, 210, 255, 0.3); }
    .btn-accent:hover { background: rgba(0, 210, 255, 0.25); }
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
    .select-style option {
      background: #111827;
      color: white;
    }

    .speed-gauge { text-align: center; padding: 12px 0; }
    .speed-number { font-family: 'JetBrains Mono', monospace; font-size: 36px; font-weight: 800; color: var(--accent); }

    .benchmark-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 12px;
    }
    .benchmark-table th {
      text-align: left;
      padding: 8px 10px;
      color: var(--text-muted);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 11px;
    }
    .benchmark-table td {
      padding: 9px 10px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .benchmark-table tr:last-child td { border-bottom: none; }

    .terminal-box {
      background: #04070d;
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 12px; padding: 16px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 12px; color: #94a3b8;
      max-height: 180px; overflow-y: auto;
      white-space: pre-wrap; line-height: 1.6;
    }

    .code-snippet {
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(255, 255, 255, 0.08);
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
    <div class="badge-mode">
      <div class="dot"></div>
      Proxy Mode (SOCKS5)
    </div>
  </header>

  <div class="dashboard-grid">
    
    <!-- Status Card -->
    <div class="card col-7">
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

      <div class="stats-row">
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
      </div>
    </div>

    <!-- Multi-region Speed Test Card -->
    <div class="card col-5">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <h3 style="font-size: 15px; font-weight: 700;">Kiểm Tra Tốc Độ Đa Quốc Gia</h3>
      </div>
      
      <div style="margin-bottom: 12px;">
        <select id="regionSelect" class="select-style">
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

      <div style="display: flex; gap: 8px; margin-bottom: 14px;">
        <button onclick="runSpeedTest()" id="testSpeedBtn" class="btn btn-secondary btn-sm" style="flex: 1;">▶ Bắt đầu đo</button>
      </div>

      <div id="singleResultBox">
        <div class="speed-gauge">
          <div id="speedResult" class="speed-number">--</div>
          <div id="speedUnit" style="font-size: 12px; color: var(--text-muted);">MB/s</div>
        </div>
        <div id="speedDetail" style="font-size: 11px; text-align: center; color: var(--text-muted);">
          Chọn Data Center và nhấn "Bắt đầu đo"
        </div>
      </div>

      <!-- Multi Results Table -->
      <div id="allResultsBox" style="display: none; max-height: 180px; overflow-y: auto;">
        <table class="benchmark-table">
          <thead>
            <tr>
              <th>Data Center</th>
              <th>Tốc độ</th>
              <th>Độ trễ</th>
            </tr>
          </thead>
          <tbody id="allResultsTbody"></tbody>
        </table>
      </div>
    </div>

    <!-- Smart Routing Toggles -->
    <div class="card col-12">
      <h3 style="font-size: 16px; font-weight: 700; margin-bottom: 16px;">Cấu hình Điều hướng Thông minh (Smart Routing)</h3>

      <div class="control-item">
        <div class="control-info">
          <h4>Proxy cho Docker Daemon (Kèm NO_PROXY Docker Hub)</h4>
          <p>Tự động cấu hình daemon để kéo các registry quốc tế qua WARP, giữ nguyên tốc độ kéo trực tiếp Docker Hub (~200 Mbps).</p>
        </div>
        <label class="switch">
          <input type="checkbox" id="dockerSwitch" onchange="toggleDockerProxy()">
          <span class="slider"></span>
        </label>
      </div>

      <div class="control-item">
        <div class="control-info">
          <h4>Tăng tốc Git CLI cho GitHub (https://github.com/)</h4>
          <p>Chỉ định tuyến riêng git clone/push của GitHub đi qua WARP SOCKS5, không ảnh hưởng GitLab/Git nội bộ.</p>
        </div>
        <label class="switch">
          <input type="checkbox" id="gitSwitch" onchange="toggleGitProxy()">
          <span class="slider"></span>
        </label>
      </div>

      <div class="control-item">
        <div class="control-info">
          <h4>Đổi Cổng SOCKS5 Proxy</h4>
          <p>Mặc định là 40000. Bạn có thể đổi sang cổng khác nếu bị xung đột.</p>
        </div>
        <div style="display: flex; gap: 8px;">
          <input type="number" id="customPortInput" style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.15); color: white; padding: 6px 10px; border-radius: 8px; width: 100px; font-family: monospace;" value="40000">
          <button onclick="saveCustomPort()" class="btn btn-secondary btn-sm">Lưu</button>
        </div>
      </div>
    </div>

    <!-- Quick Commands -->
    <div class="card col-6">
      <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 10px;">Lệnh Dòng Lệnh Nhanh (On-Demand)</h3>
      <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 10px;">Bật proxy tạm thời cho toàn bộ phiên làm việc của terminal:</p>
      
      <div class="code-snippet">
        <code>export all_proxy="socks5://127.0.0.1:40000"</code>
        <button onclick="copyToClipboard('export all_proxy=\x22socks5://127.0.0.1:40000\x22')" class="btn btn-secondary btn-sm">Copy</button>
      </div>

      <div class="code-snippet">
        <code>curl --socks5-hostname 127.0.0.1:40000 https://example.com</code>
        <button onclick="copyToClipboard('curl --socks5-hostname 127.0.0.1:40000 https://example.com')" class="btn btn-secondary btn-sm">Copy</button>
      </div>
    </div>

    <!-- Logs Box -->
    <div class="card col-6">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <h3 style="font-size: 15px; font-weight: 700;">Nhật Ký Dịch Vụ (warp-svc)</h3>
        <button onclick="loadLogs()" class="btn btn-secondary btn-sm">Làm mới</button>
      </div>
      <div id="logsBox" class="terminal-box">Đang tải nhật ký hệ thống...</div>
    </div>

  </div>
</div>

<div id="toast"></div>

<script>
  let currentStatus = {};

  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
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

  async function toggleDockerProxy() {
    const enable = document.getElementById('dockerSwitch').checked;
    showToast(enable ? 'Đang bật Proxy cho Docker Daemon...' : 'Đang gỡ Proxy cho Docker Daemon...');
    try {
      await fetch('/api/toggle-docker', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable })
      });
      showToast('Cập nhật cấu hình Docker Daemon thành công!');
      setTimeout(fetchStatus, 1500);
    } catch (e) {
      showToast('Lỗi cập nhật Docker: ' + e);
    }
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
      showToast('Cập nhật cấu hình Git thành công!');
      setTimeout(fetchStatus, 1000);
    } catch (e) {
      showToast('Lỗi cấu hình Git: ' + e);
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
      tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; color:#9ca3af; padding:15px;">Đang lần lượt đo kiểm các trạm toàn cầu...</td></tr>';

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
          row.innerHTML = `
            <td><strong>${r.flag}</strong> ${r.name}</td>
            <td style="font-family:'JetBrains Mono'; color:#00d2ff; font-weight:700;">${r.speed_mb_s} MB/s</td>
            <td style="font-family:'JetBrains Mono'; color:#9ca3af;">${r.latency_ms} ms</td>
          `;
          tbody.appendChild(row);
        });
        showToast('Đã đo xong toàn bộ các Data Center!');
      } catch (e) {
        tbody.innerHTML = `<tr><td colspan="3" style="color:#ef4444;">Lỗi: ${e}</td></tr>`;
      } finally {
        btn.disabled = false;
        btn.innerText = '▶ Bắt đầu đo';
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
        btn.innerText = '▶ Bắt đầu đo';
      }
    }
  }

  async function loadLogs() {
    const box = document.getElementById('logsBox');
    box.innerText = 'Đang tải...';
    try {
      const res = await fetch('/api/logs');
      const data = await res.json();
      box.innerText = data.logs || 'Không có log.';
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      box.innerText = 'Không thể tải log: ' + e;
    }
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

  fetchStatus();
  loadLogs();
  setInterval(fetchStatus, 10000);
</script>

</body>
</html>
"""

class WarpAPIHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        if path == "/api/status":
            status = get_warp_status()
            self.send_json(status)
            return

        if path == "/api/regions":
            self.send_json(DATA_CENTERS)
            return

        if path == "/api/logs":
            _, logs, _ = run_cmd("journalctl -u warp-svc -n 40 --no-pager 2>/dev/null", timeout=5)
            self.send_json({"logs": logs})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

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

        if path == "/api/toggle-docker":
            enable = req_data.get("enable", True)
            conf_dir = "/etc/systemd/system/docker.service.d"
            conf_path = f"{conf_dir}/http-proxy.conf"
            status = get_warp_status()
            port = status.get("port", 40000)

            if enable:
                os.makedirs(conf_dir, exist_ok=True)
                content = f"""[Service]
Environment="HTTP_PROXY=socks5://127.0.0.1:{port}"
Environment="HTTPS_PROXY=socks5://127.0.0.1:{port}"
Environment="NO_PROXY=localhost,127.0.0.1,docker.io,*.docker.io,*.docker.com,production.cloudflare.docker.com,103.186.100.0/23"
"""
                with open(conf_path, "w") as f:
                    f.write(content)
            else:
                if os.path.exists(conf_path):
                    os.remove(conf_path)

            run_cmd("systemctl daemon-reload && systemctl restart docker")
            self.send_json({"success": True, "docker_proxy": enable})
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
                # Keep original order
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

        self.send_response(404)
        self.end_headers()

def main():
    print("=" * 64)
    print("  CLOUDFLARE WARP WEB DASHBOARD & REST API")
    print(f"  Listening on: http://{HOST}:{PORT}")
    print(f"  Access locally: http://127.0.0.1:{PORT}")
    print("=" * 64)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), WarpAPIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
            sys.exit(0)

if __name__ == "__main__":
    main()
