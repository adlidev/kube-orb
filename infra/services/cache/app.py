#!/usr/bin/env python3
"""
cache: Simulated Redis-style cache — hits/misses, evictions, memory pressure.
Format: plain text with prefix — fast rate (~1-2 log/s), mostly terse.
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "cache"
INSTANCE_ID = uuid.uuid4().hex[:8]

KEY_SPACES = [
    "session:{id}",
    "user:{id}:profile",
    "user:{id}:perms",
    "rate_limit:{ip}",
    "lock:job:{id}",
    "cache:query:{id}",
    "token:{id}",
    "leaderboard:global",
]

CLIENTS = ["api-gateway", "auth-service", "user-service", "worker"]


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def log(level: str, msg: str):
    print(f"{ts()} {level} [{SERVICE}:{INSTANCE_ID}] {msg}", flush=True)


def make_key():
    tpl = random.choice(KEY_SPACES)
    return tpl.replace("{id}", uuid.uuid4().hex[:8]).replace("{ip}", f"10.0.{random.randint(0,3)}.{random.randint(1,254)}")


def simulate_operation():
    key = make_key()
    client = random.choice(CLIENTS)
    r = random.random()

    if r < 0.72:
        ttl = random.randint(60, 3600)
        log("INFO", f"HIT key={key} client={client} ttl_remaining={ttl}s")
    elif r < 0.88:
        log("INFO", f"MISS key={key} client={client}")
    elif r < 0.92:
        ttl = random.randint(60, 86400)
        size_b = random.randint(64, 8192)
        log("DEBUG", f"SET key={key} ttl={ttl}s size={size_b}b client={client}")
    elif r < 0.95:
        log("DEBUG", f"DEL key={key} client={client}")
    elif r < 0.97:
        log("WARN", f"KEY EXPIRED key={key} eviction_policy=allkeys-lru")
    else:
        log("WARN", f"MISS (expired) key={key} client={client}")


def simulate_memory():
    used_mb = max(50.0, random.gauss(280, 60))
    max_mb = 512
    pct = used_mb / max_mb * 100

    if pct > 90:
        evicted = random.randint(100, 5000)
        log("ERROR", f"MEMORY CRITICAL used={used_mb:.0f}MB max={max_mb}MB pct={pct:.1f}% evicted_keys={evicted}")
    elif pct > 75:
        log("WARN", f"MEMORY HIGH used={used_mb:.0f}MB max={max_mb}MB pct={pct:.1f}%")
    else:
        connected = random.randint(5, 40)
        hit_rate = round(random.uniform(0.65, 0.95), 3)
        log("DEBUG", f"STATS used_memory={used_mb:.0f}MB connected_clients={connected} hit_rate={hit_rate} ops_per_sec={random.randint(100, 2000)}")


def simulate_replication():
    event = random.choice([
        ("INFO",  f"REPL replica-{random.randint(1,2)} connected offset={random.randint(1000,9999999)}"),
        ("INFO",  f"REPL full resync requested replica-{random.randint(1,2)}"),
        ("WARN",  f"REPL replica-{random.randint(1,2)} disconnected — lag was {random.randint(1,300)}s"),
        ("DEBUG", f"REPL sent {random.randint(1,1000)} commands to replica-{random.randint(1,2)}"),
    ])
    log(event[0], event[1])


def main():
    log("INFO", f"cache server starting version=7.2.3 port=6379 max_memory=512mb policy=allkeys-lru")
    time.sleep(0.3)
    log("INFO", "ready to accept connections")
    log("INFO", f"loading RDB snapshot keys_loaded={random.randint(10000,500000)}")

    cycle = 0
    while True:
        cycle += 1

        simulate_operation()

        if cycle % 15 == 0:
            simulate_memory()
        if cycle % 30 == 0:
            simulate_replication()

        time.sleep(random.uniform(0.2, 0.8))


if __name__ == "__main__":
    main()
