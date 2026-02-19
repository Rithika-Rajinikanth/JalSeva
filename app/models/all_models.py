# app/models/__init__.py
# app/models/all_models.py
"""
Production-grade SQLAlchemy models for JalSeva.

Design patterns borrowed from:
- Ushahidi: hierarchical alert status, verification, disputed states
- FixMyStreet: owner assignment, evidence-gated closure
- Sahana Eden: multi-org, multi-tier authority tracking
- Akvo RSR: evidence audit, outcome validation
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, Boolean,
    ForeignKey, Enum, Float, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
import enum


def gen_uuid():
    return str(uuid.uuid4())


# ─── Enums ───────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    PANCHAYAT = "PANCHAYAT"
    BLOCK_OFFICER = "BLOCK_OFFICER"
    MANDAL_OFFICER = "MANDAL_OFFICER"
    DISTRICT_OFFICER = "DISTRICT_OFFICER"
    STATE_OFFICER = "STATE_OFFICER"
    NGO = "NGO"
    VALIDATOR = "VALIDATOR"       # Independent verifier (NGO / student volunteer)
    ADMIN = "ADMIN"


class AlertSeverity(str, enum.Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class AlertStatus(str, enum.Enum):
    """
    Ushahidi-inspired status lifecycle.
    An alert can ONLY reach CLOSED via VERIFIED → evidence approval.
    """
    CREATED = "CREATED"
    VALIDATED = "VALIDATED"
    NEEDS_ESCALATION = "NEEDS_ESCALATION"
    ASSIGNED = "ASSIGNED"
    ACTION_SUBMITTED = "ACTION_SUBMITTED"         # Actioner submitted claim
    RESOLUTION_DISPUTED = "RESOLUTION_DISPUTED"  # Ushahidi: disputed state
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    ESCALATED_DISTRICT = "ESCALATED_DISTRICT"
    ESCALATED_STATE = "ESCALATED_STATE"
    CLOSED = "CLOSED"                             # FixMyStreet: only after evidence
    ARCHIVED = "ARCHIVED"


class EscalationLevel(str, enum.Enum):
    PANCHAYAT = "PANCHAYAT"
    BLOCK = "BLOCK"
    MANDAL = "MANDAL"
    DISTRICT = "DISTRICT"
    STATE = "STATE"


class EvidenceType(str, enum.Enum):
    PHOTO = "PHOTO"
    DOCUMENT = "DOCUMENT"
    COMMUNITY_FEEDBACK = "COMMUNITY_FEEDBACK"
    FIELD_REPORT = "FIELD_REPORT"
    WATER_TEST = "WATER_TEST"
    GPS_COORDINATES = "GPS_COORDINATES"
    OTHER = "OTHER"


class VerificationDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PENDING = "PENDING"


# ─── Models ──────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default=UserRole.PANCHAYAT)
    organization = Column(String)
    panchayat = Column(String)
    district = Column(String)
    state = Column(String)
    phone = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    alerts = relationship("Alert", back_populates="reporter", foreign_keys="Alert.reporter_id")
    validations = relationship("Validation", back_populates="validator")
    audit_logs = relationship("AuditLog", back_populates="actor")


class Alert(Base):
    """
    Core alert entity. Lifecycle matches Ushahidi's report states.
    Closure is evidence-gated (FixMyStreet pattern).
    """
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_code = Column(String, unique=True, nullable=False, index=True)  # e.g. ALERT-20240115-001

    # Location (Sahana Eden: fine-grained admin hierarchy)
    panchayat = Column(String, nullable=False)
    block = Column(String)
    mandal = Column(String)
    district = Column(String, nullable=False)
    state = Column(String, nullable=False)
    lat = Column(Float)
    lng = Column(Float)

    # Issue details
    severity = Column(String, nullable=False, default=AlertSeverity.MEDIUM)
    description = Column(Text, nullable=False)
    households_affected = Column(Integer, default=0)
    water_source_type = Column(String)              # borewell, river, tanker, etc.
    primary_concern = Column(String)                # scarcity, quality, access

    # ML outputs (pure_path integration)
    ml_risk_score = Column(Float)                   # from water_governance_model.pkl
    ml_predicted_severity = Column(String)
    ml_confidence = Column(Float)

    # Status & ownership (FixMyStreet / Sahana Eden)
    status = Column(String, default=AlertStatus.CREATED, index=True)
    escalation_level = Column(String, default=EscalationLevel.PANCHAYAT)
    assigned_to = Column(String)                    # officer designation
    assigned_user_id = Column(String, ForeignKey("users.id"))
    sla_hours = Column(Integer)
    sla_deadline = Column(DateTime)
    priority_score = Column(Integer, default=1)

    # LLM validation (agents.py integration)
    validation_status = Column(String)
    validation_reasoning = Column(Text)

    # Reporter
    reporter_id = Column(String, ForeignKey("users.id"))
    reporter_name = Column(String)
    reporter_email = Column(String)
    reporter_org = Column(String)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(DateTime)

    # Action plan from governance graph
    action_plan = Column(Text)

    # n8n tracking
    n8n_notified = Column(Boolean, default=False)

    # Relationships
    reporter = relationship("User", back_populates="alerts", foreign_keys=[reporter_id])
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    actions = relationship("Action", back_populates="alert")
    validations = relationship("Validation", back_populates="alert")
    evidence = relationship("Evidence", back_populates="alert")
    audit_logs = relationship("AuditLog", back_populates="alert")
    escalation_history = relationship("EscalationHistory", back_populates="alert")


class Action(Base):
    """
    Actions claimed by any actor against an alert.
    Akvo RSR pattern: who claimed to act, what, with what evidence.
    """
    __tablename__ = "actions"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    actor_id = Column(String, ForeignKey("users.id"))
    actor_name = Column(String, nullable=False)
    actor_organization = Column(String)
    actor_email = Column(String)

    action_type = Column(String)        # tanker_dispatch, borewell_survey, etc.
    description = Column(Text, nullable=False)
    resources_deployed = Column(Text)
    expected_completion = Column(DateTime)
    actual_completion = Column(DateTime)

    submitted_at = Column(DateTime, default=datetime.utcnow)
    is_resolution_claim = Column(Boolean, default=False)

    # Ushahidi: contradictions flagged by NLI
    contradiction_score = Column(Float)
    contradiction_flag = Column(Boolean, default=False)
    contradiction_reason = Column(Text)

    alert = relationship("Alert", back_populates="actions")
    evidence = relationship("Evidence", back_populates="action")


class Evidence(Base):
    """
    Evidence vault — mWater / Akvo RSR pattern.
    All documents, photos, GPS coordinates linked immutably.
    """
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    action_id = Column(String, ForeignKey("actions.id"))
    uploaded_by_id = Column(String, ForeignKey("users.id"))

    evidence_type = Column(String, default=EvidenceType.DOCUMENT)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_size = Column(Integer)
    mime_type = Column(String)
    description = Column(Text)

    # Geolocation for field evidence
    lat = Column(Float)
    lng = Column(Float)
    gps_accuracy = Column(Float)

    uploaded_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("Alert", back_populates="evidence")
    action = relationship("Action", back_populates="evidence")


class Validation(Base):
    """
    Independent verification — FixMyStreet closure gate.
    ONLY a Validator role can approve closure.
    """
    __tablename__ = "validations"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    validator_id = Column(String, ForeignKey("users.id"))
    validator_name = Column(String, nullable=False)
    validator_org = Column(String)

    method = Column(Text)                   # Field visit, phone survey, document review
    findings = Column(Text, nullable=False)
    evidence_reviewed = Column(Text)
    community_feedback = Column(Text)
    recommendations = Column(Text)

    decision = Column(String, default=VerificationDecision.PENDING)
    llm_coherence_score = Column(Float)     # LLM analysis of resolution claim vs findings
    nli_contradiction_score = Column(Float) # NLI model contradiction detection

    validated_at = Column(DateTime, default=datetime.utcnow)

    alert = relationship("Alert", back_populates="validations")
    validator = relationship("User", back_populates="validations")


class EscalationHistory(Base):
    """
    Sahana Eden pattern: full trace of every escalation event.
    """
    __tablename__ = "escalation_history"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    from_level = Column(String)
    to_level = Column(String, nullable=False)
    escalated_by_id = Column(String, ForeignKey("users.id"))
    escalated_by_name = Column(String)
    reason = Column(Text)
    sla_breached = Column(Boolean, default=False)
    escalated_at = Column(DateTime, default=datetime.utcnow)
    n8n_notified = Column(Boolean, default=False)

    alert = relationship("Alert", back_populates="escalation_history")


class AuditLog(Base):
    """
    Immutable append-only log of every state transition.
    Every change is actor-stamped and timestamped.
    """
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    actor_id = Column(String, ForeignKey("users.id"))
    actor_name = Column(String)
    actor_role = Column(String)

    event_type = Column(String, nullable=False)   # CREATED, VALIDATED, ESCALATED, etc.
    from_status = Column(String)
    to_status = Column(String)
    details = Column(JSON)
    timestamp = Column(DateTime, default=datetime.utcnow)

    alert = relationship("Alert", back_populates="audit_logs")
    actor = relationship("User", back_populates="audit_logs")


class SLABreach(Base):
    """
    Track SLA violations for accountability reporting.
    """
    __tablename__ = "sla_breaches"

    id = Column(String, primary_key=True, default=gen_uuid)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False)
    assigned_to = Column(String)
    expected_by = Column(DateTime)
    breached_at = Column(DateTime, default=datetime.utcnow)
    hours_overdue = Column(Float)
    auto_escalated = Column(Boolean, default=False)