#!/usr/bin/env python3
"""
scheduler: Cron-style job scheduler — triggers, overlaps, missed runs, SLA alerts.
Format: structured with emoji-style severity markers — low rate (~0.1-0.2 log/s), bursty.
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "scheduler"
INSTANCE_ID = uuid.uuid4().hex[:8]

JOBS = [
    ("billing.monthly_invoice",     "0 1 1 * *",    45,   True),
    ("reports.daily_summary",       "0 6 * * *",    30,   False),
    ("users.cleanup_stale",         "0 3 * * *",    10,   False),
    ("notifications.digest",        "0 8 * * 1-5",  20,   False),
    ("search.reindex",              "0 2 * * 0",    120,  True),
    ("audit.archive",               "0 0 * * *",    15,   False),
    ("payments.reconcile",          "*/15 * * * *", 5,    True),
    ("cache.warm",                  "*/30 * * * *", 2,    False),
    ("health.ping_upstreams",       "* * * * *",    1,    False),
    ("ml.retrain_recommendations",  "0 4 * * 0",    180,  True),
]


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def log(level: str, msg: str, **ctx):
    ctx_str = "  ".join(f"{k}={v}" for k, v in ctx.items())
    print(f"{ts()} [{level}] {SERVICE}: {msg}  {ctx_str}", flush=True)


def run_job(job):
    name, cron, sla_s, critical = job
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    duration_s = max(0.5, random.gauss(sla_s * 0.8, sla_s * 0.2))
    breached = duration_s > sla_s

    log("INFO", "job triggered",
        job=name, run_id=run_id, cron=cron,
        critical=critical, sla_s=sla_s)

    # Occasional overlap detection
    if random.random() < 0.03:
        log("WARN", "previous run still active — skipping",
            job=name, run_id=run_id,
            previous_run_id=f"run-{uuid.uuid4().hex[:8]}",
            previous_started_s=random.randint(sla_s, sla_s * 3),
            action="skip")
        return

    # Occasional missed run
    if random.random() < 0.01:
        missed_count = random.randint(1, 5)
        log("ERROR" if critical else "WARN", "missed scheduled runs detected",
            job=name, missed_count=missed_count,
            reason=random.choice([
                "scheduler was down",
                "lock acquisition timed out",
                "executor pool exhausted",
            ]))

    # Simulate the job running (compressed)
    time.sleep(min(duration_s / 20, 1.5))

    r = random.random()
    if r < 0.90:
        level = "WARN" if breached else "INFO"
        msg = "job completed (SLA breached)" if breached else "job completed"
        log(level, msg,
            job=name, run_id=run_id,
            duration_s=round(duration_s, 2),
            sla_s=sla_s,
            sla_ok=not breached)
        if breached and critical:
            log("ERROR", "CRITICAL SLA BREACH — paging on-call",
                job=name, run_id=run_id,
                duration_s=round(duration_s, 2),
                sla_s=sla_s,
                breach_pct=round((duration_s / sla_s - 1) * 100, 1))
    elif r < 0.97:
        log("WARN", "job completed with retries",
            job=name, run_id=run_id,
            retries=random.randint(1, 3),
            duration_s=round(duration_s * 1.5, 2))
    else:
        log("ERROR", "job failed",
            job=name, run_id=run_id,
            error=random.choice([
                "executor threw unhandled exception",
                "downstream service unavailable",
                "database connection pool exhausted",
                "job timed out",
            ]),
            will_retry=critical,
            next_retry_in_s=random.choice([60, 300, 600]) if critical else None)


def log_scheduler_health():
    pending = random.randint(0, 12)
    running = random.randint(0, 4)
    level = "WARN" if pending > 8 else "DEBUG"
    log(level, "scheduler heartbeat",
        pending_jobs=pending,
        running_jobs=running,
        workers_available=max(0, 4 - running),
        next_tick_ms=random.randint(50, 1000))


def main():
    log("INFO", "scheduler starting",
        version="3.1.0", workers=4, timezone="UTC",
        jobs_registered=len(JOBS))
    time.sleep(0.5)
    log("INFO", "scheduler ready", lock_backend="redis", leader=True)

    cycle = 0
    while True:
        cycle += 1

        # Randomly trigger one of the jobs
        job = random.choice(JOBS)
        run_job(job)

        if cycle % 5 == 0:
            log_scheduler_health()

        # Low base rate, bursty
        time.sleep(random.uniform(3.0, 12.0))


if __name__ == "__main__":
    main()
