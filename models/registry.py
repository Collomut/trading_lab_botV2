"""Model registry: versioned artifacts, metrics, and production promotion."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from models.model import BaseModel


class ModelRegistry:
    def __init__(self, artifacts_dir: str = "models/artifacts"):
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _version_dir(self, version_id: str) -> Path:
        path = self.artifacts_dir / version_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, model: BaseModel, version_id: str, metrics: dict, *, model_filename: str = "model.joblib") -> str:
        version_dir = self._version_dir(version_id)
        model_path = version_dir / model_filename
        model.save(str(model_path))
        (version_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "version_id": version_id,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                    "metrics": metrics,
                    "feature_names": model.feature_names,
                    "is_calibrated": model.is_calibrated,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(model_path)

    def load(self, version_id: str, *, model_filename: str = "model.joblib") -> BaseModel:
        from models.sklearn_model import SklearnGradientModel

        model = SklearnGradientModel()
        model.load(str(self.artifacts_dir / version_id / model_filename))
        return model

    def list_versions(self) -> list[str]:
        return sorted(p.name for p in self.artifacts_dir.iterdir() if p.is_dir())

    def promote(self, version_id: str, *, model_filename: str = "model.joblib") -> dict:
        pointer = {
            "production_version": version_id,
            "model_filename": model_filename,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }
        (self.artifacts_dir / "production.json").write_text(json.dumps(pointer, indent=2), encoding="utf-8")
        return pointer

    def get_production(self) -> dict | None:
        pointer_path = self.artifacts_dir / "production.json"
        if not pointer_path.exists():
            return None
        return json.loads(pointer_path.read_text(encoding="utf-8"))
