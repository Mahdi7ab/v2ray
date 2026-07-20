import requests
import base64
import re
import json
import socket
import subprocess
import tempfile
import os
import time
import threading
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/V2RayRoot/V2RayConfig/refs/heads/main/Config/vless.txt",
    "https://raw.githubusercontent.com/MahanKenway/Freedom-V2Ray/refs/heads/main/configs/vless.txt",
    # "https://raw.githubusercontent.com/Delta-Kronecker/V2ray-Config/refs/heads/main/config/protocols/vless.txt",
    "https://raw.githubusercontent.com/Mahdi7ab/v2ray/refs/heads/main/free-configs/all_configs.txt",
]

MAX_WORKING_CONFIGS = 100
MAX_GEMINI_CONFIGS = 10

def decode_base64(data):
    data = data.strip()
    data += '=' * (-len(data) % 4)
    return base64.b64decode(data).decode('utf-8', errors='ignore')

def get_host_port(uri):
    try:
        if uri.startswith("vmess://"):
            data = json.loads(decode_base64(uri[8:]))
            return data.get('add'), int(data.get('port'))
        else:
            parsed = urlparse(uri)
            return parsed.hostname, parsed.port
    except:
        return None, None

def fetch_and_deduplicate():
    print("\n[Phase 1] Fetching configs from sources...")
    raw_configs = set()
    
    for url in SUBSCRIPTION_URLS:
        try:
            resp = requests.get(url, timeout=10)
            text = resp.text
            if '://' not in text: text = decode_base64(text)
            
            links = re.finditer(r'(vless|vmess)://[^\s]+', text)
            for match in links: raw_configs.add(match.group(0))
            print(f" -> Fetched from {url[:35]}... OK")
        except Exception as e:
            print(f" -> Failed to fetch {url[:35]}... Error")
            
    print(f"\n=> Total Raw Configs Collected: {len(raw_configs)}")
    print("[Phase 1.5] Strict IP:Port Deduplication...")

    unique_ip_ports = set()
    final_configs = []
    
    for link in raw_configs:
        clean_link = link.split('#')[0].replace('%0A', '').replace('%0D', '').replace('%20', '').strip()
        host, port = get_host_port(clean_link)
        if not host or not port: continue
            
        ip_port = f"{host}:{port}"
        # فقط در صورتی که این ترکیب IP و Port قبلا نبوده، اضافه کن
        if ip_port not in unique_ip_ports:
            unique_ip_ports.add(ip_port)
            final_configs.append(clean_link)
            
    print(f"=> Removed {len(raw_configs) - len(final_configs)} duplicates. Unique IP:Ports remaining: {len(final_configs)}")
    return final_configs

def tcp_ping(uri):
    host, port = get_host_port(uri)
    if not host or not port: return False
    try:
        start = time.perf_counter()
        sock = socket.create_connection((host, port), timeout=1.5)
        sock.close()
        ping_ms = (time.perf_counter() - start) * 1000
        if 5 <= ping_ms <= 800: return True
        return False
    except: return False

