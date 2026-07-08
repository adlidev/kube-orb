#!/usr/bin/env python3
"""
user-service: User CRUD, PostgreSQL-backed with Redis cache.
Format: traditional timestamped text — medium frequency (~0.5-1 log/s).
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "user-service"
INSTANCE_ID = uuid.uuid4().hex[:8]

USER_IDS = [f"usr-{i}" for i in range(10000, 10050)]
TABLES = ["users", "user_profiles", "user_preferences", "user_sessions"]


def log(level: str, msg: str, **ctx):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
    ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items())
    line = f"{ts} {level:<5} [{SERVICE}:{INSTANCE_ID}] {msg}"
    if ctx_str:
        line += f"  {ctx_str}"
    print(line, flush=True)


def simulate_db_query():
    table = random.choice(TABLES)
    op = random.choice(["SELECT", "SELECT", "SELECT", "INSERT", "UPDATE", "DELETE"])
    user_id = random.choice(USER_IDS)
    request_id = f"req-{uuid.uuid4().hex[:12]}"

    r = random.random()
    if r < 0.40:
        # Cache hit — no DB round-trip
        latency = max(0.3, random.gauss(1.5, 0.5))
        log("DEBUG", "cache hit",
            request_id=request_id, user_id=user_id,
            table=table, op=op, latency_ms=round(latency, 2), source="redis")
        return

    latency = max(1.0, random.gauss(12, 5)) if r < 0.97 else max(150.0, random.gauss(280, 80))

    if latency > 200:
        log("WARN", "slow query detected",
            request_id=request_id, user_id=user_id,
            table=table, op=op, latency_ms=round(latency, 2),
            threshold_ms=200, hint="missing_index")
    elif op in ("INSERT", "UPDATE", "DELETE"):
        rows = random.randint(1, 5) if op == "DELETE" else 1
        log("INFO", "query executed",
            request_id=request_id, user_id=user_id,
            table=table, op=op, rows_affected=rows, latency_ms=round(latency, 2))
    else:
        rows = random.randint(0, 100)
        log("DEBUG", "query executed",
            request_id=request_id, user_id=user_id,
            table=table, op=op, rows_returned=rows, latency_ms=round(latency, 2))


def simulate_crud():
    op = random.choice(["create_user", "update_profile", "deactivate_user", "get_user"])
    user_id = random.choice(USER_IDS)
    request_id = f"req-{uuid.uuid4().hex[:12]}"

    if op == "create_user":
        log("INFO", "user created",
            request_id=request_id, user_id=user_id,
            email=f"user{random.randint(1000,9999)}@example.com",
            role=random.choice(["user", "admin", "readonly"]))
    elif op == "update_profile":
        fields = ",".join(random.sample(["email", "name", "avatar", "timezone", "locale"],
                                        k=random.randint(1, 3)))
        log("INFO", "profile updated",
            request_id=request_id, user_id=user_id, fields=fields)
    elif op == "deactivate_user":
        log("WARN", "user deactivated",
            request_id=request_id, user_id=user_id,
            reason=random.choice(["admin_action", "violation", "account_closure"]),
            performed_by=f"usr-{random.randint(10000, 10050)}")
    else:
        if random.random() > 0.05:
            log("DEBUG", "user found",
                request_id=request_id, user_id=user_id,
                cached=random.choice([True, False]))
        else:
            log("INFO", "user not found",
                request_id=request_id, user_id=user_id)


def simulate_pool_stats():
    pool_size = 20
    active = random.randint(1, pool_size)
    if active > 18:
        log("WARN", "connection pool near capacity",
            active=active, pool_size=pool_size, waiting=random.randint(1, 5))
    else:
        log("DEBUG", "pool stats", active=active, idle=pool_size - active)


def main():
    log("INFO", "user-service starting", version="3.0.1", port=8082)
    time.sleep(0.4)
    log("INFO", "database connection established",
        host="postgres:5432", database="users_db", pool_size=20)
    log("INFO", "redis connection established", host="redis:6379")
    log("INFO", "service ready")

    cycle = 0
    while True:
        cycle += 1

        if cycle % 20 == 0:
            simulate_pool_stats()

        if random.random() < 0.6:
            simulate_db_query()
        else:
            simulate_crud()

        # Occasional DB error burst
        if random.random() < 0.005:
            log("ERROR", "database connection failed",
                host="postgres:5432", error="connection refused",
                attempt=random.randint(1, 3),
                next_retry_ms=random.choice([100, 500, 1000]))

        time.sleep(random.uniform(0.7, 2.0))


if __name__ == "__main__":
    main()
