# 💧 JalSeva — Water Governance Accountability Platform

A production-grade, AI-powered water scarcity governance system for India's Panchayati Raj institutions.

**JalSeva** ensures that water-risk alerts move from identification to verified resolution — not just reported, but owned, acted upon, and closed only after credible evidence is recorded.

## Architecture Inspiration

This system synthesizes patterns from three proven governance platforms:

| Platform | Pattern Borrowed |
|----------|-----------------|
| [Ushahidi](https://github.com/ushahidi) | Alert intake, contradictory evidence handling, verification workflows |
| [FixMyStreet](https://github.com/mysociety/fixmystreet) | Closure requires evidence, ownership transparency |
| [Sahana Eden](https://github.com/sahana/eden) | Multi-tier authority coordination, responsibility assignment |
| [mWater](https://github.com/mWater) | Field validation, photo evidence, audit trails |
| [Akvo RSR](https://github.com/akvo/akvo-rsr) | Who claimed to act, what evidence exists, outcome validation |

## System Overview

```
Alert Submission (Panchayat / NGO / Citizen)
        │
        ▼
   [Intake Node] → Auto-ID generation, metadata enrichment
        │
        ▼
   [ML Risk Scorer] ← water_governance_model.pkl (pure_path)
        │
        ▼
   [LLM Validation] ← Gemini 2.5 Flash — evidence coherence analysis
        │
        ▼
   [Routing Node] → Assign: Block / Mandal / District / State officer
        │
        ▼
   [Action Node or Escalation Node]
        │
        ▼
   [Independent Verification] ← NGO / Student volunteer / Audit
        │
        ▼
   [Closure Gate] ← Closed ONLY after verified evidence
```

## Key Features

- **Alert lifecycle management** — every alert has an owner, SLA, and cannot close without evidence
- **Multi-tier escalation** — Panchayat → Block → District → State with automatic SLA enforcement
- **LLM-powered validation** — Gemini analyzes evidence coherence and flags contradictions
- **ML risk scoring** — pre-trained water stress model predicts severity before human review
- **Evidence vault** — all documents, photos, and reports linked immutably to each alert
- **Contradiction detection** — NLI-based model flags conflicting resolution claims
- **Audit trail** — every state transition is logged with timestamp and actor
- **n8n workflow integration** — external notification and escalation automation
- **Role-based access** — Panchayat, District, State, NGO, Validator, Admin roles

## Stack

- **Backend**: FastAPI + SQLAlchemy + PostgreSQL
- **AI/ML**: LangGraph + Google Gemini + scikit-learn (water_governance_model.pkl)
- **NLI**: facebook/bart-large-mnli (contradiction detection)
- **Automation**: n8n webhook integration
- **Auth**: JWT with role-based permissions
- **Async**: background tasks for ML inference and notifications

## Quick Start

```bash
# 1. Clone and install
pip install -r requirements.txt

# 2. Set environment variables
cp config/.env.example config/.env
# Edit config/.env with your DATABASE_URL and GEMINI_API_KEY

# 3. Initialize database
python -m app.core.init_db

# 4. Run
uvicorn app.main:app --reload --port 8000

# 5. API Docs
open http://localhost:8000/docs
```

## Governance Principles

1. **No unowned alerts** — every alert is assigned within SLA or auto-escalated
2. **Evidence-gated closure** — `CLOSED` status requires validator-approved evidence
3. **Contradiction flagging** — AI detects when resolution claims conflict with field reports
4. **Immutable audit trail** — all transitions are append-only and actor-stamped
5. **SLA enforcement** — automatic escalation when deadlines are breached
