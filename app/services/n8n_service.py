# app/services/n8n_service.py
"""
n8n webhook integration service.

Maps every governance event to your rithika19.app.n8n.cloud webhooks:

  N8N_ALERT_WEBHOOK              → /webhook/submit-alert
  N8N_ACTION_WEBHOOK             → /webhook/submit-action
  N8N_VALIDATE_WEBHOOK           → /webhook/validate-action
  N8N_ESCALATE_DISTRICT_WEBHOOK  → /webhook/escalate-district
  N8N_ESCALATE_STATE_WEBHOOK     → /webhook/escalate-state
  N8N_ALERT_STATUS_WEBHOOK       → /webhook/alert-status
  N8N_LIST_ALERTS_WEBHOOK        → /webhook/alerts
"""
import httpx
import structlog
from typing import Optional
from app.core.config import settings

logger = structlog.get_logger()


class N8NService:

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)

    # ─── Internal helper ─────────────────────────────────────────────────────

    async def _post(self, url: str, payload: dict, event_name: str) -> bool:
        """POST to any n8n webhook. Logs success/failure without raising."""
        if not url:
            logger.info(f"n8n {event_name} webhook not configured, skipping")
            return False
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"n8n {event_name} triggered",
                        url=url, status=response.status_code)
            return True
        except httpx.HTTPStatusError as e:
            logger.warning(f"n8n {event_name} HTTP error",
                           status=e.response.status_code, url=url)
            return False
        except Exception as e:
            logger.warning(f"n8n {event_name} failed", error=str(e), url=url)
            return False

    # ─── 1. New Alert → /webhook/submit-alert ────────────────────────────────

    async def notify_new_alert(self, alert_data: dict) -> bool:
        """
        Fired when a new alert is created.
        n8n: stores in data table → sends Gmail notification to Panchayat.
        """
        payload = {
            "alert_id":           alert_data.get("alert_code"),
            "panchayat_name":     alert_data.get("panchayat"),
            "district":           alert_data.get("district"),
            "state":              alert_data.get("state"),
            "severity":           alert_data.get("severity"),
            "description":        alert_data.get("description"),
            "households_affected": alert_data.get("households_affected", 0),
            "reporter_name":      alert_data.get("reporter_name"),
            "reporter_email":     alert_data.get("reporter_email"),
            "reporter_org":       alert_data.get("reporter_org"),
            "assigned_to":        alert_data.get("assigned_to"),
            "sla_hours":          alert_data.get("sla_hours"),
            "ml_risk_score":      alert_data.get("ml_risk_score"),
            "ml_predicted_severity": alert_data.get("ml_predicted_severity"),
            "status":             alert_data.get("status", "CREATED"),
            "submitted_at":       alert_data.get("submitted_at"),
        }
        return await self._post(settings.N8N_ALERT_WEBHOOK, payload, "submit-alert")

    # ─── 2. Action / Evidence → /webhook/submit-action ───────────────────────

    async def notify_action_submitted(self, action_data: dict, alert_data: dict) -> bool:
        """
        Fired when an actor submits an action or resolution claim.
        n8n: logs action → routes by type (Resolved / Escalate to District / State).
        """
        payload = {
            "alert_id":           alert_data.get("alert_code"),
            "action_type":        "Resolved" if action_data.get("is_resolution_claim") else "Action Taken",
            "action_description": action_data.get("description"),
            "organization":       action_data.get("actor_organization"),
            "action_by_name":     action_data.get("actor_name"),
            "action_by_email":    action_data.get("actor_email"),
            "resources_deployed": action_data.get("resources_deployed"),
            "is_resolution_claim": action_data.get("is_resolution_claim", False),
            "contradiction_flag": action_data.get("contradiction_flag", False),
            "contradiction_score": action_data.get("contradiction_score"),
        }
        return await self._post(settings.N8N_ACTION_WEBHOOK, payload, "submit-action")

    # ─── 3. Validation Decision → /webhook/validate-action ───────────────────

    async def notify_validation(self, validation_data: dict, alert_data: dict) -> bool:
        """
        Fired when an independent validator submits their decision.
        n8n: updates alert status → notifies resolution team / reporter.
        """
        payload = {
            "alert_id":             alert_data.get("alert_code"),
            "validator_name":       validation_data.get("validator_name"),
            "validator_org":        validation_data.get("validator_org"),
            "decision":             validation_data.get("decision"),      # APPROVED / DISPUTED / INSUFFICIENT_EVIDENCE
            "findings":             validation_data.get("findings"),
            "method":               validation_data.get("method"),
            "evidence_reviewed":    validation_data.get("evidence_reviewed"),
            "community_feedback":   validation_data.get("community_feedback"),
            "recommendations":      validation_data.get("recommendations"),
            "llm_coherence_score":  validation_data.get("llm_coherence_score"),
            "alert_new_status":     alert_data.get("status"),             # CLOSED / RESOLUTION_DISPUTED
            "validated_at":         validation_data.get("validated_at"),
        }
        return await self._post(settings.N8N_VALIDATE_WEBHOOK, payload, "validate-action")

    # ─── 4a. Escalate to District → /webhook/escalate-district ───────────────

    async def notify_escalate_district(self, alert_data: dict, reason: str,
                                        escalated_by: str = "System") -> bool:
        """
        Fired when alert is escalated to District level.
        n8n: notifies District Officer via Gmail.
        """
        payload = {
            "alert_id":       alert_data.get("alert_code"),
            "panchayat":      alert_data.get("panchayat"),
            "district":       alert_data.get("district"),
            "state":          alert_data.get("state"),
            "severity":       alert_data.get("severity"),
            "description":    alert_data.get("description"),
            "households_affected": alert_data.get("households_affected", 0),
            "escalated_by":   escalated_by,
            "reason":         reason,
            "escalated_at":   alert_data.get("updated_at"),
            "sla_hours":      alert_data.get("sla_hours"),
            "ml_risk_score":  alert_data.get("ml_risk_score"),
        }
        return await self._post(settings.N8N_ESCALATE_DISTRICT_WEBHOOK, payload, "escalate-district")

    # ─── 4b. Escalate to State → /webhook/escalate-state ─────────────────────

    async def notify_escalate_state(self, alert_data: dict, reason: str,
                                     escalated_by: str = "System") -> bool:
        """
        Fired when alert is escalated to State level.
        n8n: notifies State Water Board via Gmail.
        """
        payload = {
            "alert_id":       alert_data.get("alert_code"),
            "panchayat":      alert_data.get("panchayat"),
            "district":       alert_data.get("district"),
            "state":          alert_data.get("state"),
            "severity":       alert_data.get("severity"),
            "description":    alert_data.get("description"),
            "households_affected": alert_data.get("households_affected", 0),
            "escalated_by":   escalated_by,
            "reason":         reason,
            "escalated_at":   alert_data.get("updated_at"),
            "ml_risk_score":  alert_data.get("ml_risk_score"),
            "previous_escalation_level": alert_data.get("escalation_level"),
        }
        return await self._post(settings.N8N_ESCALATE_STATE_WEBHOOK, payload, "escalate-state")

    # ─── 5. Alert Status Sync → /webhook/alert-status ────────────────────────

    async def sync_alert_status(self, alert_data: dict) -> bool:
        """
        Fires whenever alert status changes.
        n8n: updates the data table record for live dashboard tracking.
        """
        payload = {
            "alert_id":          alert_data.get("alert_code"),
            "status":            alert_data.get("status"),
            "escalation_level":  alert_data.get("escalation_level"),
            "assigned_to":       alert_data.get("assigned_to"),
            "validation_status": alert_data.get("validation_status"),
            "updated_at":        alert_data.get("updated_at"),
            "closed_at":         alert_data.get("closed_at"),
        }
        return await self._post(settings.N8N_ALERT_STATUS_WEBHOOK, payload, "alert-status")

    # ─── 6. List Alerts Sync → /webhook/alerts ───────────────────────────────

    async def push_alerts_list(self, alerts: list) -> bool:
        """
        Pushes a summary list of open alerts to n8n.
        Useful for n8n to build a live dashboard or daily digest email.
        """
        payload = {
            "alerts": [
                {
                    "alert_id":         a.get("alert_code"),
                    "panchayat":        a.get("panchayat"),
                    "district":         a.get("district"),
                    "severity":         a.get("severity"),
                    "status":           a.get("status"),
                    "escalation_level": a.get("escalation_level"),
                    "assigned_to":      a.get("assigned_to"),
                    "created_at":       a.get("created_at"),
                    "sla_deadline":     a.get("sla_deadline"),
                }
                for a in alerts
            ],
            "total": len(alerts),
        }
        return await self._post(settings.N8N_LIST_ALERTS_WEBHOOK, payload, "alerts-list")

    # ─── Smart escalation router ──────────────────────────────────────────────

    async def notify_escalation(self, alert_data: dict, to_level: str,
                                 reason: str, escalated_by: str = "System") -> bool:
        """
        Routes to the correct escalation webhook based on to_level.
        Called by the alerts API for both manual and SLA-triggered escalations.
        """
        to_level = to_level.upper()
        if to_level == "STATE":
            return await self.notify_escalate_state(alert_data, reason, escalated_by)
        else:
            # DISTRICT, MANDAL, BLOCK all use district webhook
            return await self.notify_escalate_district(alert_data, reason, escalated_by)

    async def close(self):
        await self.client.aclose()


# ─── Singleton ────────────────────────────────────────────────────────────────

_n8n_service: Optional[N8NService] = None


def get_n8n_service() -> N8NService:
    global _n8n_service
    if _n8n_service is None:
        _n8n_service = N8NService()
    return _n8n_service
