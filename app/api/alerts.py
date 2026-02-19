# app/api/alerts.py
"""
Alert API endpoints — full governance lifecycle.
Every state-changing event fires the matching n8n webhook.
"""
import aiofiles
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Optional, List

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.schemas.schemas import (
    AlertCreate, AlertOut, AlertListOut,
    ActionCreate, ActionOut,
    ValidationCreate, ValidationOut,
    EscalateRequest, EscalationHistoryOut,
    DashboardStats,
)
from app.services.alert_service import AlertService
from app.services.n8n_service import get_n8n_service
from app.models.all_models import Alert, Action, Validation, EscalationHistory, Evidence
from app.core.config import settings
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])
service = AlertService()


# ─── Shared helper ────────────────────────────────────────────────────────────

def _alert_to_dict(alert: Alert) -> dict:
    """Convert Alert ORM → plain dict for all n8n webhook payloads."""
    return {
        "alert_code":             alert.alert_code,
        "panchayat":              alert.panchayat,
        "district":               alert.district,
        "state":                  alert.state,
        "severity":               alert.severity,
        "description":            alert.description,
        "households_affected":    alert.households_affected,
        "reporter_name":          alert.reporter_name,
        "reporter_email":         alert.reporter_email,
        "reporter_org":           alert.reporter_org,
        "assigned_to":            alert.assigned_to,
        "sla_hours":              alert.sla_hours,
        "sla_deadline":           alert.sla_deadline.isoformat() if alert.sla_deadline else None,
        "status":                 alert.status,
        "escalation_level":       alert.escalation_level,
        "ml_risk_score":          alert.ml_risk_score,
        "ml_predicted_severity":  alert.ml_predicted_severity,
        "validation_status":      alert.validation_status,
        "updated_at":             alert.updated_at.isoformat() if alert.updated_at else None,
        "closed_at":              alert.closed_at.isoformat() if alert.closed_at else None,
        "submitted_at":           alert.created_at.isoformat() if alert.created_at else None,
    }


# ─── n8n background task helpers ──────────────────────────────────────────────

async def _n8n_new_alert(alert: Alert):
    """submit-alert + alert-status"""
    n8n = get_n8n_service()
    d = _alert_to_dict(alert)
    await n8n.notify_new_alert(d)
    await n8n.sync_alert_status(d)


async def _n8n_action(action: Action, alert: Alert):
    """submit-action + alert-status"""
    n8n = get_n8n_service()
    await n8n.notify_action_submitted(
        {
            "description":         action.description,
            "actor_name":          action.actor_name,
            "actor_organization":  action.actor_organization,
            "actor_email":         action.actor_email,
            "action_type":         action.action_type,
            "is_resolution_claim": action.is_resolution_claim,
            "resources_deployed":  action.resources_deployed,
            "contradiction_flag":  action.contradiction_flag,
            "contradiction_score": action.contradiction_score,
        },
        _alert_to_dict(alert),
    )
    await n8n.sync_alert_status(_alert_to_dict(alert))


async def _n8n_validation(validation: Validation, alert: Alert):
    """validate-action + alert-status"""
    n8n = get_n8n_service()
    await n8n.notify_validation(
        {
            "validator_name":      validation.validator_name,
            "validator_org":       validation.validator_org,
            "decision":            validation.decision,
            "findings":            validation.findings,
            "method":              validation.method,
            "evidence_reviewed":   validation.evidence_reviewed,
            "community_feedback":  validation.community_feedback,
            "recommendations":     validation.recommendations,
            "llm_coherence_score": validation.llm_coherence_score,
            "validated_at":        validation.validated_at.isoformat() if validation.validated_at else None,
        },
        _alert_to_dict(alert),
    )
    await n8n.sync_alert_status(_alert_to_dict(alert))


async def _n8n_escalation(alert: Alert, to_level: str, reason: str, escalated_by: str):
    """escalate-district OR escalate-state + alert-status"""
    n8n = get_n8n_service()
    await n8n.notify_escalation(_alert_to_dict(alert), to_level, reason, escalated_by=escalated_by)
    await n8n.sync_alert_status(_alert_to_dict(alert))


# ─── 1. Create Alert ──────────────────────────────────────────────────────────

@router.post("/", response_model=AlertOut, status_code=201,
             summary="Submit a new water scarcity alert")
