import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP, Context

from backend.src.rag.search import IncidentSearcher

# Create FastMCP app
app = FastMCP("aspenIncidentQA")

# Global state for robustness
_SEARCHER: Optional[IncidentSearcher] = None
_LAST_ERROR: Optional[str] = None


def _stderr_log(msg: str) -> None:
    """Log diagnostic messages to STDERR to avoid polluting JSON-RPC over STDOUT."""
    if os.getenv("FASTMCP_STDERR_LOG", "1") != "0":
        print(msg, file=sys.stderr, flush=True)


def build_searcher() -> IncidentSearcher:
    """
    Construct the searcher with environment-driven config.
    Keep this function reasonably light; heavy I/O should live in the searcher.
    """
    embed_base_url = os.getenv("OLLAMA_HOST") or "http://172.22.5.186:32000/ollama-dev"
    embed_model = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")

    # Boot diagnostics to STDERR only (never STDOUT)
    _stderr_log(f"[MCP][build_searcher] OLLAMA_HOST={embed_base_url} EMBED_MODEL={embed_model}")

    return IncidentSearcher(
        alpha=float(os.getenv("SEARCH_ALPHA", "0.8")),
        beta=float(os.getenv("SEARCH_BETA", "0.25")),
        candidate_pool=int(os.getenv("SEARCH_POOL", "200")),
        embed_model_name=embed_model,
        embed_base_url=embed_base_url,
    )


def ensure_searcher() -> IncidentSearcher:
    """
    Lazy-load the global searcher. On failure, cache the error string instead
    of crashing the transport.
    """
    global _SEARCHER, _LAST_ERROR
    if _SEARCHER is None:
        try:
            _SEARCHER = build_searcher()
            _LAST_ERROR = None
        except Exception as e:
            _SEARCHER = None
            _LAST_ERROR = f"{type(e).__name__}: {e}"
            raise
    return _SEARCHER


@app.tool()
def health(ctx: Context) -> Dict:
    """
    Health check that ALWAYS returns a dict; never raise to the transport.
    Includes error details when initialization fails.
    """
    global _SEARCHER, _LAST_ERROR
    detail: Dict[str, object] = {
        "status": "ok",
        "tfidf_ready": False,
        "embedding_ready": False,
        "emb_rows": 0,
        "alpha": None,
        "beta": None,
        "candidate_pool": None,
        "ollama_host": os.getenv("OLLAMA_HOST") or "http://172.22.5.186:32000/ollama-dev",
        "embed_model": os.getenv("EMBED_MODEL", "nomic-embed-text:latest"),
    }

    if _LAST_ERROR is not None:
        detail["status"] = "error"
        detail["error"] = _LAST_ERROR
        return detail

    if _SEARCHER is None:
        try:
            ensure_searcher()
        except Exception as e:
            detail["status"] = "error"
            detail["error"] = f"{type(e).__name__}: {e}"
            return detail

    s = _SEARCHER
    try:
        tfidf_ready = bool(getattr(s, "vec", None) is not None and
                           getattr(s, "mat", None) is not None and
                           getattr(s, "df", None) is not None)
        emb = getattr(s, "doc_emb", None)
        embedding_ready = bool(emb is not None)
        emb_rows = int(emb.shape[0]) if emb is not None and hasattr(emb, "shape") else 0

        detail.update({
            "tfidf_ready": tfidf_ready,
            "embedding_ready": embedding_ready,
            "emb_rows": emb_rows,
            "alpha": getattr(s, "alpha", None),
            "beta": getattr(s, "beta", None),
            "candidate_pool": getattr(s, "candidate_pool", None),
            "ollama_host": getattr(s, "embed_base_url", detail["ollama_host"]),
            "embed_model": getattr(s, "embed_model_name", detail["embed_model"]),
        })
    except Exception as e:
        detail["status"] = "error"
        detail["error"] = f"inspect_failed: {type(e).__name__}: {e}"

    return detail


@app.tool()
def reload_artifacts(ctx: Context) -> str:
    """
    Hot-reload TF-IDF / embedding artifacts. Never crash; return a simple status string.
    """
    global _SEARCHER, _LAST_ERROR
    try:
        _SEARCHER = build_searcher()
        _LAST_ERROR = None
        return "reloaded"
    except Exception as e:
        _SEARCHER = None
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        return f"reload_failed: {_LAST_ERROR}"


@app.tool()
def lookup_solution(
    ctx: Context,
    query: str,
    top_k: int = 8,
    alpha: Optional[float] = None,
    beta: Optional[float] = None,
    candidate_pool: Optional[int] = None,
    min_desc_len: int = 0,
    same_resolution_dedupe: bool = True,
) -> List[Dict]:
    """
    Two-stage retrieval:
      Stage-1: TF-IDF + fuzzy blended score
      Stage-2: Optional embedding re-rank (if embeddings exist)
    Returns a list of results or a single structured error dict in a list.
    """
    try:
        s = ensure_searcher()
    except Exception as e:
        return [{"error": f"searcher_unavailable: {type(e).__name__}: {e}"}]

    if alpha is not None:
        s.alpha = float(alpha)
    if beta is not None:
        s.beta = float(beta)
    if candidate_pool is not None:
        s.candidate_pool = int(candidate_pool)

    try:
        return s.search(
            query=query,
            top_k=top_k,
            min_desc_len=min_desc_len,
            same_resolution_dedupe=same_resolution_dedupe,
        )
    except Exception as e:
        return [{"error": f"search_failed: {type(e).__name__}: {e}"}]


if __name__ == "__main__":
    _stderr_log("[MCP] FastMCP server starting...")
    app.run()
