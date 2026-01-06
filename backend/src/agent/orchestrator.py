import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from typing import Any, Dict, List, Optional

from backend.src.agent.router import IntentRouter
from backend.src.agent.mcp_client import MCPClient
from backend.src.agent.synthesizer import Synthesizer


class AgentOrchestrator:
    """
    Orchestrates the full flow: route → (optional MCP search, one-shot) → synthesize.
    - Distills retrieved hits to the exact fields LLM needs (description + resolution + minimal meta).
    - Robustly normalizes MCP results into list[dict] regardless of SDK content wrapper shapes.
    """

    # Top-k evidence fed to LLM (post-search)
    DISTILL_MAX_K: int = 12
    # Safety caps to control token usage
    MAX_DESC_CHARS: int = 1200
    MAX_RESOLUTION_CHARS: int = 1600
    MAX_SNIPPET_CHARS: int = 600

    def __init__(
        self,
        router: Optional[IntentRouter] = None,
        synthesizer: Optional[Synthesizer] = None,
        keep_alive_mcp: bool = False,  # one-shot by default to avoid cancel-scope issues
    ) -> None:
        self.router = router or IntentRouter()
        self.synth = synthesizer or Synthesizer()
        # kept for compatibility, but we force one-shot below
        self.keep_alive_mcp = bool(keep_alive_mcp)

    # ---------------- Public API ----------------

    def handle(self, text: str) -> Dict[str, Any]:
        """
        Execute router → (optional MCP one-shot) → synthesizer.
        Returns:
            {
              "reply": str,
              "used_tool": bool,
              "n_hits": int,
              "plan": dict,
              "hits": list,            # normalized raw hits (list[dict])
              "evidence": list,        # distilled top-k for LLM (desc+resolution+meta)
              "meta": {"avg_top3_score_final": float?}
            }
        """
        plan = self.router.route(text)

        raw_hits: Any = []
        meta: Dict[str, Any] = {}

        # Optional MCP search (ONE-SHOT: keep_alive=False)
        if plan.get("need_search"):
            p = plan.get("mcp_params", {}) or {}
            mcp = MCPClient(keep_alive=False)
            raw_hits = mcp.lookup_solution(
                query=plan.get("search_query") or text,
                top_k=p.get("top_k"),
                alpha=p.get("alpha"),
                beta=p.get("beta"),
                candidate_pool=p.get("candidate_pool"),
            )

        # Normalize hits into list[dict] regardless of SDK return shapes
        hits: List[Dict[str, Any]] = self._normalize_hits(raw_hits)

        # Compute avg of top-3 score_final if present
        if hits:
            vals = [self._as_float(h.get("score_final"), 0.0) for h in hits[:3]]
            if any(v > 0 for v in vals):
                meta["avg_top3_score_final"] = round(sum(vals) / len(vals), 4)

        # Distill hits → evidence (only fields Synthesizer truly needs)
        evidence = self._distill_hits(hits, k=self.DISTILL_MAX_K)

        # Feed distilled evidence to Synthesizer
        reply = self.synth.synthesize(text, evidence if evidence else [])

        return {
            "reply": reply,
            "used_tool": bool(hits),
            "n_hits": len(hits),
            "plan": plan,
            "hits": hits,          # normalized raw hits for UI/debug
            "evidence": evidence,  # compact evidence fed to LLM
            "meta": meta,
        }

    # ---------------- Normalization helpers ----------------

    @staticmethod
    def _normalize_hits(hits: Any) -> List[Dict[str, Any]]:
        """
        Coerce various SDK return shapes into list[dict].
        Supports:
          - {"type":"json","json":[ ... ]} or {"json":[ ... ]}
          - {"type":"text","text":"[ ... ]"} (JSON string)
          - a plain dict (single hit) or list[dict]
          - otherwise returns []
        """
        # Already list -> keep only dict items
        if isinstance(hits, list):
            return [h for h in hits if isinstance(h, dict)]

        # Plain dict could be: a single hit, or a content wrapper with "json"/"data"/"value"/"text"
        if isinstance(hits, dict):
            # Prefer explicit JSON-like payloads
            for key in ("json", "data", "value"):
                if key in hits and isinstance(hits[key], (list, dict)):
                    val = hits[key]
                    if isinstance(val, list):
                        return [h for h in val if isinstance(h, dict)]
                    if isinstance(val, dict):
                        return [val]

            # Text content that actually contains JSON
            t = hits.get("text")
            if hits.get("type") == "text" and isinstance(t, str):
                s = t.strip()
                if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                    try:
                        parsed = json.loads(s)
                        if isinstance(parsed, list):
                            return [h for h in parsed if isinstance(h, dict)]
                        if isinstance(parsed, dict):
                            return [parsed]
                    except Exception:
                        return []

            # Treat as single hit dict
            return [hits]

        # Unknown shapes -> empty
        return []

    # ---------------- Distillation & utilities ----------------

    def _distill_hits(self, hits: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
        """
        Keep only top-k and normalize common field names:
          - description: description | desc | problem | issue | summary | symptom
          - resolution:  resolution | solution | fix | resolution_text | steps
          - snippet:     snippet | context
        Also keep id/title/source_file/meta and scores.
        """
        if not hits:
            return []

        distilled: List[Dict[str, Any]] = []
        for h in hits[: max(1, int(k))]:
            desc = self._first_nonempty(
                h, ("description", "desc", "problem", "issue", "summary", "symptom")
            )
            reso = self._first_nonempty(
                h, ("resolution", "solution", "fix", "resolution_text", "steps")
            )
            snip = self._first_nonempty(h, ("snippet", "context"))

            # support your stage-1 score name (score_tfidf_fuzzy)
            score_stage1 = (
                self._as_float(h.get("score_tfidf_fuzzy"), None) or
                self._as_float(h.get("score_tfidf"), None)
            )

            item = {
                "id": h.get("id") or h.get("incident_id") or h.get("uid"),
                "title": h.get("title") or h.get("headline"),
                "source_file": h.get("source_file") or h.get("source") or h.get("file"),

                # Core fields for LLM
                "description": self._clip(desc, self.MAX_DESC_CHARS),
                "resolution": self._clip(reso, self.MAX_RESOLUTION_CHARS),

                # Optional helpful context
                "snippet": self._clip(snip, self.MAX_SNIPPET_CHARS),
                "version": self._infer_version(h),

                # Scores (for meta/traceability)
                "score_final": self._as_float(h.get("score_final"), None),
                "score_stage1": score_stage1,

                "extra": h.get("extra"),
            }
            distilled.append(item)

        return distilled

    @staticmethod
    def _infer_version(h: Dict[str, Any]) -> Optional[str]:
        extra = h.get("extra")
        if isinstance(extra, dict):
            v = extra.get("version") or extra.get("product_version")
            if isinstance(v, str) and v.strip():
                return v.strip()
        v2 = h.get("version") or h.get("product_version")
        if isinstance(v2, str) and v2.strip():
            return v2.strip()
        return None

    @staticmethod
    def _first_nonempty(h: Dict[str, Any], keys: tuple) -> Optional[str]:
        for k in keys:
            v = h.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return None

    @staticmethod
    def _clip(s: Optional[str], limit: int) -> Optional[str]:
        if not isinstance(s, str):
            return None
        s = s.strip()
        if len(s) <= limit:
            return s
        return s[: max(1, limit - 3)].rstrip() + "..."

    @staticmethod
    def _as_float(v: Any, default: Optional[float]) -> Optional[float]:
        try:
            return float(v) if v is not None else default
        except Exception:
            return default


if __name__ == "__main__":
    orch = AgentOrchestrator()
    q = "HYSYS ejector missing from palette"
    out = orch.handle(q)
    print(json.dumps(out, ensure_ascii=False, indent=2))