async def create_alert(
    data: AlertCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Submits a new alert and runs the full governance pipeline:
    ML scoring → LLM validation → routing → SLA assignment.
    n8n: fires **submit-alert** + **alert-status**.
    """
    try:
        alert = service.create_alert(db, data, reporter_id=current_user.id)
        background_tasks.add_task(_n8n_new_alert, alert)
        return alert
    except Exception as e:
        logger.error("Alert creation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─── 2. List Alerts ───────────────────────────────────────────────────────────

@router.get("/", response_model=AlertListOut)
def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    district: Optional[str] = None,
    escalation_level: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    skip = (page - 1) * page_size
    total, items = service.list_alerts(
        db, skip=skip, limit=page_size,
        status=status, severity=severity,
        district=district, escalation_level=escalation_level,
    )
    return AlertListOut(total=total, page=page, page_size=page_size, items=items)


# ─── 3. Get Single Alert ──────────────────────────────────────────────────────

@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    alert = service.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


# ─── 4. Alert Timeline ────────────────────────────────────────────────────────

@router.get("/{alert_id}/timeline")
def get_alert_timeline(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    alert = service.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    events = service.get_alert_timeline(db, alert_id)
    return {"alert_id": alert_id, "alert_code": alert.alert_code, "events": events}


# ─── 5. Submit Action ─────────────────────────────────────────────────────────

@router.post("/{alert_id}/actions", response_model=ActionOut, status_code=201,
             summary="Submit an action or resolution claim")
async def submit_action(
    alert_id: str,
    data: ActionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Records an action or resolution claim.
    is_resolution_claim=true → NLI contradiction check, alert → PENDING_VERIFICATION.
    n8n: fires **submit-action** + **alert-status**.
    """
    data.alert_id = alert_id
    try:
        alert, action = service.submit_action(db, data, actor_id=current_user.id)
        background_tasks.add_task(_n8n_action, action, alert)
        return action
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── 6. List Actions ─────────────────────────────────────────────────────────

@router.get("/{alert_id}/actions", response_model=List[ActionOut])
def list_actions(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return db.query(Action).filter(Action.alert_id == alert_id).all()


# ─── 7. Upload Evidence ───────────────────────────────────────────────────────

@router.post("/{alert_id}/evidence", status_code=201,
             summary="Upload evidence file (photo/document/water test)")
async def upload_evidence(
    alert_id: str,
    file: UploadFile = File(...),
    description: Optional[str] = None,
    evidence_type: str = "DOCUMENT",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    alert = service.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    content = await file.read()
    if len(content) / (1024 * 1024) > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=413,
                            detail=f"File too large. Max {settings.MAX_UPLOAD_SIZE_MB}MB")

    upload_dir = os.path.join(settings.UPLOAD_DIR, alert_id)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    evidence = Evidence(
        alert_id=alert_id,
        uploaded_by_id=current_user.id,
        evidence_type=evidence_type,
        filename=file.filename,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
        description=description,
        lat=lat,
        lng=lng,
    )
    db.add(evidence)
    db.commit()
    return {"id": evidence.id, "filename": file.filename,
            "evidence_type": evidence_type, "size_bytes": len(content)}


# ─── 8. Submit Validation ─────────────────────────────────────────────────────

@router.post("/{alert_id}/validate", response_model=ValidationOut, status_code=201,
             summary="Independent validation — only VALIDATOR/NGO/ADMIN")
async def submit_validation(
    alert_id: str,
    data: ValidationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("VALIDATOR", "NGO", "ADMIN")),
):
    """
    APPROVED  → alert CLOSED. n8n fires **validate-action** + **alert-status**.
    DISPUTED  → alert RESOLUTION_DISPUTED.
    INSUFFICIENT_EVIDENCE → stays PENDING_VERIFICATION.
    """
    data.alert_id = alert_id
    try:
        alert, validation = service.submit_validation(db, data, validator_id=current_user.id)
        background_tasks.add_task(_n8n_validation, validation, alert)
        return validation
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 9. Escalate Alert ────────────────────────────────────────────────────────

@router.post("/{alert_id}/escalate",
             summary="Escalate alert to District or State level")
async def escalate_alert(
    alert_id: str,
    data: EscalateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    to_level=DISTRICT → fires **escalate-district** webhook.
    to_level=STATE    → fires **escalate-state** webhook.
    Also fires **alert-status** for data table sync.
    """
    data.alert_id = alert_id
    try:
        alert = service.escalate_alert(
            db, data,
            escalated_by_id=current_user.id,
            escalated_by_name=current_user.full_name,
        )
        background_tasks.add_task(
            _n8n_escalation, alert, data.to_level, data.reason, current_user.full_name
        )
        return {
            "alert_code":       alert.alert_code,
            "new_status":       alert.status,
            "escalation_level": alert.escalation_level,
            "n8n_webhook":      f"escalate-{'state' if data.to_level.upper() == 'STATE' else 'district'}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 10. Escalation History ───────────────────────────────────────────────────

@router.get("/{alert_id}/escalations", response_model=List[EscalationHistoryOut])
def get_escalation_history(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return db.query(EscalationHistory).filter(
        EscalationHistory.alert_id == alert_id
    ).order_by(EscalationHistory.escalated_at.asc()).all()


# ─── 11. Dashboard ────────────────────────────────────────────────────────────

@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return service.get_dashboard_stats(db)


# ─── 12. SLA Check (admin) ────────────────────────────────────────────────────

@router.post("/admin/check-sla")
async def check_sla_breaches(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    escalated = service.check_sla_breaches(db)
    for alert in escalated:
        background_tasks.add_task(
            _n8n_escalation, alert, alert.escalation_level,
            "Auto-escalated: SLA deadline breached", "JalSeva SLA Engine"
        )
    return {"escalated_count": len(escalated), "alerts": [a.alert_code for a in escalated]}
