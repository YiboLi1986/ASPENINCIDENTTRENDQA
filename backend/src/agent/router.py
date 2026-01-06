import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

from backend.src.llm.copilot_client import CopilotClient
from backend.src.data_io.file_reader import FileReader


class IntentRouter:
    """
    Classify user intent and decide whether to call MCP search via Copilot.
    - Loads prompt templates using FileReader.
    - Returns a normalized routing plan for the orchestrator.
    """

    # Class-level defaults
    DEFAULT_PARAMS: Dict[str, Any] = {
        "top_k": 8,
        "alpha": 0.8,
        "beta": 0.25,
        "candidate_pool": 200,
    }

    VALID_INTENTS: Set[str] = {
        "EXPLAIN",
        "HOW_TO_FIX",
        "LOOKUP_REFERENCE",
        "ASK_MORE",
    }

    def __init__(
        self,
        copilot: Optional[CopilotClient] = None,
        prompts_dir: Optional[Path] = None,
        max_tokens: int = 800,
    ) -> None:
        """
        Args:
            copilot: Optional external CopilotClient; if None, a default one is created.
            prompts_dir: Directory containing router.system.txt & router.user.txt.
            max_tokens: Max tokens the router call can generate.
        """
        self.copilot = copilot or CopilotClient(max_tokens=max_tokens)
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).resolve().parents[1] / "prompts"
        self.max_tokens = int(max_tokens)

        self.system_path = self.prompts_dir / "router.system.txt"
        self.user_path = self.prompts_dir / "router.user.txt"

        # Fail fast if prompts are missing
        self.system_prompt = FileReader.read_text(str(self.system_path))
        self.user_template = FileReader.read_text(str(self.user_path))

    # ---------------- Public API ----------------

    def route(self, user_text: str) -> Dict[str, Any]:
        """
        Run routing and return a normalized plan.

        Returns:
            {
              "intent": "HOW_TO_FIX" | "EXPLAIN" | "LOOKUP_REFERENCE" | "ASK_MORE",
              "need_search": bool,
              "search_query": str,
              "mcp_params": {"top_k": int, "alpha": float, "beta": float, "candidate_pool": int},
              "ask": str (only if intent == "ASK_MORE")
            }
        """
        rendered_user = self._render_user(user_text)
        raw = self._infer(rendered_user, json_mode=True)
        plan = self._parse_and_normalize(raw, user_text)
        return plan

    # ---------------- Internal Helpers ----------------

    def _render_user(self, user_text: str) -> str:
        """Fill the user template with the provided user_text."""
        return self.user_template.format(user_text=user_text)

    def _infer(self, rendered_user: str, json_mode: bool = True) -> Dict[str, Any]:
        """
        Call Copilot to infer routing intent.

        Args:
            rendered_user: Already-rendered user prompt.
            json_mode: If True, request JSON-mode from the model.

        Returns:
            Raw JSON response from Copilot.
        """
        payload: Dict[str, Any] = {
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": rendered_user},
            ],
            "max_tokens": self.max_tokens,
            "temperature": 0.0,  # deterministic routing
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self.copilot.chat_raw(**payload)

    def _parse_and_normalize(self, raw: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        """
        Parse model output and apply defaults/validation for downstream stability.
        """
        content = self._safe_get_content(raw)
        plan = self._extract_json(content) or {}

        # Intent
        intent = plan.get("intent")
        if intent not in self.VALID_INTENTS:
            intent = "HOW_TO_FIX"
        plan["intent"] = intent

        # need_search (default true for FIX/REF)
        if "need_search" not in plan:
            plan["need_search"] = intent in ("HOW_TO_FIX", "LOOKUP_REFERENCE")

        # search_query
        sq = plan.get("search_query")
        plan["search_query"] = sq.strip() if isinstance(sq, str) and sq.strip() else user_text

        # mcp_params merge + basic sanity
        params = plan.get("mcp_params") or {}
        merged = dict(self.DEFAULT_PARAMS)
        merged.update({k: v for k, v in params.items() if v is not None})

        # type coercion with guards
        merged["top_k"] = self._as_int(merged.get("top_k"), self.DEFAULT_PARAMS["top_k"])
        merged["candidate_pool"] = self._as_int(merged.get("candidate_pool"), self.DEFAULT_PARAMS["candidate_pool"])
        merged["alpha"] = self._as_float(merged.get("alpha"), self.DEFAULT_PARAMS["alpha"])
        merged["beta"] = self._as_float(merged.get("beta"), self.DEFAULT_PARAMS["beta"])

        # soft guard: candidate_pool >= top_k * 5
        if merged["candidate_pool"] < merged["top_k"] * 5:
            merged["candidate_pool"] = max(merged["top_k"] * 5, 100)

        plan["mcp_params"] = merged

        # ask (only when ASK_MORE)
        if intent == "ASK_MORE":
            ask = plan.get("ask")
            if not isinstance(ask, str) or not ask.strip():
                plan["ask"] = "Could you share the exact error text and product version?"
        else:
            plan.pop("ask", None)

        return plan

    @staticmethod
    def _safe_get_content(raw: Dict[str, Any]) -> str:
        """
        Extract assistant message content safely.
        Falls back to str(raw) if not present.
        """
        try:
            return raw["choices"][0]["message"]["content"]
        except Exception:
            return str(raw)

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Robust JSON extraction from possibly noisy model output.
        Tries direct json.loads, then a greedy {...} regex fallback.
        """
        try:
            return json.loads(text)
        except Exception:
            pass

        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None

    @staticmethod
    def _as_int(v: Any, default: int) -> int:
        """Coerce value to int with default fallback."""
        try:
            return int(v)
        except Exception:
            return default

    @staticmethod
    def _as_float(v: Any, default: float) -> float:
        """Coerce value to float with default fallback."""
        try:
            return float(v)
        except Exception:
            return default

if __name__ == "__main__":
    query = "HYSYS ejector missing from palette"
    router = IntentRouter()
    plan = router.route(query)
    print("[IntentRouter] Routing result:")
    print(json.dumps(plan, ensure_ascii=False, indent=2))