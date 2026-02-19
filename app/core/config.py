# app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "JalSeva Water Governance Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database
    DATABASE_URL: str = "postgresql://postgres:Postgres@123@localhost:5432/water_governance"

    # Auth
    SECRET_KEY: str = "jalseva-super-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    # AI
    GEMINI_API_KEY: str = ""

    # n8n — base URL
    N8N_WEBHOOK_BASE_URL: Optional[str] = None

    # n8n — individual webhook endpoints (all from your .env)
    N8N_ALERT_WEBHOOK: Optional[str] = None           # POST new alert
    N8N_ACTION_WEBHOOK: Optional[str] = None          # POST action/evidence
    N8N_VALIDATE_WEBHOOK: Optional[str] = None        # POST validation decision
    N8N_ESCALATE_DISTRICT_WEBHOOK: Optional[str] = None   # POST escalate to district
    N8N_ESCALATE_STATE_WEBHOOK: Optional[str] = None      # POST escalate to state
    N8N_ALERT_STATUS_WEBHOOK: Optional[str] = None    # GET/POST alert status check
    N8N_LIST_ALERTS_WEBHOOK: Optional[str] = None     # GET list of alerts

    # Email contacts
    PANCHAYAT_EMAIL: str = "panchayat@example.gov.in"
    DISTRICT_EMAIL: str = "district@example.gov.in"
    STATE_EMAIL: str = "state@example.gov.in"
    VERIFICATION_TEAM_EMAIL: str = "verify@ngo-partner.org"

    # File storage
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # ML models
    WATER_GOVERNANCE_MODEL_PATH: str = "./pure_path/water_governance_model.pkl"
    WATER_MODEL_PATH: str = "./pure_path/water_model.pkl"

    # SLA (hours)
    SLA_LOW: int = 72
    SLA_MEDIUM: int = 48
    SLA_HIGH: int = 24
    SLA_CRITICAL: int = 6

    # NLI
    NLI_MODEL: str = "facebook/bart-large-mnli"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        env_file = "config/.env"
        case_sensitive = True


settings = Settings()
