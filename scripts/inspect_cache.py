import json
import sys
import time

sys.path.insert(0, r"C:\Kapish\AI-CFO-Agent")

from app.core.cache import get_redis  # adjust if you named it differently

r = get_redis()
assert r, "Redis not configured — check UPSTASH_REDIS_REST_URL/TOKEN in .env"
print("PING:", r.ping())

# SCAN (not KEYS) — Upstash-friendly, non-blocking
cursor, keys = r.execute(["SCAN", "0", "MATCH", "dashboard:user:*", "COUNT", "100"])[:2]
while True:
    for key in keys:
        raw = r.get(key)
        blob = json.loads(raw) if isinstance(raw, str) else raw
        print(f"\n{key}   TTL={r.ttl(key)}s   {len(raw) if isinstance(raw, str) else len(json.dumps(raw))} bytes")
        for month, entry in (blob or {}).items():
            left = entry["exp"] - time.time()
            payload = entry["payload"]
            print(f"    {month!r}: expires in {left:5.1f}s | "
                  f"revenue={payload.get('total_revenue')} | "
                  f"{len(payload.get('trend_data', []))} trend points | "
                  f"{len(payload.get('categories', []))} categories")
    if cursor == 0 or cursor == "0":
        break
    cursor, keys = r.execute(["SCAN", cursor, "MATCH", "dashboard:user:*", "COUNT", "100"])[:2]