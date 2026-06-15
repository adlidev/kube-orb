#!/usr/bin/env python3
"""
notification-service: Email, push, and webhook delivery.
Format: nested JSON — slower pace (~0.2-0.5 log/s).
"""
import json
import random
import time
import uuid
from datetime import datetime, timezone

SERVICE = "notification-service"
INSTANCE_ID = uuid.uuid4().hex[:8]

EMAIL_PROVIDERS = ["sendgrid", "ses", "mailgun"]
PUSH_PROVIDERS = ["fcm", "apns"]
WEBHOOK_ENDPOINTS = [
    "https://hooks.example.com/integrations/slack",
    "https://api.crm.example.com/webhooks/events",
    "https://zapier.com/hooks/catch/abc123def",
]
EMAIL_SUBJECTS = [
    "Welcome to the platform",
    "Your weekly digest",
    "Password reset request",
    "Invoice #{n}",
    "Action required: verify your email",
    "Your account has been updated",
]


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


def simulate_email():
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    provider = random.choice(EMAIL_PROVIDERS)
    recipient = f"user{random.randint(1000, 9999)}@example.com"
    notification_id = uuid.uuid4().hex[:16]
    subject = random.choice(EMAIL_SUBJECTS).replace("{n}", str(random.randint(10000, 99999)))
    latency_ms = max(50.0, random.gauss(450, 120))

    r = random.random()
    if r < 0.80:
        log("INFO", "email delivered",
            request_id=request_id,
            notification_id=notification_id,
            provider=provider,
            recipient=recipient,
            subject=subject,
            latency_ms=round(latency_ms, 1),
            provider_message_id=uuid.uuid4().hex)
    elif r < 0.88:
        log("WARN", "email bounced",
            request_id=request_id,
            notification_id=notification_id,
            provider=provider,
            recipient=recipient,
            bounce_type=random.choice(["hard", "soft"]),
            bounce_reason=random.choice([
                "mailbox_full", "invalid_address",
                "domain_not_found", "spam_block",
            ]))
    elif r < 0.95:
        attempt = random.randint(1, 3)
        log("WARN", "email deferred - will retry",
            request_id=request_id,
            notification_id=notification_id,
            provider=provider,
            retry={"attempt": attempt, "max": 5,
                   "next_retry_s": [60, 300, 900][attempt - 1]})
    else:
        log("ERROR", "email delivery failed - provider error",
            request_id=request_id,
            notification_id=notification_id,
            provider=provider,
            recipient=recipient,
            error={
                "code": "provider_error",
                "detail": random.choice([
                    "rate limit exceeded",
                    "API key invalid",
                    "provider timeout",
                ]),
            })


def simulate_webhook():
    request_id = f"req-{uuid.uuid4().hex[:12]}"
    notification_id = uuid.uuid4().hex[:16]
    endpoint = random.choice(WEBHOOK_ENDPOINTS)
    event_type = random.choice([
        "user.created", "user.deleted", "payment.completed",
        "subscription.renewed", "alert.triggered",
    ])
    latency_ms = max(10.0, random.gauss(180, 60))

    r = random.random()
    if r < 0.75:
        log("INFO", "webhook delivered",
            request_id=request_id,
            notification_id=notification_id,
            event_type=event_type,
            endpoint=endpoint,
            status_code=200,
            latency_ms=round(latency_ms, 1))
    elif r < 0.85:
        status_code = random.choice([404, 422, 500, 502, 503])
        log("WARN", "webhook delivery failed - will retry",
            request_id=request_id,
            notification_id=notification_id,
            event_type=event_type,
            endpoint=endpoint,
            status_code=status_code,
            retry={"attempt": 1, "max": 5},
            latency_ms=round(latency_ms, 1))
    else:
        log("ERROR", "webhook endpoint unreachable",
            request_id=request_id,
            notification_id=notification_id,
            event_type=event_type,
            endpoint=endpoint,
            error="connection timeout",
            timeout_ms=5000)


def simulate_queue_stats():
    depth = random.randint(0, 500)
    if depth > 300:
        processing_rate = random.randint(10, 50)
        log("WARN", "notification queue depth elevated",
            queue={"depth": depth, "threshold": 300,
                   "processing_rate": processing_rate,
                   "estimated_lag_s": round(depth / processing_rate, 1)})
    else:
        log("DEBUG", "queue stats",
            queue={"depth": depth, "consumers": random.randint(2, 8),
                   "processing_rate": random.randint(20, 100)})


def main():
    log("INFO", "notification-service starting", version="1.8.3", port=8083)
    time.sleep(0.6)
    log("INFO", "queue consumer started",
        queue="notifications",
        concurrency=4,
        providers={"email": EMAIL_PROVIDERS, "push": PUSH_PROVIDERS})

    cycle = 0
    while True:
        cycle += 1

        if cycle % 15 == 0:
            simulate_queue_stats()

        if random.random() < 0.65:
            simulate_email()
        else:
            simulate_webhook()

        time.sleep(random.uniform(1.5, 4.0))


if __name__ == "__main__":
    main()
