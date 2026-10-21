from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

import pytest

from scripts.staging import validate_url_model as staging
from app.core import config
from app.services import url_model
from app.services import tools as tool_service


def test_staging_artifact_missing_is_clear(tmp_path):
    with pytest.raises(staging.StartupValidationError, match="missing"):
        staging.validate_artifact(tmp_path / "missing.joblib", "0" * 64)


def test_staging_checksum_mismatch_fails_before_loading(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: pytest.fail("must not load mismatched artifact"))
    with pytest.raises(staging.StartupValidationError, match="SHA-256 mismatch"):
        staging.validate_artifact(path, staging.EXPECTED_ARTIFACT_SHA256)


def test_staging_model_load_failure_has_actionable_diagnostic(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    monkeypatch.setattr(staging.importlib.metadata, "version", lambda name: staging.EXPECTED_VERSIONS[name])
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: (_ for _ in ()).throw(ValueError("bad pickle")))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_ARTIFACT_SHA256", digest)
    with pytest.raises(staging.StartupValidationError, match="could not be loaded"):
        staging.validate_artifact(path, digest)


def test_staging_metadata_compatibility_is_checked(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    monkeypatch.setattr(staging.importlib.metadata, "version", lambda name: staging.EXPECTED_VERSIONS[name])
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: {
        "model": object(), "metadata": {"model_version": "wrong", "feature_schema": "wrong"}
    })
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_ARTIFACT_SHA256", digest)
    with pytest.raises(staging.StartupValidationError, match="metadata"):
        staging.validate_artifact(path, digest)


def test_staging_accepts_only_expected_artifact_metadata(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    monkeypatch.setattr(staging.importlib.metadata, "version", lambda name: staging.EXPECTED_VERSIONS[name])
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: {
        "model": object(), "metadata": {
            "model_version": staging.EXPECTED_MODEL_VERSION,
            "feature_schema": staging.EXPECTED_FEATURE_SCHEMA,
            "threshold_selection": {"selected_threshold": staging.EXPECTED_THRESHOLD},
        }
    })
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_ARTIFACT_SHA256", digest)
    metadata = staging.validate_artifact(path, digest)
    assert metadata["model_version"] == staging.EXPECTED_MODEL_VERSION


def test_missing_dependency_is_clear(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    def missing(name):
        if name == "numpy":
            raise staging.importlib.metadata.PackageNotFoundError(name)
        return staging.EXPECTED_VERSIONS[name]
    monkeypatch.setattr(staging.importlib.metadata, "version", missing)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_ARTIFACT_SHA256", digest)
    with pytest.raises(staging.StartupValidationError, match="Missing ML dependency 'numpy'"):
        staging.validate_artifact(path, digest)


def test_incompatible_dependency_version_is_clear(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    path.write_bytes(b"controlled-test-artifact")
    monkeypatch.setattr(staging.importlib.metadata, "version", lambda name: "0.0.0")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_ARTIFACT_SHA256", digest)
    with pytest.raises(staging.StartupValidationError, match="Incompatible URL-model dependencies"):
        staging.validate_artifact(path, digest)


def test_startup_rejects_user_supplied_artifact_path(monkeypatch, tmp_path):
    monkeypatch.setenv("URL_MODEL_SHADOW_ENABLED", "true")
    monkeypatch.setenv("URL_FETCH_ENABLED", "false")
    monkeypatch.setenv("RUN_MIGRATIONS", "false")
    monkeypatch.setenv("URL_MODEL_ARTIFACT_PATH", str(tmp_path / "user.joblib"))
    monkeypatch.setattr(staging, "validate_artifact", lambda *_: pytest.fail("untrusted path must not load"))
    with pytest.raises(staging.StartupValidationError, match="deployer-controlled path"):
        staging.main()


def test_predictor_inference_failure_returns_error(tmp_path, monkeypatch):
    artifact = tmp_path / "trusted.joblib"
    artifact.write_bytes(b"test")
    monkeypatch.setattr(url_model, "_load_artifact", lambda *_: {
        "model": SimpleNamespace(predict_proba=lambda _rows: (_ for _ in ()).throw(RuntimeError("inference"))),
        "metadata": {"feature_schema": url_model.CHAR_TFIDF_FEATURE_VERSION},
    })
    assert url_model.predict_url("https://example.test/path", artifact)["status"] == "error"


class _MemoryDb:
    def add(self, row):
        row.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        row.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    def commit(self):
        pass


def test_shadow_toggle_does_not_change_existing_analysis_fields(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())
    monkeypatch.setattr(tool_service, "load_official_context", lambda *_: tool_service.OfficialContext([], [], []))
    monkeypatch.setattr(tool_service, "analyze_url", lambda *_: ("https://example.test/", []))
    settings = SimpleNamespace(url_model_shadow_enabled=False, url_model_artifact_path="/controlled/model.joblib",
                               phishtank_app_key="")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(url_model, "predict_url", lambda *_: {
        "status": "scored", "model_version": "test-only", "score": 0.91,
    })

    payload = {"url": "https://example.test/"}
    disabled = tool_service.run_url_analysis(_MemoryDb(), user, payload)
    settings.url_model_shadow_enabled = True
    enabled = tool_service.run_url_analysis(_MemoryDb(), user, payload)
    assert enabled.input_summary.pop("url_model_shadow")["score"] == 0.91
    assert disabled.input_summary == enabled.input_summary == payload
    for name in ("id", "organization_id", "created_by_id", "tool", "subject", "findings",
                 "risk_score", "severity", "confidence", "methodology_version", "created_at"):
        assert getattr(disabled, name) == getattr(enabled, name), name
