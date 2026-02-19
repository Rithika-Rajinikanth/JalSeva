# app/schemas/schemas.py
"""
Pydantic v2 schemas for all API endpoints.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum


# ─── Auth ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str
    role: str = "PANCHAYAT"
    organization: Optional[str] = None
    panchayat: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    organization: Optional[str]
    panchayat: Optional[str]
    district: Optional[str]
    state: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Alert ───────────────────────────────────────────────────────────────────

class AlertCreate(BaseModel):
    panchayat: str = Field(..., min_length=2)
    block: Optional[str] = None
    mandal: Optional[str] = None
    district: str = Field(..., min_length=2)
    state: str = Field(..., min_length=2)
    lat: Optional[float] = None
    lng: Optional[float] = None
    severity: str = Field(default="Medium")
    description: str = Field(..., min_length=20)
    households_affected: int = Field(default=0, ge=0)
    water_source_type: Optional[str] = None
    primary_concern: Optional[str] = None
    reporter_name: str
    reporter_email: Optional[EmailStr] = None
    reporter_org: Optional[str] = None


class AlertOut(BaseModel):
    id: str
    alert_code: str
    panchayat: str
    district: str
    state: str
    severity: str
    description: str
    households_affected: int
    status: str
    escalation_level: str
    assigned_to: Optional[str]
    sla_hours: Optional[int]
    sla_deadline: Optional[datetime]
    priority_score: Optional[int]
    ml_risk_score: Optional[float]
    ml_predicted_severity: Optional[str]
    validation_status: Optional[str]
    validation_reasoning: Optional[str]
    reporter_name: Optional[str]
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True


class AlertListOut(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AlertOut]


# ─── Action ──────────────────────────────────────────────────────────────────

class ActionCreate(BaseModel):
    alert_id: str
    actor_name: str
    actor_organization: Optional[str] = None
    actor_email: Optional[EmailStr] = None
    action_type: Optional[str] = None
    description: str = Field(..., min_length=20)
    resources_deployed: Optional[str] = None
    expected_completion: Optional[datetime] = None
    is_resolution_claim: bool = False


class ActionOut(BaseModel):
    id: str
    alert_id: str
    actor_name: str
    actor_organization: Optional[str]
    description: str
    action_type: Optional[str]
    is_resolution_claim: bool
    contradiction_flag: bool
    contradiction_score: Optional[float]
    submitted_at: datetime

    class Config:
        from_attributes = True


# ─── Validation ──────────────────────────────────────────────────────────────

class ValidationCreate(BaseModel):
    alert_id: str
    validator_name: str
    validator_org: Optional[str] = None
    method: str = Field(..., min_length=10)
    findings: str = Field(..., min_length=20)
    evidence_reviewed: Optional[str] = None
    community_feedback: Optional[str] = None
    recommendations: Optional[str] = None
    decision: str = Field(..., pattern="^(APPROVED|DISPUTED|INSUFFICIENT_EVIDENCE)$")


class ValidationOut(BaseModel):
    id: str
    alert_id: str
    validator_name: str
    validator_org: Optional[str]
    decision: str
    findings: str
    llm_coherence_score: Optional[float]
    nli_contradiction_score: Optional[float]
    validated_at: datetime

    class Config:
        from_attributes = True


# ─── Escalation ──────────────────────────────────────────────────────────────

class EscalateRequest(BaseModel):
    alert_id: str
    to_level: str
    reason: str = Field(..., min_length=10)


class EscalationHistoryOut(BaseModel):
    id: str
    alert_id: str
    from_level: Optional[str]
    to_level: str
    escalated_by_name: Optional[str]
    reason: Optional[str]
    sla_breached: bool
    escalated_at: datetime

    class Config:
        from_attributes = True


# ─── Dashboard / Analytics ───────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_alerts: int
    open_alerts: int
    closed_alerts: int
    pending_verification: int
    sla_breached: int
    by_severity: dict
    by_status: dict
    by_escalation_level: dict
    avg_resolution_hours: Optional[float]
    alerts_closed_with_evidence: int


class AlertTimeline(BaseModel):
    alert_id: str
    alert_code: str
    events: List[dict]
