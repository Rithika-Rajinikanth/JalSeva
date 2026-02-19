# app/core/graph.py
"""
LangGraph governance workflow — enhanced from original graph.py.
"""
import os
from datetime import datetime, timedelta
from typing_extensions import TypedDict
from typing import Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage
import structlog

logger = structlog.get_logger()


# ── State ─────────────────────────────────────────────────────────────────────

class GovernanceState(TypedDict, total=False):
    alert_id: str
    alert_code: str
    panchayat: str
    district: str
    state: str
    severity: str
    description: str
    households_affected: int
    water_source_type: str
    primary_concern: str
    ml_risk_score: float
    ml_predicted_severity: str
    ml_confidence: float
    validation_status: str
    validation_reasoning: str
    status: str
    escalation_level: str
    assigned_to: str
    sla_hours: int
    sla_deadline: str
    priority_score: int
    action_plan: str
    action_submitted: bool
    has_verified_evidence: bool
    verification_decision: str
    contradiction_score: float
    contradiction_flag: bool
    contradiction_reason: str
    processed_at: str


# ── Nodes ─────────────────────────────────────────────────────────────────────

def intake_node(state: GovernanceState) -> GovernanceState:
    state["status"] = "CREATED"
    state["processed_at"] = datetime.utcnow().isoformat()
    state["escalation_level"] = state.get("escalation_level", "PANCHAYAT")
    state["has_verified_evidence"] = state.get("has_verified_evidence", False)
    return state


def ml_scoring_node(state: GovernanceState) -> GovernanceState:
    try:
        from app.ml.ml_service import get_risk_scorer
        from app.core.config import settings

        scorer = get_risk_scorer(settings.WATER_GOVERNANCE_MODEL_PATH)
        risk_score, predicted_severity, confidence = scorer.predict(
            households_affected=state.get("households_affected", 0),
            severity_input=state.get("severity", "Medium"),
            district=state.get("district", ""),
            description_len=len(state.get("description", "")),
        )

        state["ml_risk_score"] = risk_score
        state["ml_predicted_severity"] = predicted_severity
        state["ml_confidence"] = confidence

        severity_rank = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
        if severity_rank.get(predicted_severity, 2) > severity_rank.get(state.get("severity", "Medium"), 2):
            state["severity"] = predicted_severity

        logger.info("ML scoring complete", risk_score=risk_score, predicted_severity=predicted_severity)
    except Exception as e:
        logger.warning("ML scoring skipped", error=str(e))

    return state


def validation_node(state: GovernanceState) -> GovernanceState:
    """
    LLM validation using Gemini.
    FIX: model name changed from 'gemini-2.5-flash' to 'gemini-1.5-flash'
         (gemini-2.5-flash does not exist in google-generativeai==0.7.2)
    """
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        from app.core.config import settings

        if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your-gemini-api-key-here":
            raise ValueError("GEMINI_API_KEY not configured")

        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",   # FIX: was gemini-2.5-flash (invalid in 0.7.2)
            temperature=0,
            google_api_key=settings.GEMINI_API_KEY
        )

        prompt = f"""You are a senior government water governance analyst for the Government of India.

Analyze this water scarcity alert and determine whether it warrants immediate action:

Panchayat: {state.get("panchayat", "N/A")}
District: {state.get("district", "N/A")}
State: {state.get("state", "N/A")}
Severity: {state.get("severity", "N/A")}
ML Risk Score: {state.get("ml_risk_score", "N/A")}
Description: {state.get("description", "N/A")}
Households Affected: {state.get("households_affected", 0)}
Water Source: {state.get("water_source_type", "N/A")}
Primary Concern: {state.get("primary_concern", "N/A")}

Governance Rules:
1. Any report affecting 100+ households requires Approved status
2. High or Critical severity or ML risk score >0.6 requires Approved status
3. Vague descriptions with no specifics → Pending Review

Respond STRICTLY in this format:
Status: <Approved or Pending Review>
Reason: <2-3 sentence reasoning>
Urgency: <Immediate / Within 24 hours / Within 48 hours / Within 72 hours>"""

        response = llm.invoke([HumanMessage(content=prompt)])
        output = response.content
        state["validation_status"] = "Approved" if "Approved" in output else "Pending Review"
        state["validation_reasoning"] = output
        logger.info("LLM validation complete", status=state["validation_status"])

    except Exception as e:
        logger.warning("LLM validation failed, using rule-based fallback", error=str(e))
        households = state.get("households_affected", 0)
        severity = state.get("severity", "Low")
        risk_score = state.get("ml_risk_score", 0.0) or 0.0

        if households >= 100 or severity in ("High", "Critical") or risk_score > 0.6:
            state["validation_status"] = "Approved"
            state["validation_reasoning"] = "Rule-based approval: criteria met (households/severity/ML score)."
        else:
            state["validation_status"] = "Pending Review"
            state["validation_reasoning"] = "Rule-based: requires manual review."

    return state


