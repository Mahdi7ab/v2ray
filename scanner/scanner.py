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
    # "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-004.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-008.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-015.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-016.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-023.txt",
    "https://github.com/ebrasha/free-v2ray-public-list/raw/refs/heads/main/separated-protocols-chunks/vless/EbraSha-Protocol-Chunks-vless-042.txt",
]

def decode_base64(data):
    data = data.strip()
    data += '=' * (-len(data) % 4)
    return base64.b64decode(data).decode('utf-8', errors='ignore')

def fetch_and_deduplicate():
    print("Phase 1: Fetching and deduplicating configs (Deep Mode)...")
    configs_map = {}
    
    for url in SUBSCRIPTION_URLS:
        try:
            resp = requests.get(url, timeout=10)
            text = resp.text
            if '://' not in text:
                text = decode_base64(text)
            
            links = re.finditer(r'(vless|vmess)://[^\s]+', text)
            for match in links:
                raw_link = match.group(0)
                clean_link = raw_link.split('#')[0].replace('%0A', '').replace('%0D', '').replace('%20', '').strip()
                
                parsed = urlparse(clean_link)
                if clean_link.startswith('vless://'):
                    params = parse_qs(parsed.query)
                    fingerprint = f"vless|{parsed.username}|{params.get('host', [''])[0]}|{params.get('path', [''])[0]}"
                else:
                    try:
                        data = json.loads(decode_base64(clean_link[8:]))
                        fingerprint = f"vmess|{data.get('id')}|{data.get('host', '')}|{data.get('path', '')}"
                    except:
                        fingerprint = clean_link
                
                if fingerprint not in configs_map:
                    configs_map[fingerprint] = clean_link
        except:
            pass
            
    return list(configs_map.values())

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

def tcp_ping(uri):
    host, port = get_host_port(uri)
    if not host or not port: return False
    try:
        start = time.perf_counter()
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        if (time.perf_counter() - start) * 1000 < 5: return False
        return True
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
                stream_settings["realitySettings"] = {
                    "serverName": params.get('sni', [parsed.hostname])[0],
                    "fingerprint": params.get('fp', ['chrome'])[0],
                    "publicKey": params.get('pbk', [''])[0],
                    "shortId": params.get('sid', [''])[0],
                    "spiderX": params.get('spx', ['/'])[0]
                }
            elif security == 'tls':
                stream_settings["tlsSettings"] = {"serverName": params.get('sni', [parsed.hostname])[0]}

            if network == 'ws':
                stream_settings["wsSettings"] = {"path": params.get('path', ['/'])[0], "headers": {"Host": params.get('host', [parsed.hostname])[0]}}
            elif network == 'grpc':
                stream_settings["grpcSettings"] = {"serviceName": params.get('serviceName', [''])[0], "multiMode": True}

            return {
                "log": {"loglevel": "none"},
                "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}],
                "outbounds": [{
                    "protocol": "vless",
                    "settings": {"vnext": [{"address": parsed.hostname, "port": parsed.port, "users": [{"id": parsed.username, "encryption": "none", "flow": params.get('flow', [''])[0]}]}]},
                    "streamSettings": stream_settings
                }]
            }
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

            return {
                "log": {"loglevel": "none"},
                "inbounds": [{"port": local_port, "protocol": "http", "settings": {"timeout": 0}}],
                "outbounds": [{
                    "protocol": "vmess",
                    "settings": {"vnext": [{"address": data.get('add'), "port": int(data.get('port')), "users": [{"id": data.get('id'), "alterId": int(data.get('aid', 0)), "security": data.get('scy', 'auto')}]}]},
                    "streamSettings": stream_settings
                }]
            }
    except: return None
    return None

def check_with_xray(uri, local_port):
    config = create_xray_config(uri, local_port)
    if not config: return False, "ParseError"
        
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_file = f.name
        
    proc = None
    try:
        proc = subprocess.Popen(['xray', '-c', config_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        # زمان صبر برای بالا آمدن هسته بیشتر شد
        time.sleep(2.0) 
        
        if proc.poll() is not None: 
            return False, "XrayCrash"

        proxies = {'http': f'http://127.0.0.1:{local_port}', 'https': f'http://127.0.0.1:{local_port}'}
        
        # تایم‌اوت تست HTTP به ۸ ثانیه افزایش یافت (سرورهای رایگان کند هستند)
        resp = requests.get('http://www.gstatic.com/generate_204', proxies=proxies, timeout=10)
        if resp.status_code == 204: 
            return True, "OK"
        else:
            return False, f"HTTP_Status_{resp.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "Timeout (Blocked/Too Slow)"
    except requests.exceptions.ConnectionError:
        return False, "Connection Refused (DPI Drop)"
    except Exception as e:
        return False, "Error"
    finally:
        if proc:
            proc.terminate()
            proc.wait() 
        try: os.unlink(config_file)
        except: pass

def main():
    all_configs = fetch_and_deduplicate()
    if not all_configs: return

    print("Phase 2: TCP Ping scanning...")
    tcp_alive = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(tcp_ping, all_configs))
        for config, is_alive in zip(all_configs, results):
            if is_alive: tcp_alive.append(config)
                
    print(f"Configs passed TCP Ping: {len(tcp_alive)}")

    with open('/app/data/all_configs.txt', 'w') as f:
        for i, c in enumerate(tcp_alive):
            f.write(f"{c}#Pinged_{i+1}\n")

    print("Phase 3: Deep HTTP Testing (Timeout Increased)...")
    
    working_configs = []
    error_stats = {}
    
    def check_http(args):
        index, config = args
        local_port = 15000 + index 
        success, reason = check_with_xray(config, local_port)
        return config, success, reason

    # تعداد ورکرها روی ۸ برای تعادل بین سرعت و پایداری
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(check_http, enumerate(tcp_alive)))
        
    for config, success, reason in results:
        if success:
            working_configs.append(config)
        else:
            error_stats[reason] = error_stats.get(reason, 0) + 1

    print(f"\n✅ Final REAL Working Configs: {len(working_configs)}")
    
    print("\n--- DPI & ERROR SUMMARY ---")
    for err, count in sorted(error_stats.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f" ❌ {err}: {count} configs")
    print("---------------------------\n")
    
    final_output = []
    for i, c in enumerate(working_configs):
        final_output.append(f"{c}#Working_Real_{i+1}")
        
    final_text = "\n".join(final_output)
    
    if final_text.strip():
        b64_encoded = base64.b64encode(final_text.encode('utf-8')).decode('utf-8')
    else:
        b64_encoded = ""
        
    with open('/app/data/working.txt', 'w') as f:
        f.write(b64_encoded)
        
if __name__ == "__main__":
    main()