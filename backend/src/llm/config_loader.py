import os
import sys 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from pathlib import Path
from typing import Dict, Optional

_DEFAULTS = {
    "base_url": "https://models.github.ai",
    "model": "openai/gpt-4.1",
}

def _read_json(path: Path) -> Optional[Dict]:
    """Read a JSON file if it exists; return None on any error."""
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return None
    return None

def load_github_models_config() -> Dict[str, str]:
    """
    Load GitHub Models config with the following precedence:
      1) Environment variables (GITHUB_PAT, GITHUB_MODELS_BASE_URL, GITHUB_MODELS_MODEL)
      2) Fixed local JSON file at repo root: config/github_models.local.json
      3) Hard-coded defaults for base_url/model

    Returns:
      Dict with keys: api_key, base_url, model

    Raises:
      RuntimeError if api_key is missing in both env and config file.
    """
    # --- 1) Environment variables first ---
    api_key = os.getenv("GITHUB_PAT") or os.getenv("GH_MODELS_PAT")
    base_url = os.getenv("GITHUB_MODELS_BASE_URL")
    model = os.getenv("GITHUB_MODELS_MODEL")

    # --- 2) Fallback to <repo>/config/github_models.local.json ---
    if not (api_key and base_url and model):
        # This file sits at: <repo>/backend/src/llm/config_loader.py
        repo_root = Path(__file__).resolve().parents[3]
        cfg_path = repo_root / "backend/src/config/github_models.local.json"

        data = _read_json(cfg_path)
        if data:
            gm = data.get("github_models", {}) if isinstance(data, dict) else {}
            api_key = api_key or gm.get("api_key") or data.get("api_key")
            base_url = base_url or gm.get("base_url") or data.get("base_url")
            model = model or gm.get("model") or data.get("model")

    # --- 3) Defaults for base_url/model ---
    base_url = (base_url or _DEFAULTS["base_url"]).rstrip("/")
    model = model or _DEFAULTS["model"]

    if not api_key:
        raise RuntimeError(
            "Missing API key. Set env GITHUB_PAT (or create config/github_models.local.json with github_models.api_key)."
        )

    return {"api_key": api_key, "base_url": base_url, "model": model}
