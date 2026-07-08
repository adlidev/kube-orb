#!/usr/bin/env python3
"""
database: Simulated Postgres-style database — query logs, connections, vacuums.
Format: structured key=value — moderate rate (~0.3-0.8 log/s).
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "database"
INSTANCE_ID = uuid.uuid4().hex[:8]

TABLES = [
    "users", "sessions", "notifications", "audit_log",
    "payments", "products", "orders", "events",
]

QUERY_TYPES = ["SELECT", "INSERT", "UPDATE", "DELETE"]

SLOW_QUERY_TEMPLATES = [
    "SELECT * FROM {table} WHERE created_at < NOW() - INTERVAL '30 days'",
    "SELECT COUNT(*) FROM {table} JOIN sessions ON sessions.user_id = {table}.id",
    "UPDATE {table} SET status='archived' WHERE last_seen < NOW() - INTERVAL '90 days'",
    "DELETE FROM {table} WHERE expires_at < NOW()",
]

CLIENTS = ["user-service", "auth-service", "worker", "api-gateway"]


def log(level: str, msg: str, **ctx):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    ctx_parts = " ".join(f"{k}={v}" for k, v in ctx.items())
    print(f"{ts} [{level}] {SERVICE}[{INSTANCE_ID}]: {msg}  {ctx_parts}", flush=True)


def simulate_query():
    table = random.choice(TABLES)
    qtype = random.choice(QUERY_TYPES)
    client = random.choice(CLIENTS)
    rows = random.randint(0, 5000)
    duration_ms = max(0.1, random.lognormvariate(2.5, 1.2))

    if duration_ms > 500:
        query = random.choice(SLOW_QUERY_TEMPLATES).format(table=table)
        log("WARN", "slow query detected",
            duration_ms=round(duration_ms, 2),
            query=query,
            table=table,
            rows_examined=rows * random.randint(10, 100),
            rows_returned=rows,
            client=client,
            lock_wait_ms=round(random.uniform(0, duration_ms * 0.3), 1))
    elif random.random() < 0.005:
        log("ERROR", "query failed",
            query_type=qtype,
            table=table,
            client=client,
            error=random.choice([
                "deadlock detected",
                "could not serialize access due to concurrent update",
                "canceling statement due to lock timeout",
                "out of shared memory",
            ]),
            duration_ms=round(duration_ms, 2))
    else:
        log("DEBUG", "query executed",
            query_type=qtype,
            table=table,
            rows=rows,
            duration_ms=round(duration_ms, 2),
            client=client,
            index_used=random.choice(["true", "true", "true", "false"]))


def simulate_connection_event():
    event = random.choice([
        "client connected",
        "client connected",
        "client connected",
        "client disconnected",
        "idle connection reclaimed",
    ])
    pool_size = random.randint(5, 50)
    active = random.randint(0, pool_size)
    level = "WARN" if pool_size > 45 else "INFO"
    log(level, event,
        client=random.choice(CLIENTS),
        pool_size=pool_size,
        active_connections=active,
        idle_connections=pool_size - active,
        max_connections=50)


def simulate_maintenance():
    table = random.choice(TABLES)
    event = random.choice([
        ("INFO",  "autovacuum started",          {"table": table}),
        ("INFO",  "autovacuum completed",         {"table": table, "dead_tuples_removed": random.randint(100, 50000), "pages_removed": random.randint(1, 200)}),
        ("INFO",  "checkpoint started",           {"wal_buffers_full": random.randint(0, 5)}),
        ("INFO",  "checkpoint completed",         {"duration_s": round(random.uniform(0.1, 3.5), 2), "buffers_written": random.randint(100, 5000)}),
        ("WARN",  "replication lag detected",     {"replica": f"replica-{random.randint(1,2)}", "lag_bytes": random.randint(1024, 10485760), "lag_s": round(random.uniform(1, 30), 1)}),
        ("INFO",  "WAL archive completed",         {"file": f"000000010000000{random.randint(10,99)}", "segments_archived": random.randint(1, 5)}),
    ])
    level, msg, ctx = event
    log(level, msg, **ctx)


def main():
    log("INFO", "database starting",
        version="15.4", port=5432, max_connections=50, shared_buffers="256MB")
    time.sleep(0.8)
    log("INFO", "database system is ready to accept connections", data_dir="/var/lib/postgresql/data")
    log("INFO", "autovacuum launcher started")

    cycle = 0
    while True:
        cycle += 1

        simulate_query()

        if cycle % 8 == 0:
            simulate_connection_event()
        if cycle % 20 == 0:
            simulate_maintenance()

        time.sleep(random.uniform(0.8, 2.5))


if __name__ == "__main__":
    main()
