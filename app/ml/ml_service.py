# app/ml/ml_service.py
"""
ML Service — integrates pure_path water_governance_model.pkl
and the NLI contradiction detection model (Ushahidi-inspired).

Models:
  - water_governance_model.pkl: predicts risk score and severity
  - NLI (bart-large-mnli): detects contradictions in evidence claims
"""
import joblib
import numpy as np
from typing import Optional, Tuple
from pathlib import Path
import structlog

logger = structlog.get_logger()


# ─── Water Risk Scorer ────────────────────────────────────────────────────────

class WaterRiskScorer:
    """
    Wraps the pre-trained water_governance_model.pkl from pure_path.
    Predicts risk score and severity classification.
    """
    SEVERITY_MAP = {0: "Low", 1: "Medium", 2: "High", 3: "Critical"}

    def __init__(self, model_path: str):
        self.model = None
        self.model_path = model_path
        self._load()

    def _load(self):
        path = Path(self.model_path)
        if path.exists():
            try:
                self.model = joblib.load(path)
                logger.info("water_governance_model loaded", path=str(path))
            except Exception as e:
                logger.warning("Failed to load ML model", error=str(e))
        else:
            logger.warning("ML model not found at path", path=str(path))

    def predict(
        self,
        households_affected: int,
        severity_input: str,
        district: str = "",
        description_len: int = 0,
    ) -> Tuple[float, str, float]:
        """
        Returns (risk_score, predicted_severity, confidence).
        Falls back to rule-based scoring if model unavailable.
        """
        if self.model is None:
            return self._rule_based(households_affected, severity_input)

        severity_num = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}.get(severity_input, 1)

        try:
            features = np.array([[
                households_affected,
                severity_num,
                description_len,
                len(district)
            ]])
            prediction = self.model.predict(features)[0]
            proba = self.model.predict_proba(features)[0]
            confidence = float(max(proba))
            predicted_severity = self.SEVERITY_MAP.get(int(prediction), "Medium")
            risk_score = float(severity_num / 3.0 * 0.4 + (households_affected / 1000.0) * 0.6)
            risk_score = min(1.0, risk_score)
            return risk_score, predicted_severity, confidence
        except Exception as e:
            logger.warning("ML prediction failed, using rule-based", error=str(e))
            return self._rule_based(households_affected, severity_input)

    def _rule_based(self, households: int, severity: str) -> Tuple[float, str, float]:
        severity_score = {"Low": 0.2, "Medium": 0.5, "High": 0.75, "Critical": 1.0}.get(severity, 0.5)
        households_score = min(1.0, households / 500.0)
        risk_score = severity_score * 0.6 + households_score * 0.4
        predicted = severity if severity else ("High" if risk_score > 0.6 else "Medium")
        return round(risk_score, 3), predicted, 0.7


# ─── NLI Contradiction Detector (Ushahidi-inspired) ──────────────────────────

class ContradictionDetector:
    """
    Uses facebook/bart-large-mnli to detect contradictions between:
    - Original alert description
    - Submitted resolution claims
    
    Flags cases where resolution claims contradict field evidence,
    matching Ushahidi's 'disputed report' workflow.
    """

    def __init__(self, model_name: str = "facebook/bart-large-mnli"):
        self.model_name = model_name
        self.pipeline = None
        self._load()

    def _load(self):
        try:
            from transformers import pipeline
            self.pipeline = pipeline(
                "zero-shot-classification",
                model=self.model_name,
                device=-1  # CPU; change to 0 for GPU
            )
            logger.info("NLI contradiction detector loaded", model=self.model_name)
        except Exception as e:
            logger.warning("NLI model not loaded (optional)", error=str(e))

    def detect(self, premise: str, hypothesis: str) -> Tuple[float, bool, str]:
        """
        Args:
            premise: Original alert description / field report
            hypothesis: Resolution claim submitted by actioner

        Returns:
            (contradiction_score, is_contradicted, reason)
        """
        if self.pipeline is None:
            return 0.0, False, "NLI model not available"

        try:
            labels = ["resolved", "contradicts original report", "partially addressed"]
            result = self.pipeline(
                hypothesis,
                candidate_labels=labels,
                hypothesis_template=f"Given that '{premise[:200]}', this claim {{}}."
            )

            contradiction_score = 0.0
            for label, score in zip(result["labels"], result["scores"]):
                if label == "contradicts original report":
                    contradiction_score = score
                    break

            is_contradicted = contradiction_score > 0.5
            reason = ""
            if is_contradicted:
                reason = (
                    f"Resolution claim appears to contradict the original alert description "
                    f"(contradiction confidence: {contradiction_score:.1%}). "
                    "Independent verification strongly recommended."
                )

            return round(contradiction_score, 3), is_contradicted, reason

        except Exception as e:
            logger.warning("Contradiction detection failed", error=str(e))
            return 0.0, False, ""


# ─── Singleton instances ──────────────────────────────────────────────────────

_risk_scorer: Optional[WaterRiskScorer] = None
_contradiction_detector: Optional[ContradictionDetector] = None


def get_risk_scorer(model_path: str = "./pure_path/water_governance_model.pkl") -> WaterRiskScorer:
    global _risk_scorer
    if _risk_scorer is None:
        _risk_scorer = WaterRiskScorer(model_path)
    return _risk_scorer


def get_contradiction_detector() -> ContradictionDetector:
    global _contradiction_detector
    if _contradiction_detector is None:
        _contradiction_detector = ContradictionDetector()
    return _contradiction_detector
