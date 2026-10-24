from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import spambase_model


class FakeModel:
    def predict_proba(self, rows):
        assert len(rows) == 1 and len(rows[0]) == 57
        return [[0.25, 0.75]]


def test_rejects_wrong_width_and_non_finite_input(tmp_path):
    artifact = tmp_path / "missing.joblib"
    assert spambase_model.predict_spambase([0.0] * 56, artifact)["status"] == "invalid_input"
    assert spambase_model.predict_spambase([float("nan")] + [0.0] * 56, artifact)["status"] == "error"


def test_scores_only_engineered_vectors(tmp_path, monkeypatch):
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"trusted")
    monkeypatch.setattr(spambase_model, "_load", lambda *_: {
        "model": FakeModel(), "metadata": {"model_version": "test", "threshold_selection": {"selected_threshold": 0.5}}
    })
    result = spambase_model.predict_spambase([0.0] * 57, artifact)
    assert result["status"] == "scored"
    assert result["prediction"] == "spam"
    assert result["target"] == "unsolicited_commercial_spam"
    assert result["score_is_calibrated_probability"] is False
