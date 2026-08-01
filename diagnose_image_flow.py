import sys
import os
import socket
import urllib.request
import urllib.error
import json
import time

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "data", "config.toml")
DEFAULTS_PATH = os.path.join(os.path.dirname(__file__), "config.defaults.toml")

def load_config():
    """Load config.toml manually to avoid dependency issues."""
    path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else DEFAULTS_PATH
    print(f"[*] Loading config from: {path}")
    
    # Simple TOML parser using built-in tomllib (Python 3.11+)
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        # Fallback manual parser for older Python versions
        config = {}
        current_section = None
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[["):
                    # Table array
                    section = line.strip("[]")
                    current_section = []
                    config.setdefault(section, current_section)
                    current_item = {}
                    current_section.append(current_item)
                elif line.startswith("["):
                    # Regular table
                    current_section = line.strip("[]")
                    config[current_section] = {}
                elif "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if isinstance(config.get(current_section), list):
                        config[current_section][-1][k] = v
                    elif isinstance(config.get(current_section), dict):
                        config[current_section][k] = v
        return config

def check_dns(host):
    print(f"\n[*] Step 1: Testing DNS resolution for '{host}'...")
    try:
        ip = socket.gethostbyname(host)
        print(f"  [+] Resolved successfully: {host} -> {ip}")
        return True, ip
    except Exception as e:
        print(f"  [-] DNS Resolution FAILED for '{host}': {e}")
        return False, None

def check_port(host, port, timeout=5):
    print(f"\n[*] Step 2: Testing direct TCP connection to {host}:{port}...")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        print(f"  [+] Direct TCP connection to {host}:{port} succeeded.")
        return True
    except Exception as e:
        print(f"  [-] Direct TCP connection to {host}:{port} FAILED: {e}")
        return False

def check_proxy(proxy_url):
    print(f"\n[*] Step 3: Checking egress proxy configuration...")
    if not proxy_url:
        print("  [-] No egress proxy configured.")
        return False
    print(f"  [+] Configured proxy: {proxy_url}")
    
    # Parse proxy host/port
    try:
        from urllib.parse import urlparse
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port
        if host and port:
            print(f"  [*] Testing connection to proxy server {host}:{port}...")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.close()
            print(f"  [+] Connection to proxy server {host}:{port} succeeded.")
            return True
        else:
            print("  [-] Invalid proxy format.")
            return False
    except Exception as e:
        print(f"  [-] Connection to proxy server FAILED: {e}")
        print("  [!] Hint: If your proxy (e.g., socks5://warp:1080) is down, all outbound requests will fail.")
        return False

def test_api_call(base_url, api_key, model, prompt="a test image", proxy_url=None):
    print(f"\n[*] Step 4: Testing API call to upstream model '{model}'...")
    
    # Prepare URL and headers
    url = f"{base_url.rstrip('/')}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024"
    }
    
    print(f"  [*] Endpoint: {url}")
    print(f"  [*] API Key: {api_key[:10]}...{api_key[-5:] if len(api_key) > 10 else ''}")
    
    # Setup handlers (with proxy if needed)
    handlers = []
    if proxy_url:
        print(f"  [*] Using proxy for request: {proxy_url}")
        # Note: urllib doesn't natively support SOCKS easily, but we can configure HTTP proxy
        if proxy_url.startswith("http"):
            proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
            handlers.append(proxy_handler)
    
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    
    start_time = time.time()
    try:
        with opener.open(req, timeout=30) as response:
            res_body = response.read().decode('utf-8')
            elapsed = time.time() - start_time
            print(f"  [+] API call SUCCEEDED in {elapsed:.2f}s!")
            try:
                res_json = json.loads(res_body)
                print(f"  [+] Response data: {json.dumps(res_json, indent=2)}")
            except:
                print(f"  [+] Raw Response: {res_body[:300]}")
            return True
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start_time
        err_body = e.read().decode('utf-8') if e.fp else ""
        print(f"  [-] API call FAILED with HTTP Status {e.code} in {elapsed:.2f}s")
        print(f"  [-] Error Response: {err_body}")
        
        # Actionable hints
        if e.code == 401:
            print("  [!] Diagnostic Hint: HTTP 401 Unauthorized. Your API key is invalid or expired.")
        elif e.code == 402:
            print("  [!] Diagnostic Hint: HTTP 402 Payment Required. The upstream account has run out of balance.")
        elif e.code == 429:
            print("  [!] Diagnostic Hint: HTTP 429 Rate Limit. You are making too many requests or hit the concurrent limit.")
        elif e.code >= 500:
            print(f"  [!] Diagnostic Hint: HTTP {e.code} Server Error. The upstream service is currently down or experiencing internal failures.")
        return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  [-] API call FAILED with error in {elapsed:.2f}s: {e}")
        return False

def main():
    try:
        config = load_config()
    except Exception as e:
        print(f"[-] Failed to load config: {e}")
        sys.exit(1)
        
    # Get egress proxy
    proxy_url = None
    if "proxy" in config and "egress" in config["proxy"]:
        proxy_url = config["proxy"]["egress"].get("proxy_url")
    elif "proxy.egress" in config:
        proxy_url = config["proxy.egress"].get("proxy_url")
        
    # Find Pidoi channel config
    pidoi_channel = None
    channels = config.get("providers.newapi.channels", [])
    # Sometimes loaded under separate table arrays
    if not channels and "providers" in config and "newapi" in config["providers"] and "channels" in config["providers"]["newapi"]:
        channels = config["providers"]["newapi"]["channels"]
    
    # Try manual traversal for table arrays parsed differently
    if not channels:
        for k, v in config.items():
            if "channels" in k and isinstance(v, list):
                channels = v
                break
                
    for chan in channels:
        if chan.get("id") == "pidoi" or "pidoi" in chan.get("name", "").lower():
            pidoi_channel = chan
            break
            
    if not pidoi_channel:
        print("[-] FAILED to find 'pidoi' channel configuration in config.toml!")
        sys.exit(1)
        
    base_url = pidoi_channel.get("base_url")
    api_key = pidoi_channel.get("api_key")
    
    print("\n" + "=" * 60)
    print(" Upstream Channel Diagnostic tool (Pidoi / gpt-image-2)")
    print("=" * 60)
    print(f"Target Upstream: {base_url}")
    print(f"Target Model:    gpt-image-2")
    print(f"Proxy Config:    {proxy_url}")
    print("=" * 60)
    
    # Extract host name for DNS
    from urllib.parse import urlparse
    host = urlparse(base_url).hostname
    if not host:
        print("[-] Invalid base_url.")
        sys.exit(1)
        
    # Run tests
    dns_ok, ip = check_dns(host)
    port_ok = check_port(host, 443)
    proxy_ok = check_proxy(proxy_url) if proxy_url else False
    
    # Run API test with and without proxy configurations
    print("\n--- Running API Generation Tests ---")
    test_api_call(base_url, api_key, "gpt-image-2")
    
    if proxy_url and proxy_ok:
        print("\n--- Running API Generation Test (via proxy) ---")
        test_api_call(base_url, api_key, "gpt-image-2", proxy_url=proxy_url)

if __name__ == "__main__":
    main()
