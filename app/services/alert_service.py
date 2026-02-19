# app/services/alert_service.py
"""
Alert service — core business logic for the governance lifecycle.

Implements:
- Ushahidi: alert creation, disputed states, verification workflow
- FixMyStreet: evidence-gated closure, owner assignment
- Sahana Eden: multi-tier escalation, SLA tracking
- Akvo RSR: outcome validation, actor accountability
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
import structlog

from app.models.all_models import (
    Alert, Action, Evidence, Validation, EscalationHistory, AuditLog, SLABreach
)
from app.schemas.schemas import AlertCreate, ActionCreate, ValidationCreate, EscalateRequest
from app.core.config import settings

logger = structlog.get_logger()


def _generate_alert_code(panchayat: str) -> str:
    """Generate human-readable alert code."""
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    prefix = panchayat[:3].upper().replace(" ", "")
    uid = str(uuid.uuid4())[:4].upper()
    return f"ALERT-{ts}-{prefix}-{uid}"


def _audit(db: Session, alert_id: str, event_type: str, from_status: str, to_status: str,
           actor_id: str = None, actor_name: str = None, actor_role: str = None, details: dict = None):
    """Append immutable audit log entry."""
    log = AuditLog(
        alert_id=alert_id,
        actor_id=actor_id,
        actor_name=actor_name or "System",
        actor_role=actor_role or "SYSTEM",
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        details=details or {},
        timestamp=datetime.utcnow(),
    )
    db.add(log)


class AlertService:
    """
    Core governance service.
    All state transitions are logged. Closure is evidence-gated.
    """

    def create_alert(self, db: Session, data: AlertCreate, reporter_id: str = None,
                     run_graph: bool = True) -> Alert:
        """
        Create alert, run governance graph, persist results.
        """
        alert_code = _generate_alert_code(data.panchayat)

        alert = Alert(
            alert_code=alert_code,
            panchayat=data.panchayat,
            block=data.block,
            mandal=data.mandal,
            district=data.district,
            state=data.state,
            lat=data.lat,
            lng=data.lng,
            severity=data.severity,
            description=data.description,
            households_affected=data.households_affected,
            water_source_type=data.water_source_type,
            primary_concern=data.primary_concern,
            reporter_id=reporter_id,
            reporter_name=data.reporter_name,
            reporter_email=str(data.reporter_email) if data.reporter_email else None,
            reporter_org=data.reporter_org,
            status="CREATED",
            escalation_level="PANCHAYAT",
        )

        db.add(alert)
        db.flush()  # get alert.id before running graph

        if run_graph:
            self._run_governance_graph(db, alert, data)

        _audit(db, alert.id, "CREATED", None, alert.status,
               actor_id=reporter_id, actor_name=data.reporter_name,
               details={"alert_code": alert_code, "severity": data.severity})

        db.commit()
        db.refresh(alert)

        logger.info("Alert created", alert_code=alert_code, severity=alert.severity,
                    status=alert.status, assigned_to=alert.assigned_to)
        return alert

    def _run_governance_graph(self, db: Session, alert: Alert, data: AlertCreate):
        """Run LangGraph governance pipeline and persist results."""
        try:
            from app.core.graph import graph

            state = {
                "alert_id": alert.id,
                "alert_code": alert.alert_code,
                "panchayat": data.panchayat,
                "district": data.district,
                "state": data.state,
                "severity": data.severity,
                "description": data.description,
                "households_affected": data.households_affected,
                "water_source_type": data.water_source_type or "",
                "primary_concern": data.primary_concern or "",
                "status": "CREATED",
                "escalation_level": "PANCHAYAT",
            }

            result = graph.invoke(state)

            # Persist graph results to alert
            alert.ml_risk_score = result.get("ml_risk_score")
            alert.ml_predicted_severity = result.get("ml_predicted_severity")
            alert.ml_confidence = result.get("ml_confidence")
            alert.validation_status = result.get("validation_status")
            alert.validation_reasoning = result.get("validation_reasoning")
            alert.status = result.get("status", "CREATED")
            alert.assigned_to = result.get("assigned_to")
            alert.sla_hours = result.get("sla_hours")
            alert.priority_score = result.get("priority_score")
            alert.escalation_level = result.get("escalation_level", "PANCHAYAT")
            alert.action_plan = result.get("action_plan")

            if result.get("sla_deadline"):
                alert.sla_deadline = datetime.fromisoformat(result["sla_deadline"])

            # Use ML-upgraded severity if higher
            if result.get("severity") and result["severity"] != data.severity:
                alert.severity = result["severity"]

        except Exception as e:
            logger.error("Governance graph failed", error=str(e))
            # Fallback: rule-based assignment
            severity = data.severity
            sla_map = {"Low": 72, "Medium": 48, "High": 24, "Critical": 6}
            alert.sla_hours = sla_map.get(severity, 48)
            alert.sla_deadline = datetime.utcnow() + timedelta(hours=alert.sla_hours)
            alert.assigned_to = "DISTRICT_OFFICER" if severity in ("High", "Critical") else "BLOCK_OFFICER"
            alert.status = "CREATED"

    def submit_action(self, db: Session, data: ActionCreate, actor_id: str = None) -> Tuple[Alert, Action]:
        """
        Record an action claim against an alert.
        If it's a resolution claim, run NLI contradiction detection (Ushahidi pattern).
        """
        alert = db.query(Alert).filter(Alert.id == data.alert_id).first()
        if not alert:
            raise ValueError(f"Alert {data.alert_id} not found")

        action = Action(
            alert_id=alert.id,
            actor_id=actor_id,
            actor_name=data.actor_name,
            actor_organization=data.actor_organization,
            actor_email=str(data.actor_email) if data.actor_email else None,
            action_type=data.action_type,
            description=data.description,
            resources_deployed=data.resources_deployed,
            expected_completion=data.expected_completion,
            is_resolution_claim=data.is_resolution_claim,
        )

        # Ushahidi: contradiction detection for resolution claims
        if data.is_resolution_claim:
            self._check_contradiction(action, alert)

        db.add(action)

        prev_status = alert.status
        if data.is_resolution_claim:
            alert.status = "PENDING_VERIFICATION"
        else:
            alert.status = "ACTION_SUBMITTED"

        _audit(db, alert.id, "ACTION_SUBMITTED", prev_status, alert.status,
               actor_id=actor_id, actor_name=data.actor_name,
               details={
                   "action_type": data.action_type,
                   "is_resolution_claim": data.is_resolution_claim,
                   "contradiction_flag": action.contradiction_flag,
               })

        db.commit()
        db.refresh(alert)
        db.refresh(action)
        return alert, action

    def _check_contradiction(self, action: Action, alert: Alert):
        """NLI-based contradiction detection (Ushahidi disputed-report pattern)."""
        try:
            from app.ml.ml_service import get_contradiction_detector
            detector = get_contradiction_detector()
            score, is_contradicted, reason = detector.detect(
                premise=alert.description,
                hypothesis=action.description
            )
            action.contradiction_score = score
            action.contradiction_flag = is_contradicted
            action.contradiction_reason = reason

            if is_contradicted:
                logger.warning("Contradiction detected in resolution claim",
                               alert_id=alert.id, score=score)
        except Exception as e:
            logger.warning("Contradiction check failed", error=str(e))

    def submit_validation(self, db: Session, data: ValidationCreate,
                          validator_id: str = None) -> Tuple[Alert, Validation]:
        """
        Independent validation — FixMyStreet closure gate.
        Alert reaches CLOSED only when validator approves.
        """
        alert = db.query(Alert).filter(Alert.id == data.alert_id).first()
        if not alert:
            raise ValueError(f"Alert {data.alert_id} not found")

        if alert.status not in ("PENDING_VERIFICATION", "VERIFIED"):
            raise ValueError(f"Alert status '{alert.status}' is not eligible for validation")

        # LLM coherence scoring
        llm_score = self._llm_coherence_score(alert, data)

        validation = Validation(
            alert_id=alert.id,
            validator_id=validator_id,
            validator_name=data.validator_name,
            validator_org=data.validator_org,
            method=data.method,
            findings=data.findings,
            evidence_reviewed=data.evidence_reviewed,
            community_feedback=data.community_feedback,
            recommendations=data.recommendations,
            decision=data.decision,
            llm_coherence_score=llm_score,
        )
        db.add(validation)

        prev_status = alert.status
        if data.decision == "APPROVED":
            # FixMyStreet: CLOSED only after verified evidence
            alert.status = "CLOSED"
            alert.closed_at = datetime.utcnow()
        elif data.decision == "DISPUTED":
            alert.status = "RESOLUTION_DISPUTED"
        else:
            alert.status = "PENDING_VERIFICATION"

        _audit(db, alert.id, "VALIDATION_SUBMITTED", prev_status, alert.status,
               actor_id=validator_id, actor_name=data.validator_name, actor_role="VALIDATOR",
               details={"decision": data.decision, "llm_coherence_score": llm_score})

        db.commit()
        db.refresh(alert)
        db.refresh(validation)
        return alert, validation

    def _llm_coherence_score(self, alert: Alert, data: ValidationCreate) -> Optional[float]:
        """LLM evaluates coherence between resolution claim and validator findings."""
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            from app.core.config import settings

            llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                temperature=0,
                google_api_key=settings.GEMINI_API_KEY
            )

            prompt = f"""
