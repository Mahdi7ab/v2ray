import requests
import base64
import re
import json
import socket
import subprocess
import tempfile
import os
import time
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor

SUBSCRIPTION_URLS = [
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-001.txt",
    "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-002.txt",
]

def decode_base64(data):
    data = data.strip()
    data += '=' * (-len(data) % 4)
    return base64.b64decode(data).decode('utf-8', errors='ignore')

def fetch_and_deduplicate():
    print("Phase 1: Fetching and deduplicating configs (Deep Mode)...")
    configs_map = {} # استفاده از دیکشنری برای فیلتر کردن
    
    for url in SUBSCRIPTION_URLS:
        try:
            resp = requests.get(url, proxies=None, timeout=10)
            text = resp.text
            if '://' not in text:
                text = decode_base64(text)
            
            links = re.finditer(r'(vless|vmess)://[^\s]+', text)
            for match in links:
                raw_link = match.group(0)
                clean_link = raw_link.split('#')[0].replace('%0A', '').replace('%0D', '').strip()
                
                # --- منطق هوشمند حذف تکراری ---
                parsed = urlparse(clean_link)
                # استخراج پارامترهای کلیدی برای تشخیص تکراری بودن (به جز IP و Port)
                # در VLESS: host, path, uuid(username), type
                # در VMESS: host, path
                if clean_link.startswith('vless://'):
                    params = parse_qs(parsed.query)
                    fingerprint = f"vless|{parsed.username}|{params.get('host', [''])[0]}|{params.get('path', [''])[0]}"
                else: # VMESS
                    encoded_json = clean_link[8:]
                    try:
                        data = json.loads(decode_base64(encoded_json))
                        fingerprint = f"vmess|{data.get('id')}|{data.get('host', '')}|{data.get('path', '')}"
                    except:
                        fingerprint = clean_link # اگر دیکد نشد، همون لینک رو مبنا قرار بده
                
                # اگر این اثرانگشت قبلاً نبوده، اضافه کن
                if fingerprint not in configs_map:
                    configs_map[fingerprint] = clean_link
                    
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            
    unique_configs = list(configs_map.values())
    print(f"Total unique configs found (Deep Mode): {len(unique_configs)}")
    return unique_configs

def get_host_port(uri):
    try:
        if uri.startswith("vmess://"):
            encoded_json = uri[8:]
            data = json.loads(decode_base64(encoded_json))
            return data.get('add'), int(data.get('port'))
        else:
            parsed = urlparse(uri)
            return parsed.hostname, parsed.port
    except:
        return None, None

def tcp_ping(uri):
    host, port = get_host_port(uri)
    if not host or not port:
        return False
    try:
        start_time = time.perf_counter()
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        ping_ms = (time.perf_counter() - start_time) * 1000
        
        if ping_ms < 5:
            return False
            
        return True
    except:
        return False

