"""
Test CBI access using PAC file approach + requests library (no browser).
This tests whether the IP itself is blocked or the browser is the problem.
"""
import time
import requests
import socket

print("=" * 60)
print("Step 1: Check DNS resolution for cbi.ir")
print("=" * 60)
try:
    ip = socket.gethostbyname('www.cbi.ir')
    print(f"  www.cbi.ir resolves to: {ip}")
except Exception as e:
    print(f"  DNS error: {e}")

print()
print("=" * 60)
print("Step 2: Direct HTTP request (NO proxy)")
print("=" * 60)
try:
    session = requests.Session()
    session.trust_env = False  # Ignore system proxy
    session.verify = False
    resp = session.get(
        'https://www.cbi.ir/EstelamSayad/24090.aspx',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8',
        },
        timeout=20
    )
    print(f"  Status: {resp.status_code}")
    text = resp.text[:500]
    if 'Request Rejected' in text:
        print("  Result: WAF BLOCKED")
    elif 'صيادی' in text or 'txtChequeNumber' in text:
        print("  Result: PAGE LOADED OK!")
    else:
        print(f"  Result: Got response ({len(resp.text)} bytes)")
        print(f"  Snippet: {text[:200]}")
except Exception as e:
    print(f"  Error: {e}")

print()
print("=" * 60)
print("Step 3: Request THROUGH Hiddify proxy")
print("=" * 60)
try:
    session2 = requests.Session()
    session2.trust_env = False
    session2.verify = False
    session2.proxies = {'http': 'http://127.0.0.1:12334', 'https': 'http://127.0.0.1:12334'}
    resp2 = session2.get(
        'https://www.cbi.ir/EstelamSayad/24090.aspx',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'fa-IR,fa;q=0.9,en;q=0.8',
        },
        timeout=20
    )
    print(f"  Status: {resp2.status_code}")
    text2 = resp2.text[:500]
    if 'Request Rejected' in text2:
        print("  Result: WAF BLOCKED (as expected with foreign IP)")
    elif 'صيادی' in text2 or 'txtChequeNumber' in text2:
        print("  Result: PAGE LOADED OK!")
    else:
        print(f"  Result: Got response ({len(resp2.text)} bytes)")
        print(f"  Snippet: {text2[:200]}")
except Exception as e:
    print(f"  Error: {e}")

print()
print("=" * 60)
print("Step 4: Check our public IP (direct)")
print("=" * 60)
try:
    session3 = requests.Session()
    session3.trust_env = False
    resp3 = session3.get('https://api.ipify.org?format=json', timeout=10)
    print(f"  Direct IP: {resp3.json()}")
except Exception as e:
    print(f"  Error: {e}")

try:
    session4 = requests.Session()
    session4.trust_env = False
    session4.proxies = {'http': 'http://127.0.0.1:12334', 'https': 'http://127.0.0.1:12334'}
    resp4 = session4.get('https://api.ipify.org?format=json', timeout=10)
    print(f"  Via Hiddify: {resp4.json()}")
except Exception as e:
    print(f"  Error: {e}")
