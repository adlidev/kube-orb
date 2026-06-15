#!/usr/bin/env python3
"""
worker: Background job processor — scheduled tasks, async queues.
Format: bracketed plain text — slowest, bursty (~0.1-0.3 log/s baseline).
"""
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "worker"
INSTANCE_ID = uuid.uuid4().hex[:8]

# (job_type, min_steps, max_steps, queue)
JOB_TYPES = [
    ("generate_report",           3, 6, "reports"),
    ("sync_user_data",            2, 4, "sync"),
    ("send_digest_emails",        4, 7, "email"),
    ("cleanup_expired_sessions",  1, 3, "maintenance"),
    ("reindex_search",            3, 5, "search"),
    ("process_payments",          2, 5, "billing"),
    ("export_audit_log",          2, 4, "audit"),
    ("thumbnail_generation",      1, 3, "media"),
]

STEP_POOL = [
    "fetch_data", "validate_schema", "transform_records", "persist_results",
    "update_index", "notify_downstream", "cleanup_temp", "compress_output",
    "checksum_verify", "publish_event",
]

SCHEDULED_JOBS = [
    ("daily_report_job",   "0 6 * * *"),
    ("hourly_cleanup",     "0 * * * *"),
    ("weekly_digest",      "0 9 * * 1"),
    ("realtime_sync",      "*/5 * * * *"),
]


def log(level: str, msg: str, **ctx):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ctx_parts = [f"{k}={v}" for k, v in ctx.items()]
    ctx_str = (" | " + " ".join(ctx_parts)) if ctx_parts else ""
    print(f"[{ts}] [{level}] [{SERVICE}:{INSTANCE_ID}]{ctx_str} {msg}", flush=True)


def run_job():
    job_type, min_steps, max_steps, queue = random.choice(JOB_TYPES)
    job_id = f"job-{uuid.uuid4().hex[:10]}"
    n_steps = random.randint(min_steps, max_steps)
    steps = random.sample(STEP_POOL, k=n_steps)

    log("INFO", "job started",
        job_id=job_id, job_type=job_type, queue=queue, steps=n_steps)

    total_items = 0
    for i, step in enumerate(steps, 1):
        # Occasional transient error requiring a retry
        if random.random() < 0.06:
            log("WARN", "transient error - retrying step",
                job_id=job_id, step=step, attempt=1,
                error=random.choice(["network timeout", "lock contention", "rate limited"]))
            time.sleep(0.1)

        items = random.randint(10, 5000)
        total_items += items
        step_ms = random.randint(50, 2000)
        log("DEBUG", "step completed",
            job_id=job_id, step=step,
            progress=f"{i}/{n_steps}", items=items, step_ms=step_ms)
        time.sleep(min(step_ms / 5000, 0.3))  # Compressed for demo

    # Job outcome
    r = random.random()
    if r < 0.87:
        log("INFO", "job completed",
            job_id=job_id, job_type=job_type,
            total_items=total_items, queue=queue)
    elif r < 0.95:
        log("WARN", "job completed with warnings",
            job_id=job_id, job_type=job_type,
            warnings=random.randint(1, 10),
            detail=random.choice([
                "some records skipped - validation failed",
                "rate limited by upstream - partial results",
                "quota approaching limit",
            ]))
    else:
        log("ERROR", "job failed",
            job_id=job_id, job_type=job_type, queue=queue,
            error=random.choice([
                "database connection lost",
                "heap exhausted - OOM",
                "upstream API returned 500",
                "job timed out after 300s",
            ]),
            will_retry=random.choice(["true", "false"]))


def run_scheduled():
    job_name, cron = random.choice(SCHEDULED_JOBS)
    log("INFO", "scheduled job triggered",
        job=job_name, cron=cron,
        next_run_in_s=random.choice([60, 300, 3600, 86400]))


def log_resources():
    mem_mb = max(200.0, random.gauss(512, 100))
    goroutines = random.randint(10, 80)
    if mem_mb > 750:
        log("WARN", "high memory usage",
            mem_mb=round(mem_mb, 1), limit_mb=1024,
            goroutines=goroutines, gc_runs=random.randint(100, 500))
    else:
        log("DEBUG", "resource stats",
            mem_mb=round(mem_mb, 1), goroutines=goroutines,
            active_jobs=random.randint(0, 4))


def main():
    queues = ",".join({q for _, _, _, q in JOB_TYPES})
    log("INFO", "worker starting", version="1.2.4", concurrency=4, queues=queues)
    time.sleep(1.0)
    log("INFO", "queue connection established", broker="redis:6379")
    log("INFO", "worker ready - polling for jobs")

    cycle = 0
    while True:
        cycle += 1

        if cycle % 10 == 0:
            log_resources()
        if cycle % 25 == 0:
            run_scheduled()

        run_job()

        # Bursty: sometimes back-to-back jobs, sometimes idle
        time.sleep(random.uniform(2.0, 8.0))


if __name__ == "__main__":
    main()
