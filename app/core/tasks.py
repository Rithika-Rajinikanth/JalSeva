# app/core/tasks.py
"""
Celery background tasks for SLA enforcement and scheduled governance checks.
"""
from celery import Celery
from app.core.config import settings
import structlog

logger = structlog.get_logger()

celery_app = Celery(
    "jalseva",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    beat_schedule={
        "check-sla-breaches-hourly": {
            "task": "app.core.tasks.check_sla_breaches",
            "schedule": 3600.0,  # Every hour
        },
    },
)


@celery_app.task(name="app.core.tasks.check_sla_breaches", bind=True, max_retries=3)
def check_sla_breaches(self):
    """
    Periodic SLA enforcement — Sahana Eden pattern.
    Auto-escalates alerts that have breached their SLA deadline.
    """
    try:
        from app.core.database import SessionLocal
        from app.services.alert_service import AlertService

        db = SessionLocal()
        try:
            service = AlertService()
            escalated = service.check_sla_breaches(db)
            logger.info("SLA check complete", escalated_count=len(escalated))
            return {"escalated": len(escalated)}
        finally:
            db.close()
    except Exception as exc:
        logger.error("SLA check task failed", error=str(exc))
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(name="app.core.tasks.send_n8n_notification")
async def send_n8n_notification(webhook_type: str, payload: dict):
    """Async n8n notification task."""
    from app.services.n8n_service import get_n8n_service
    n8n = get_n8n_service()
    if webhook_type == "alert":
        await n8n.notify_new_alert(payload)
    elif webhook_type == "escalation":
        await n8n.notify_escalation(payload, payload.get("to_level"), payload.get("reason"))