def create_xray_config(uri, local_port):
    try:
        if uri.startswith('vless://'):
            parsed = urlparse(uri)
            params = parse_qs(parsed.query)
            security = params.get('security', ['none'])[0]
            network = params.get('type', ['tcp'])[0]
            stream_settings = {"network": network, "security": security}
            if security == 'reality':
                stream_settings["realitySettings"] = {"serverName": params.get('sni', [parsed.hostname])[0], "fingerprint": params.get('fp', ['chrome'])[0], "publicKey": params.get('pbk', [''])[0], "shortId": params.get('sid', [''])[0], "spiderX": params.get('spx', ['/'])[0]}
            elif security == 'tls':
                stream_settings["tlsSettings"] = {"serverName": params.get('sni', [parsed.hostname])[0]}
            if network == 'ws': stream_settings["wsSettings"] = {"path": params.get('path', ['/'])[0], "headers": {"Host": params.get('host', [parsed.hostname])[0]}}
            elif network == 'grpc': stream_settings["grpcSettings"] = {"serviceName": params.get('serviceName', [''])[0], "multiMode": True}

            return {"log": {"loglevel": "none"}, "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}], "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": parsed.hostname, "port": parsed.port, "users": [{"id": parsed.username, "encryption": "none", "flow": params.get('flow', [''])[0]}]}]}, "streamSettings": stream_settings}]}
        elif uri.startswith('vmess://'):
            data = json.loads(decode_base64(uri[8:]))
            network = data.get('net', 'tcp')
            security = data.get('tls', 'none')
            if security == '': security = 'none'
            stream_settings = {"network": network, "security": security}
            sni = data.get('sni', '') or data.get('host', '')
            if security == 'tls': stream_settings["tlsSettings"] = {"serverName": sni or data.get('add')}
            if network == 'ws': stream_settings["wsSettings"] = {"path": data.get('path', '/'), "headers": {"Host": data.get('host', sni)}}
            elif network == 'grpc': stream_settings["grpcSettings"] = {"serviceName": data.get('path', ''), "multiMode": True}

            return {"log": {"loglevel": "none"}, "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}], "outbounds": [{"protocol": "vmess", "settings": {"vnext": [{"address": data.get('add'), "port": int(data.get('port')), "users": [{"id": data.get('id'), "alterId": int(data.get('aid', 0)), "security": data.get('scy', 'auto')}]}]}, "streamSettings": stream_settings}]}
    except: return None
    return None

def check_with_xray(uri, local_port):
    config = create_xray_config(uri, local_port)
    if not config: return False, False, "ParseError"
        
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_file = f.name
        
    proc = None
    try:
        proc = subprocess.Popen(['xray', '-c', config_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(1.2) 
        if proc.poll() is not None: return False, False, "XrayCrash"

        proxies = {'http': f'http://127.0.0.1:{local_port}', 'https': f'http://127.0.0.1:{local_port}'}
        
        # ۱. تست اولیه (تایید کارکرد کلی کانفیگ)
        resp = requests.get('http://www.gstatic.com/generate_204', proxies=proxies, timeout=4)
        if resp.status_code != 204:
            return False, False, f"HTTP_Status_{resp.status_code}"
            
        # ۲. تست تخصصی سایت جمینای
        gemini_ok = False
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            # تایم‌اوت را برای جمینای کمی بیشتر می‌دهیم
            g_resp = requests.get('https://gemini.google.com/app', proxies=proxies, headers=headers, timeout=6)
            if g_resp.status_code == 200:
                gemini_ok = True
        except:
            pass # خطا در باز کردن جمینای ولی کانفیگ سالمه

        return True, gemini_ok, "OK"
            
    except requests.exceptions.Timeout: return False, False, "Timeout"
    except requests.exceptions.ConnectionError: return False, False, "Connection Refused (DPI)"
    except Exception: return False, False, "Error"
    finally:
        if proc: proc.terminate(); proc.wait() 
        try: os.unlink(config_file)
        except: pass

def main():
    all_configs = fetch_and_deduplicate()
    if not all_configs: return

    print("\n[Phase 2] TCP Ping scanning (Filtering dead IPs)...")
    tcp_alive = []
    total_pinged = 0
    with ThreadPoolExecutor(max_workers=100) as executor:
        for is_alive, config in zip(executor.map(tcp_ping, all_configs), all_configs):
            total_pinged += 1
            if is_alive: tcp_alive.append(config)
            
            # نمایش پیشرفت هر 100 کانفیگ
            if total_pinged % 100 == 0 or total_pinged == len(all_configs):
                print(f" -> Pinged: {total_pinged}/{len(all_configs)} | Passed: {len(tcp_alive)}")

    with open('/app/data/all_configs.txt', 'w') as f:
        for i, c in enumerate(tcp_alive): f.write(f"{c}#Pinged_{i+1}\n")

    print(f"\n[Phase 3] Deep HTTP & Gemini Check (Max {MAX_WORKING_CONFIGS} Normal, {MAX_GEMINI_CONFIGS} Gemini)...")
    
    state_lock = threading.Lock()
    working_configs = []
    gemini_configs = []
    error_stats = {}
    
    def check_http_task(args):
        index, config = args
        # جلوگیری از تست اضافه اگر ظرفیت پر شده بود
        with state_lock:
            if len(working_configs) >= MAX_WORKING_CONFIGS and len(gemini_configs) >= MAX_GEMINI_CONFIGS:
                return config, False, False, "LimitReached"
                
        local_port = 15000 + index 
        success, gemini_ok, reason = check_with_xray(config, local_port)
        return config, success, gemini_ok, reason

    completed = 0
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(check_http_task, (i, config)): config for i, config in enumerate(tcp_alive)}
        
        for future in as_completed(futures):
            completed += 1
            config, success, gemini_ok, reason = future.result()
            
            if success:
                with state_lock:
                    if len(working_configs) < MAX_WORKING_CONFIGS:
                        working_configs.append(config)
                    if gemini_ok and len(gemini_configs) < MAX_GEMINI_CONFIGS:
                        gemini_configs.append(config)
                        
                    w_count = len(working_configs)
                    g_count = len(gemini_configs)
                
                print(f" [★] Success! Working: {w_count}/{MAX_WORKING_CONFIGS} | Gemini: {g_count}/{MAX_GEMINI_CONFIGS}")
                
                # خروج هوشمند اگر هر دو لیست پر شدند
                if w_count >= MAX_WORKING_CONFIGS and g_count >= MAX_GEMINI_CONFIGS:
                    print("\n🎯 Targets Reached! Stopping remaining Xray tasks...")
                    break 
            else:
                if reason != "LimitReached":
                    error_stats[reason] = error_stats.get(reason, 0) + 1
                    
            if completed % 20 == 0:
                print(f" -> Testing Progress: {completed}/{len(tcp_alive)}...")

    print("\n" + "="*30)
    print(f"✅ Final General Working: {len(working_configs)}")
    print(f"🚀 Final Gemini Friendly: {len(gemini_configs)}")
    print("="*30)
    
    # 1. ذخیره کانفیگ‌های عمومی
    final_text = "\n".join([f"{c}#Working_Real_{i+1}" for i, c in enumerate(working_configs)])
    with open('/app/data/working.txt', 'w') as f:
        f.write(base64.b64encode(final_text.encode('utf-8')).decode('utf-8') if final_text.strip() else "")
        
    # 2. ذخیره کانفیگ‌های مخصوص جمینای
    gemini_text = "\n".join([f"{c}#Gemini_Premium_{i+1}" for i, c in enumerate(gemini_configs)])
    with open('/app/data/gemini_configs.txt', 'w') as f:
        f.write(base64.b64encode(gemini_text.encode('utf-8')).decode('utf-8') if gemini_text.strip() else "")
        
if __name__ == "__main__":
    main()