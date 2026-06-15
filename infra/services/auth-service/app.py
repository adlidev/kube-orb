#!/usr/bin/env python3
"""
auth-service: JWT issuance, validation, session management.
Format: logfmt — medium frequency (~0.5-1 log/s).
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "auth-service"
INSTANCE_ID = uuid.uuid4().hex[:8]

KNOWN_USERS = [f"usr-{i}" for i in range(10000, 10050)]
ATTACK_IPS = ["185.220.101.47", "45.142.212.100", "203.0.113.42"]
CLEAN_IPS = [f"10.{random.randint(0,3)}.{random.randint(0,255)}.{random.randint(1,254)}"
             for _ in range(30)]


def logfmt(level: str, msg: str, **kwargs):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    parts = [
        f'time="{ts}"',
        f"level={level.lower()}",
        f"service={SERVICE}",
        f"instance={INSTANCE_ID}",
        f'msg="{msg}"',
    ]
    for k, v in kwargs.items():
        if isinstance(v, str) and (" " in v or "=" in v):
            parts.append(f'{k}="{v}"')
        else:
            parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)


def simulate_login():
    user_id = random.choice(KNOWN_USERS)
    is_attack = random.random() < 0.05
    client_ip = random.choice(ATTACK_IPS if is_attack else CLEAN_IPS)
    request_id = f"req-{uuid.uuid4().hex[:12]}"

    if is_attack:
        logfmt("WARN", "brute force detected",
               request_id=request_id, user_id=user_id, client_ip=client_ip,
               attempts=random.randint(5, 20), action="temporary_block",
               block_duration_s=300)
        return

    success = random.random() < 0.88
    latency_ms = max(5.0, random.gauss(35, 10))

    if success:
        logfmt("INFO", "login successful",
               request_id=request_id, user_id=user_id, client_ip=client_ip,
               token_id=uuid.uuid4().hex[:16],
               latency_ms=round(latency_ms, 1),
               mfa=random.choice(["none", "totp", "sms"]))
    else:
        logfmt("WARN", "login failed - invalid credentials",
               request_id=request_id, user_id=user_id, client_ip=client_ip,
               latency_ms=round(latency_ms, 1),
               failure_count=random.randint(1, 3))


def simulate_token_validation():
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    user_id = random.choice(KNOWN_USERS)
    token_id = uuid.uuid4().hex[:16]
    latency_ms = max(0.5, random.gauss(8, 3))

    r = random.random()
    if r < 0.88:
        logfmt("DEBUG", "token validated",
               request_id=request_id, user_id=user_id, token_id=token_id,
               latency_ms=round(latency_ms, 1),
               scope="read:users write:users")
    elif r < 0.93:
        logfmt("WARN", "token expired",
               request_id=request_id, user_id=user_id, token_id=token_id,
               expired_at="2024-01-15T09:00:00Z", action="rejected")
    elif r < 0.97:
        logfmt("WARN", "token signature invalid",
               request_id=request_id, token_id=token_id, action="rejected")
    else:
        logfmt("ERROR", "token validation failed - redis unreachable",
               request_id=request_id,
               error="connection refused", redis_host="redis:6379",
               latency_ms=round(latency_ms * 10, 1))


def simulate_refresh():
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    user_id = random.choice(KNOWN_USERS)
    logfmt("INFO", "token refreshed",
           request_id=request_id, user_id=user_id,
           old_token_id=uuid.uuid4().hex[:16],
           new_token_id=uuid.uuid4().hex[:16],
           expires_in=3600)


def main():
    logfmt("INFO", "auth-service starting", version="2.1.0", port=8081)
    time.sleep(0.3)
    logfmt("INFO", "JWT keys loaded", algorithm="RS256", key_rotation_days=30)
    logfmt("INFO", "redis connection established", host="redis:6379", pool_size=10)

    actions = [
        (simulate_login, 0.25),
        (simulate_token_validation, 0.60),
        (simulate_refresh, 0.15),
    ]

    while True:
        r = random.random()
        cumulative = 0.0
        for action, weight in actions:
            cumulative += weight
            if r < cumulative:
                action()
                break
        time.sleep(random.uniform(0.8, 2.5))


if __name__ == "__main__":
    main()
