# app/core/init_db.py
"""
Initialize database schema.
Run: python -m app.core.init_db
"""
from app.core.database import engine, Base
from app.models.all_models import (
    User, Alert, Action, Evidence, Validation,
    EscalationHistory, AuditLog, SLABreach
)
import structlog

logger = structlog.get_logger()


def init_db():
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")


if __name__ == "__main__":
    init_db()
