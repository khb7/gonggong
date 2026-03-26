import urllib.request
import json
import traceback

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/bid/calculate',
    data=json.dumps({
        "bid_notice_id": "TEST-001",
        "overrides": {
            "base_price": 500000000,
            "client_name": "강원특별자치도교육청",
            "project_type": "건축공사",
            "region": "강원도"
        }
    }).encode('utf-8'),
    headers={'Content-Type': 'application/json'},
    method='POST'
)

try:
    with urllib.request.urlopen(req) as response:
        print("Success:", response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code)
    print("Body:", e.read().decode('utf-8'))
except Exception as e:
    print("Other Error:", e)
