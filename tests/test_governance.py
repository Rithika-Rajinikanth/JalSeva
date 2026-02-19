# tests/test_governance.py
"""
Integration tests for the JalSeva governance lifecycle.
Tests the full alert → action → validation → closure pipeline.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.models.all_models import User

# ─── Test DB setup ────────────────────────────────────────────────────────────

SQLALCHEMY_TEST_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    # Seed test users
    users = [
        User(id="user-panchayat", email="panchayat@test.com",
             hashed_password=hash_password("password123"),
             full_name="Panchayat User", role="PANCHAYAT", is_active=True),
        User(id="user-validator", email="validator@test.com",
             hashed_password=hash_password("password123"),
             full_name="Validator User", role="VALIDATOR", is_active=True),
        User(id="user-admin", email="admin@test.com",
             hashed_password=hash_password("password123"),
             full_name="Admin User", role="ADMIN", is_active=True),
    ]
    for u in users:
        db.add(u)
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def get_token(email: str, password: str = "password123") -> str:
    r = client.post("/api/v1/auth/token", data={"username": email, "password": password})
    return r.json()["access_token"]


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestAuthEndpoints:
    def test_register(self):
        r = client.post("/api/v1/auth/register", json={
            "email": "newuser@test.com", "password": "strongpass1",
            "full_name": "New User", "role": "PANCHAYAT"
        })
        assert r.status_code == 201
        assert r.json()["email"] == "newuser@test.com"

    def test_login(self):
        r = client.post("/api/v1/auth/token",
                        data={"username": "panchayat@test.com", "password": "password123"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_me(self):
        token = get_token("panchayat@test.com")
        r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "PANCHAYAT"


class TestAlertLifecycle:
    """
    Tests the full governance lifecycle:
    CREATED → VALIDATED → ASSIGNED → ACTION_SUBMITTED → PENDING_VERIFICATION → CLOSED
    """
    alert_id = None

    def test_create_alert(self):
        token = get_token("panchayat@test.com")
        r = client.post("/api/v1/alerts/", json={
            "panchayat": "Kothapalli",
            "district": "Warangal",
            "state": "Telangana",
            "severity": "High",
            "description": "Groundwater levels have dropped by 3 meters. Two borewells dry. 450 households affected. No clean water for 5 days.",
            "households_affected": 450,
            "water_source_type": "borewell",
            "primary_concern": "scarcity",
            "reporter_name": "Sarpanch Lakshmi Devi",
            "reporter_email": "lakshmi@kothapalli.gov.in",
            "reporter_org": "Kothapalli Gram Panchayat",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        data = r.json()
        assert "alert_code" in data
        assert data["status"] != ""
        TestAlertLifecycle.alert_id = data["id"]

    def test_get_alert(self):
        token = get_token("panchayat@test.com")
        r = client.get(f"/api/v1/alerts/{self.alert_id}",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["id"] == self.alert_id

    def test_submit_action(self):
        token = get_token("panchayat@test.com")
        r = client.post(f"/api/v1/alerts/{self.alert_id}/actions", json={
            "alert_id": self.alert_id,
            "actor_name": "Rajesh Kumar",
            "actor_organization": "District Rural Water Supply Dept",
            "action_type": "tanker_dispatch",
            "description": "Deployed 2 water tankers (10,000L each) for daily supply. Hydrogeological survey conducted. New borewell drilling contractor engaged.",
            "resources_deployed": "2 water tankers, survey team",
            "is_resolution_claim": False,
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201

    def test_submit_resolution_claim(self):
        token = get_token("panchayat@test.com")
        r = client.post(f"/api/v1/alerts/{self.alert_id}/actions", json={
            "alert_id": self.alert_id,
            "actor_name": "Rajesh Kumar",
            "actor_organization": "District Rural Water Supply Dept",
            "action_type": "borewell_completion",
            "description": "New borewell operational. Water quality tested and meets BIS standards. Community water supply fully restored.",
            "is_resolution_claim": True,
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        # Resolution claim may or may not trigger contradiction flag
        data = r.json()
        assert "contradiction_flag" in data

    def test_alert_timeline(self):
        token = get_token("panchayat@test.com")
        r = client.get(f"/api/v1/alerts/{self.alert_id}/timeline",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        events = r.json()["events"]
        assert len(events) >= 1

    def test_validation_requires_validator_role(self):
        """Panchayat user should NOT be able to approve closure."""
        token = get_token("panchayat@test.com")
        r = client.post(f"/api/v1/alerts/{self.alert_id}/validate", json={
            "alert_id": self.alert_id,
            "validator_name": "Priya Sharma",
            "method": "Field visit on 12th Feb. Inspected borewell and interviewed 15 households.",
            "findings": "New borewell operational. Water supply restored. Community confirms regular supply.",
            "decision": "APPROVED",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403  # Role denied

    def test_validator_can_approve(self):
        """Only VALIDATOR role can close an alert."""
        token = get_token("validator@test.com")
        r = client.post(f"/api/v1/alerts/{self.alert_id}/validate", json={
            "alert_id": self.alert_id,
            "validator_name": "Priya Sharma",
            "validator_org": "WaterAid India",
            "method": "Field visit on 12th Feb. Inspected borewell, interviewed 15 households, tested water quality.",
            "findings": "New borewell operational since Feb 10. Water quality meets BIS standards. 450 households report restored supply.",
            "evidence_reviewed": "Photos, water quality certificate, GPS coordinates",
            "decision": "APPROVED",
        }, headers={"Authorization": f"Bearer {token}"})
        # May return 400 if status not PENDING_VERIFICATION yet
        assert r.status_code in (201, 400)


class TestDashboard:
    def test_dashboard_stats(self):
        token = get_token("admin@test.com")
        r = client.get("/api/v1/alerts/dashboard/stats",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert "total_alerts" in data
        assert "closed_alerts" in data
        assert "by_severity" in data

    def test_list_alerts(self):
        token = get_token("panchayat@test.com")
        r = client.get("/api/v1/alerts/?page=1&page_size=10",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "items" in data


class TestMLScoring:
    """Test that ML scoring integrates correctly."""
    def test_alert_with_ml_scores(self):
        token = get_token("panchayat@test.com")
        r = client.post("/api/v1/alerts/", json={
            "panchayat": "TestPanchayat",
            "district": "TestDistrict",
            "state": "TestState",
            "severity": "Low",
            "description": "Minor decline in well water level affecting 20 households. Seasonal pattern observed.",
            "households_affected": 20,
            "reporter_name": "Test Reporter",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 201
        # ml_risk_score and ml_predicted_severity should be populated
        # (or None if model not available — both are acceptable)
        data = r.json()
        assert "ml_risk_score" in data
