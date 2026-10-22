"""Compare /api/dashboard/overview: cache miss vs hit vs cache disabled."""
import os
import statistics
import sys
import time

import requests
from dotenv import load_dotenv

# Running this file as `python scripts/bench_dashboard.py` puts scripts/ on
# sys.path, not the repo root — so `import app` (needed to reach the cache
# helpers) would fail. Put the repo root on the path explicitly.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
# .env is resolved relative to cwd by pydantic-settings; load it by absolute
# path so the script works from any working directory.
load_dotenv(os.path.join(REPO_ROOT, ".env"))

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "test@example.com"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "password123"

login = requests.post(f"{BASE}/api/auth/login",
                      json={"email": EMAIL, "password": PASSWORD}, timeout=30).json()
token, uid = login["token"], login["user"]["id"]
H = {"Authorization": f"Bearer {token}"}
URL = f"{BASE}/api/dashboard/overview?user_id={uid}"

def timed():
    t = time.perf_counter()
    code = requests.get(URL, headers=H, timeout=60).status_code
    return (time.perf_counter() - t) * 1000, code

def clear_cache():
    # from your shell instead:  python -c "from app.api.dashboard import _cache_key; from app.core.cache import cache_delete; cache_delete(_cache_key(1))"
    from app.api.dashboard import _cache_key
    from app.core.cache import cache_delete
    cache_delete(_cache_key(uid))

def report(label, xs):
    s = sorted(xs)
    print(f"{label:<28} p50={statistics.median(xs):7.1f}ms  "
          f"p95={s[int(len(s)*0.95)]:7.1f}ms  n={len(xs)}")

# warmup (also wakes a sleeping Render instance — do this before measuring!)
timed()

# A. cold/miss: delete the key before every request
miss = []
for _ in range(10):
    clear_cache()
    ms, code = timed()
    assert code == 200, code
    miss.append(ms)

# B. hit: one populate, then 20 reads inside the TTL
clear_cache()
timed()
hit = []
for _ in range(20):
    ms, code = timed()
    assert code == 200, code
    hit.append(ms)

report("MISS (recompute + Redis)", miss)
report("HIT (served from cache)", hit)
print("\nFor 'cache disabled' numbers: remove UPSTASH_REDIS_* from .env,")
print("restart, rerun this script — that's your baseline.")