"""Local-only persistence: the saved screen selection, app settings, and
user calibration templates. Everything lives under a per-user Application
Support directory; nothing is ever sent over the network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from meowdoku.models import CalibrationTemplate, SelectionRect

APP_DIR_NAME = "MeowdokuCompanion"


def app_support_dir() -> Path:
    override = os.environ.get("MEOWDOKU_APP_SUPPORT_DIR")
    if override:
        path = Path(override)
    else:
        path = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _settings_path() -> Path:
    return app_support_dir() / "settings.json"


def load_settings() -> dict:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict) -> None:
    path = _settings_path()
    tmp_path = path.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(settings, f, indent=2)
    tmp_path.replace(path)


def save_selection(rect: SelectionRect) -> None:
    settings = load_settings()
    settings["selection"] = rect.to_json()
    save_settings(settings)


def load_selection() -> Optional[SelectionRect]:
    settings = load_settings()
    data = settings.get("selection")
    if not data:
        return None
    try:
        return SelectionRect.from_json(data)
    except (KeyError, TypeError):
        return None


def save_board_size_override(size: Optional[int]) -> None:
    settings = load_settings()
    settings["board_size_override"] = size
    save_settings(settings)


def load_board_size_override() -> Optional[int]:
    return load_settings().get("board_size_override")


def save_respect_x_marks(value: bool) -> None:
    settings = load_settings()
    settings["respect_x_marks"] = bool(value)
    save_settings(settings)


def load_respect_x_marks() -> bool:
    return bool(load_settings().get("respect_x_marks", False))


def save_time_budget_seconds(value: float) -> None:
    settings = load_settings()
    settings["time_budget_seconds"] = float(value)
    save_settings(settings)


def load_time_budget_seconds(default: float = 5.0) -> float:
    return float(load_settings().get("time_budget_seconds", default))


# --- Calibration templates -------------------------------------------------

def _calibration_dir() -> Path:
    d = app_support_dir() / "calibration"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _calibration_index_path() -> Path:
    return _calibration_dir() / "index.json"


def save_calibration_template(template: CalibrationTemplate) -> None:
    d = _calibration_dir()
    index_path = _calibration_index_path()
    index = []
    if index_path.exists():
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            index = []
    filename = f"{template.kind}_{len(index)}.png"
    cv2.imwrite(str(d / filename), template.patch_gray)
    index.append({"kind": template.kind, "filename": filename, "source_cell_px": template.source_cell_px})
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


def load_calibration_templates() -> dict:
    """Returns {"cat": [CalibrationTemplate, ...], "x": [CalibrationTemplate, ...]}."""
    result = {"cat": [], "x": []}
    index_path = _calibration_index_path()
    if not index_path.exists():
        return result
    try:
        with open(index_path, "r") as f:
            index = json.load(f)
    except (json.JSONDecodeError, OSError):
        return result
    d = _calibration_dir()
    for entry in index:
        img_path = d / entry["filename"]
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        tpl = CalibrationTemplate(kind=entry["kind"], patch_gray=img, source_cell_px=entry.get("source_cell_px", img.shape[0]))
        result.setdefault(entry["kind"], []).append(tpl)
    return result


def clear_calibration_templates() -> None:
    d = _calibration_dir()
    index_path = _calibration_index_path()
    if index_path.exists():
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
            for entry in index:
                p = d / entry["filename"]
                if p.exists():
                    p.unlink()
        except (json.JSONDecodeError, OSError):
            pass
        index_path.unlink()


# --- Debug export ------------------------------------------------------------

def export_debug_bundle(directory: str, crop_bgr: np.ndarray, grid_overlay_bgr: Optional[np.ndarray], board_json: dict) -> None:
    """Explicit, user-triggered export of the selected crop, a detected-grid
    overlay image, and the board JSON -- for reproducing a failed
    recognition case. Never written automatically."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    if crop_bgr is not None:
        cv2.imwrite(str(out / "crop.png"), crop_bgr)
    if grid_overlay_bgr is not None:
        cv2.imwrite(str(out / "grid_overlay.png"), grid_overlay_bgr)
    with open(out / "board.json", "w") as f:
        json.dump(board_json, f, indent=2)
