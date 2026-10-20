from __future__ import annotations

from app.services import url_model


class _FakeModel:
    def predict_proba(self, rows):
        assert len(rows) == 1 and len(rows[0]) == 15
        return [[0.2, 0.8]]


def test_inference_rejects_invalid_url_without_loading_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: (_ for _ in ()).throw(AssertionError()))
    assert url_model.predict_url("javascript:alert(1)", tmp_path / "missing.joblib")["status"] == "invalid_input"


def test_inference_reports_missing_artifact_as_unavailable(tmp_path):
    assert url_model.predict_url("https://example.com", tmp_path / "missing.joblib")["status"] == "unavailable"


def test_inference_uses_training_features_and_marks_score_uncalibrated(tmp_path, monkeypatch):
    artifact = tmp_path / "trusted.joblib"
    artifact.write_bytes(b"placeholder")
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: {
        "model": _FakeModel(), "metadata": {"model_version": "test-v1", "threshold_selected_on_validation": 0.4},
    })
    result = url_model.predict_url("HTTPS://Example.com/a#fragment", artifact)
    assert result["status"] == "scored" and result["score"] == 0.8
    assert result["model_version"] == "test-v1" and result["score_is_calibrated_probability"] is False