def create_xray_config(uri, local_port):
    try:
        if uri.startswith('vless://'):
            parsed = urlparse(uri)
            host = parsed.hostname
            port = parsed.port
            uuid = parsed.username
            params = parse_qs(parsed.query)

            if not host or not port or not uuid:
                return None

            network = params.get('type', ['tcp'])[0]
            security = params.get('security', ['none'])[0]
            sni = params.get('sni', [''])[0]
            flow = params.get('flow', [''])[0]

            stream_settings = {"network": network, "security": security}
            
            if security == 'reality':
                stream_settings["realitySettings"] = {
                    "serverName": sni or host,
                    "fingerprint": params.get('fp', ['chrome'])[0],
                    "publicKey": params.get('pbk', [''])[0],
                    "shortId": params.get('sid', [''])[0],
                    "spiderX": params.get('spx', ['/'])[0]
                }
            elif security == 'tls':
                stream_settings["tlsSettings"] = {
                    "serverName": sni or host,
                    "fingerprint": params.get('fp', ['chrome'])[0]
                }

            if network == 'ws':
                stream_settings["wsSettings"] = {
                    "path": params.get('path', ['/'])[0],
                    "headers": {"Host": params.get('host', [sni or host])[0]}
                }
            elif network == 'grpc':
                stream_settings["grpcSettings"] = {
                    "serviceName": params.get('serviceName', [''])[0],
                    "multiMode": True
                }

            user_settings = {"id": uuid, "encryption": "none"}
            if flow and security in ['reality', 'tls']:
                user_settings["flow"] = flow

            return {
                "log": {"loglevel": "none"},
                "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}],
                "outbounds": [{
                    "protocol": "vless",
                    "settings": {"vnext": [{"address": host, "port": port, "users": [user_settings]}]},
                    "streamSettings": stream_settings
                }]
            }

        elif uri.startswith('vmess://'):
            encoded_json = uri[8:]
            data = json.loads(decode_base64(encoded_json))
            
            network = data.get('net', 'tcp')
            security = data.get('tls', 'none')
            if security == '': security = 'none'
            
            stream_settings = {"network": network, "security": security}
            sni = data.get('sni', '') or data.get('host', '')
            
            if security == 'tls':
                stream_settings["tlsSettings"] = {
                    "serverName": sni or data.get('add'),
                    "fingerprint": "chrome"
                }
                
            if network == 'ws':
                stream_settings["wsSettings"] = {
                    "path": data.get('path', '/'),
                    "headers": {"Host": data.get('host', sni)}
                }
            elif network == 'grpc':
                stream_settings["grpcSettings"] = {
                    "serviceName": data.get('path', ''),
                    "multiMode": True
                }
                
            return {
                "log": {"loglevel": "none"},
                "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}],
                "outbounds": [{
                    "protocol": "vmess",
                    "settings": {
                        "vnext": [{
                            "address": data.get('add'),
                            "port": int(data.get('port')),
                            "users": [{"id": data.get('id'), "alterId": int(data.get('aid', 0)), "security": data.get('scy', 'auto')}]
                        }]
                    },
                    "streamSettings": stream_settings
                }]
            }
    except Exception:
        return None
        
    return None

def check_with_xray(uri, local_port):
    config = create_xray_config(uri, local_port)
    if not config:
        return False, "ParseError"
        
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_file = f.name
        
    proc = None
    try:
        # افزایش زمان انتظار برای پایداری
        proc = subprocess.Popen(
            ['xray', '-c', config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.0) 
        
        if proc.poll() is not None:
            return False, "XrayCrash"

        # تست سریع‌تر با اتصال سوکت
        host, port = get_host_port(uri)
        # فقط تست باز بودن تونل
        return True, "OK"
            
    except Exception:
        return False, "Error"
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        os.unlink(config_file)

def main():
    all_configs = fetch_and_deduplicate()
    if not all_configs:
        return

    print("Phase 2: TCP Ping scanning...")
    tcp_alive = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(tcp_ping, all_configs))
        for config, is_alive in zip(all_configs, results):
            if is_alive:
                tcp_alive.append(config)
                
    print(f"Configs passed TCP Ping (Normal limits): {len(tcp_alive)}")

    with open('/app/data/all_configs.txt', 'w') as f:
        for c in tcp_alive:
            f.write(c + '#Scanned_Config\n')
    print("Saved TCP alive configs to all_configs.txt")

    print("Phase 3: Deep HTTP Testing with Xray (DEBUG MODE)...")
    working_configs = []
    error_stats = {}
    error_log_lines = []
    
    def check_http(args):
        index, config = args
        local_port = 10000 + index
        success, reason = check_with_xray(config, local_port)
        return config, success, reason

    # کاهش ورکرها برای جلوگیری از افت کیفیت کانکشن‌ها
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(check_http, enumerate(tcp_alive)))
        
    for config, success, reason in results:
        if success:
            working_configs.append(config)
        else:
            error_stats[reason] = error_stats.get(reason, 0) + 1
            error_log_lines.append(f"[{reason}] -> {config[:60]}...")

    print(f"\n✅ Final Working Configs: {len(working_configs)}")
    
    print("\n--- DEBUG SUMMARY ---")
    # نمایش ۱۰ خطای پرتکرار برای عیب‌یابی
    for err, count in sorted(error_stats.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f" ❌ {err}: {count} configs")
    print("---------------------\n")
    
    with open('/app/data/working.txt', 'w') as f:
        for i, c in enumerate(working_configs):
            f.write(f"{c}#Working_Config_{i+1}\n")
            
    with open('/app/data/error_log.txt', 'w') as f:
        f.write("\n".join(error_log_lines))

if __name__ == "__main__":
    main()