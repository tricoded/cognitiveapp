# test_backend_connection.py
import requests
import json
from datetime import datetime

API = "http://localhost:8000"

print("=" * 60)
print("🔍 BACKEND CONNECTION DIAGNOSTIC")
print("=" * 60)

# Test 1: Health check
print("\n[1] Testing /health endpoint...")
try:
    r = requests.get(f"{API}/health", timeout=4)
    print(f"✅ Status: {r.status_code}")
    print(f"Response: {r.json()}")
except Exception as e:
    print(f"❌ FAILED: {e}")
    exit(1)

# Test 2: Create a test log
print("\n[2] Creating test log...")
payload = {
    "tool_name": "TestTool",
    "category": "Testing",
    "duration_mins": 5,
    "quality": "active",
    "notes": f"Test at {datetime.now()}"
}
try:
    r = requests.post(f"{API}/ai-usage/", json=payload, timeout=4)
    print(f"✅ Status: {r.status_code}")
    log_data = r.json()
    print(f"Response: {json.dumps(log_data, indent=2)}")
    test_log_id = log_data.get("id")
except Exception as e:
    print(f"❌ FAILED: {e}")
    exit(1)

# Test 3: Fetch today's logs
print("\n[3] Fetching /ai-usage/today...")
try:
    r = requests.get(f"{API}/ai-usage/today", timeout=4)
    print(f"✅ Status: {r.status_code}")
    today_data = r.json()
    print(f"Total mins today: {today_data.get('total_mins')}")
    print(f"Logs count: {len(today_data.get('logs', []))}")
    print(f"Response: {json.dumps(today_data, indent=2)}")
except Exception as e:
    print(f"❌ FAILED: {e}")
    exit(1)

# Test 4: Fetch all logs (last 30 days)
print("\n[4] Fetching /ai-usage/ (all logs)...")
try:
    r = requests.get(f"{API}/ai-usage/?days=30", timeout=4)
    print(f"✅ Status: {r.status_code}")
    all_logs = r.json()
    print(f"Total logs: {len(all_logs)}")
    if all_logs:
        print(f"Most recent log:")
        print(json.dumps(all_logs[0], indent=2))
except Exception as e:
    print(f"❌ FAILED: {e}")
    exit(1)

# Test 5: Fetch stats
print("\n[5] Fetching /ai-usage/stats...")
try:
    r = requests.get(f"{API}/ai-usage/stats?days=7", timeout=4)
    print(f"✅ Status: {r.status_code}")
    stats = r.json()
    print(f"Response: {json.dumps(stats, indent=2)}")
except Exception as e:
    print(f"❌ FAILED: {e}")
    exit(1)

print("\n" + "=" * 60)
print("✅ ALL TESTS PASSED - Backend is working!")
print("=" * 60)