def verify_node(state: GovernanceState) -> GovernanceState:
    if state.get("validation_status") == "Approved":
        state["status"] = "VALIDATED"
    else:
        state["status"] = "NEEDS_ESCALATION"
    return state


def routing_node(state: GovernanceState) -> GovernanceState:
    severity = state.get("severity", "Low")
    risk_score = state.get("ml_risk_score", 0.0) or 0.0
    households = state.get("households_affected", 0)

    if severity == "Critical" or risk_score >= 0.85 or households >= 500:
        assigned_to, sla_hours, priority_score, escalation = "STATE_OFFICER", 6, 4, "STATE"
    elif severity == "High" or risk_score >= 0.6 or households >= 200:
        assigned_to, sla_hours, priority_score, escalation = "DISTRICT_OFFICER", 24, 3, "DISTRICT"
    elif severity == "Medium" or risk_score >= 0.4 or households >= 50:
        assigned_to, sla_hours, priority_score, escalation = "MANDAL_OFFICER", 48, 2, "MANDAL"
    else:
        assigned_to, sla_hours, priority_score, escalation = "BLOCK_OFFICER", 72, 1, "BLOCK"

    deadline = datetime.utcnow() + timedelta(hours=sla_hours)
    state.update({
        "assigned_to": assigned_to,
        "sla_hours": sla_hours,
        "sla_deadline": deadline.isoformat(),
        "priority_score": priority_score,
        "escalation_level": escalation,
    })
    return state


def action_node(state: GovernanceState) -> GovernanceState:
    severity = state.get("severity", "Medium")
    action_plans = {
        "Critical": "IMMEDIATE: Deploy emergency water tankers. Engage district collector. Initiate emergency borewell drilling.",
        "High":     "Dispatch water tankers and initiate groundwater survey. Engage drilling contractor within 48 hours.",
        "Medium":   "Coordinate with block water supply office. Schedule field assessment within 5 days.",
        "Low":      "Log for monitoring. Schedule routine inspection. Alert Panchayat water committee.",
    }
    state["action_plan"] = action_plans.get(severity, action_plans["Medium"])
    state["status"] = "ASSIGNED"
    return state


def escalation_node(state: GovernanceState) -> GovernanceState:
    current_level = state.get("escalation_level", "PANCHAYAT")
    chain = ["PANCHAYAT", "BLOCK", "MANDAL", "DISTRICT", "STATE"]
    try:
        next_idx = min(chain.index(current_level) + 1, len(chain) - 1)
        new_level = chain[next_idx]
    except ValueError:
        new_level = "DISTRICT"
    state["escalation_level"] = new_level
    state["status"] = f"ESCALATED_{new_level}"
    return state


def evidence_gate_node(state: GovernanceState) -> GovernanceState:
    if state.get("has_verified_evidence") and state.get("verification_decision") == "APPROVED":
        state["status"] = "CLOSED"
    else:
        state["status"] = "PENDING_VERIFICATION"
    return state


# ── Routing functions ─────────────────────────────────────────────────────────

def post_verify_route(state: GovernanceState) -> str:
    return "route" if state.get("status") == "VALIDATED" else "escalate"

def post_route_decision(state: GovernanceState) -> str:
    return "action" if state.get("validation_status") == "Approved" else "escalate"

def post_action_route(state: GovernanceState) -> str:
    return "evidence_gate" if state.get("action_submitted") else "end"


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph():
    builder = StateGraph(GovernanceState)

    builder.add_node("intake",        intake_node)
    builder.add_node("ml_score",      ml_scoring_node)
    builder.add_node("validate",      validation_node)
    builder.add_node("verify",        verify_node)
    builder.add_node("route",         routing_node)
    builder.add_node("action",        action_node)
    builder.add_node("escalate",      escalation_node)
    builder.add_node("evidence_gate", evidence_gate_node)

    builder.set_entry_point("intake")
    builder.add_edge("intake",   "ml_score")
    builder.add_edge("ml_score", "validate")
    builder.add_edge("validate", "verify")

    builder.add_conditional_edges("verify", post_verify_route,
                                  {"route": "route", "escalate": "escalate"})
    builder.add_conditional_edges("route",  post_route_decision,
                                  {"action": "action", "escalate": "escalate"})
    builder.add_conditional_edges("action", post_action_route,
                                  {"evidence_gate": "evidence_gate", "end": END})

    builder.add_edge("evidence_gate", END)
    builder.add_edge("escalate",      END)

    return builder.compile()


graph = build_graph()