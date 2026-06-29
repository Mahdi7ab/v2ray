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
    print("Phase 1: Fetching and deduplicating configs...")
    configs = set()
    proxies = None 
    
    for url in SUBSCRIPTION_URLS:
        try:
            resp = requests.get(url, proxies=proxies, timeout=10)
            text = resp.text
            if '://' not in text:
                text = decode_base64(text)
            
            links = re.finditer(r'(vless|vmess)://[^\s]+', text)
            for match in links:
                configs.add(match.group(0))
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            
    print(f"Total unique configs found: {len(configs)}")
    return list(configs)

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
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        return True
    except:
        return False

def create_xray_config(uri, local_port):
    """ساخت فایل کانفیگ با ورودی HTTP به جای SOCKS برای سازگاری کامل پایتون"""
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
        return False
        
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        config_file = f.name
        
    proc = None
    try:
        proc = subprocess.Popen(
            ['xray', '-c', config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.5) 
        
        # در صورتی که هسته Xray به خاطر ساختار خراب کانفیگ کرش کرده باشد
        if proc.poll() is not None:
            return False

        proxies = {
            'http': f'http://127.0.0.1:{local_port}',
            'https': f'http://127.0.0.1:{local_port}'
        }
        
        # استفاده از آدرس‌های بسیار سریع که خطای 204 (No Content) برمی‌گردانند
        test_urls = [
            'http://www.gstatic.com/generate_204',
            'http://cp.cloudflare.com/generate_204'
        ]
        
        for url in test_urls:
            try:
                response = requests.get(url, proxies=proxies, timeout=5)
                if response.status_code == 204:
                    return True
            except requests.exceptions.RequestException:
                continue
            
    except Exception:
        pass
    finally:
        if proc:
            proc.terminate()
            proc.wait() # آزادسازی کامل پورت‌ها
        try:
            os.unlink(config_file)
        except:
            pass
            
    return False

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
                
    print(f"Configs passed TCP Ping: {len(tcp_alive)}")

    with open('/app/data/all_configs.txt', 'w') as f:
        for c in tcp_alive:
            f.write(c + '\n')
    print("Saved TCP alive configs to all_configs.txt")

    print("Phase 3: Deep HTTP Testing with Xray...")
    
    def check_http(args):
        index, config = args
        local_port = 10000 + index
        if check_with_xray(config, local_port):
            return config
        return None

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(check_http, enumerate(tcp_alive)))
        working_configs = [c for c in results if c]

    print(f"\n✅ Final Working Configs: {len(working_configs)}")
    
    with open('/app/data/working.txt', 'w') as f:
        for c in working_configs:
            f.write(c + '\n')
            
if __name__ == "__main__":
    main()