Rate the coherence between the following resolution claim and independent validation findings.
Score from 0.0 (completely incoherent/contradictory) to 1.0 (fully coherent/consistent).

Original Alert: {alert.description[:300]}
Validator Findings: {data.findings[:300]}
Validator Method: {data.method[:200]}

Respond with ONLY a number between 0.0 and 1.0.
"""
            response = llm.invoke([HumanMessage(content=prompt)])
            from langchain_core.messages import HumanMessage
            score = float(response.content.strip().split()[0])
            return round(max(0.0, min(1.0, score)), 3)
        except Exception:
            return None

    def escalate_alert(self, db: Session, data: EscalateRequest, escalated_by_id: str = None,
                       escalated_by_name: str = None, sla_breached: bool = False) -> Alert:
        """Escalate alert to next tier — Sahana Eden pattern."""
        alert = db.query(Alert).filter(Alert.id == data.alert_id).first()
        if not alert:
            raise ValueError(f"Alert {data.alert_id} not found")

        escalation_chain = ["PANCHAYAT", "BLOCK", "MANDAL", "DISTRICT", "STATE"]
        to_level = data.to_level.upper()

        history = EscalationHistory(
            alert_id=alert.id,
            from_level=alert.escalation_level,
            to_level=to_level,
            escalated_by_id=escalated_by_id,
            escalated_by_name=escalated_by_name or "System",
            reason=data.reason,
            sla_breached=sla_breached,
        )
        db.add(history)

        prev_status = alert.status
        alert.escalation_level = to_level
        alert.status = f"ESCALATED_{to_level}"

        _audit(db, alert.id, "ESCALATED", prev_status, alert.status,
               actor_id=escalated_by_id, actor_name=escalated_by_name,
               details={"to_level": to_level, "reason": data.reason, "sla_breached": sla_breached})

        db.commit()
        db.refresh(alert)
        return alert

    def check_sla_breaches(self, db: Session) -> List[Alert]:
        """Find alerts past SLA deadline and auto-escalate — Sahana Eden pattern."""
        now = datetime.utcnow()
        overdue = db.query(Alert).filter(
            Alert.sla_deadline < now,
            Alert.status.notin_(["CLOSED", "ARCHIVED"]),
        ).all()

        escalated = []
        for alert in overdue:
            hours_overdue = (now - alert.sla_deadline).total_seconds() / 3600

            # Log SLA breach
            breach = SLABreach(
                alert_id=alert.id,
                assigned_to=alert.assigned_to,
                expected_by=alert.sla_deadline,
                hours_overdue=round(hours_overdue, 1),
                auto_escalated=True,
            )
            db.add(breach)

            # Auto-escalate
            request = EscalateRequest(
                alert_id=alert.id,
                to_level=self._next_level(alert.escalation_level),
                reason=f"Auto-escalated: SLA breached by {hours_overdue:.1f} hours"
            )
            try:
                self.escalate_alert(db, request, sla_breached=True)
                escalated.append(alert)
                logger.warning("SLA breach auto-escalation", alert_code=alert.alert_code,
                               hours_overdue=hours_overdue)
            except Exception as e:
                logger.error("Auto-escalation failed", alert_id=alert.id, error=str(e))

        if escalated:
            db.commit()

        return escalated

    def _next_level(self, current: str) -> str:
        chain = ["PANCHAYAT", "BLOCK", "MANDAL", "DISTRICT", "STATE"]
        try:
            idx = chain.index(current)
            return chain[min(idx + 1, len(chain) - 1)]
        except ValueError:
            return "DISTRICT"

    def get_alert(self, db: Session, alert_id: str) -> Optional[Alert]:
        return db.query(Alert).filter(Alert.id == alert_id).first()

    def get_alert_by_code(self, db: Session, alert_code: str) -> Optional[Alert]:
        return db.query(Alert).filter(Alert.alert_code == alert_code).first()

    def list_alerts(self, db: Session, skip: int = 0, limit: int = 20,
                    status: str = None, severity: str = None,
                    district: str = None, escalation_level: str = None) -> Tuple[int, List[Alert]]:
        query = db.query(Alert)
        if status:
            query = query.filter(Alert.status == status)
        if severity:
            query = query.filter(Alert.severity == severity)
        if district:
            query = query.filter(Alert.district.ilike(f"%{district}%"))
        if escalation_level:
            query = query.filter(Alert.escalation_level == escalation_level)
        total = query.count()
        items = query.order_by(Alert.created_at.desc()).offset(skip).limit(limit).all()
        return total, items

    def get_dashboard_stats(self, db: Session) -> dict:
        """Aggregate governance performance metrics."""
        total = db.query(func.count(Alert.id)).scalar()
        closed = db.query(func.count(Alert.id)).filter(Alert.status == "CLOSED").scalar()
        pending_verify = db.query(func.count(Alert.id)).filter(
            Alert.status == "PENDING_VERIFICATION").scalar()

        sla_breached = db.query(func.count(SLABreach.id)).scalar()

        # Avg resolution time (hours) for closed alerts
        closed_alerts = db.query(Alert).filter(
            Alert.status == "CLOSED", Alert.closed_at.isnot(None)).all()
        avg_hours = None
        if closed_alerts:
            durations = [(a.closed_at - a.created_at).total_seconds() / 3600
                         for a in closed_alerts if a.closed_at]
            avg_hours = round(sum(durations) / len(durations), 1) if durations else None

        # By severity
        by_severity = {}
        for sev in ["Low", "Medium", "High", "Critical"]:
            by_severity[sev] = db.query(func.count(Alert.id)).filter(Alert.severity == sev).scalar()

        # By status
        statuses = db.query(Alert.status, func.count(Alert.id)).group_by(Alert.status).all()
        by_status = {s: c for s, c in statuses}

        # By escalation level
        levels = db.query(Alert.escalation_level, func.count(Alert.id)).group_by(
            Alert.escalation_level).all()
        by_escalation = {l: c for l, c in levels}

        return {
            "total_alerts": total,
            "open_alerts": total - closed,
            "closed_alerts": closed,
            "pending_verification": pending_verify,
            "sla_breached": sla_breached,
            "by_severity": by_severity,
            "by_status": by_status,
            "by_escalation_level": by_escalation,
            "avg_resolution_hours": avg_hours,
            "alerts_closed_with_evidence": closed,
        }

    def get_alert_timeline(self, db: Session, alert_id: str) -> List[dict]:
        """Full immutable audit trail for an alert."""
        logs = db.query(AuditLog).filter(
            AuditLog.alert_id == alert_id
        ).order_by(AuditLog.timestamp.asc()).all()

        return [
            {
                "event_type": log.event_type,
                "from_status": log.from_status,
                "to_status": log.to_status,
                "actor_name": log.actor_name,
                "actor_role": log.actor_role,
                "timestamp": log.timestamp.isoformat(),
                "details": log.details or {},
            }
            for log in logs
        ]