#!/usr/bin/env python3
"""
api-gateway: Routes requests to backend services.
Format: structured JSON — the busiest service (~1-2 logs/s).
"""
import json
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "api-gateway"
INSTANCE_ID = uuid.uuid4().hex[:8]

ROUTES = [
    ("GET",    "/api/v1/users",              "user-service"),
    ("GET",    "/api/v1/users/{id}",         "user-service"),
    ("POST",   "/api/v1/users",              "user-service"),
    ("PUT",    "/api/v1/users/{id}",         "user-service"),
    ("DELETE", "/api/v1/users/{id}",         "user-service"),
    ("POST",   "/api/v1/auth/login",         "auth-service"),
    ("POST",   "/api/v1/auth/refresh",       "auth-service"),
    ("DELETE", "/api/v1/auth/logout",        "auth-service"),
    ("POST",   "/api/v1/notifications",      "notification-service"),
    ("GET",    "/api/v1/notifications",      "notification-service"),
    ("GET",    "/health",                    None),
    ("GET",    "/metrics",                   None),
]

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "okhttp/4.9.0",
    "python-httpx/0.24.0",
    "axios/1.4.0",
]

CLIENT_IPS = [f"10.0.{random.randint(0,3)}.{random.randint(1,254)}" for _ in range(20)]


def log(level: str, msg: str, **kwargs):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": SERVICE,
        "instance": INSTANCE_ID,
        "msg": msg,
        **kwargs,
    }
    print(json.dumps(record), flush=True)


def simulate_request():
    method, path_tpl, upstream = random.choice(ROUTES)
    path = path_tpl.replace("{id}", str(random.randint(1000, 9999)))
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    user_id = f"usr-{random.randint(10000, 99999)}" if random.random() > 0.2 else None
    client_ip = random.choice(CLIENT_IPS)

    upstream_ms = max(5.0, random.gauss(45, 20)) if upstream else max(0.5, random.gauss(2, 1))
    total_ms = upstream_ms + max(0.5, random.gauss(3, 1))

    r = random.random()
    if r < 0.85:
        status = 200 if method == "GET" else (201 if method == "POST" else 200)
    elif r < 0.90:
        status = 400
    elif r < 0.93:
        status = 401
    elif r < 0.95:
        status = 404
    elif r < 0.97:
        status = 429
    elif r < 0.99:
        status = 503
    else:
        status = 500

    extra = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "status": status,
        "latency_ms": round(total_ms, 2),
        "client_ip": client_ip,
        "user_agent": random.choice(USER_AGENTS),
    }
    if user_id:
        extra["user_id"] = user_id
    if upstream:
        extra["upstream"] = upstream
        extra["upstream_latency_ms"] = round(upstream_ms, 2)

    if status == 429:
        log("WARN", "rate limit exceeded", **extra, retry_after=60)
    elif status >= 500:
        log("ERROR", f"upstream error from {upstream or 'internal'}", **extra,
            error="upstream_unavailable" if status == 503 else "internal_error")
    elif total_ms > 100:
        log("WARN", "slow upstream response", **extra)
    else:
        log("INFO", "request completed", **extra)

    # Occasional routing debug log
    if random.random() < 0.08 and upstream:
        log("DEBUG", "routing decision",
            request_id=request_id, upstream=upstream, strategy="round-robin",
            selected_pod=f"{upstream}-{random.randint(1,2)}-{uuid.uuid4().hex[:5]}")


def main():
    log("INFO", "api-gateway starting", version="1.4.2", port=8080)
    time.sleep(0.5)
    log("INFO", "connected to upstream services",
        upstreams=["auth-service", "user-service", "notification-service"])
    log("INFO", "rate limiter initialized", requests_per_minute=1000, burst=50)

    while True:
        simulate_request()
        # Busiest service: mostly fast, occasional quiet stretch
        time.sleep(random.uniform(0.3, 1.2) if random.random() < 0.75 else random.uniform(1.2, 3.0))


if __name__ == "__main__":
    main()
