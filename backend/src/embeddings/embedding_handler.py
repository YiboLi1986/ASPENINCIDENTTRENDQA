import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import re
from typing import List, Optional
from langchain_community.embeddings import OllamaEmbeddings

class EmbeddingHandler:
    """
    Lightweight wrapper for vector embedding models served by Ollama.
    Calls the `/api/embeddings` endpoint (local or remote).
    Includes minimal pre-processing and truncation safeguards.
    """

    def __init__(
        self,
        model_name: str = "nomic-embed-text:latest",
        base_url: str = "http://172.22.5.186:32000/ollama-dev",
        max_chars: int = 8000,         # ~2k tokens rough cap
        tail_chars: int = 2000,        # keep some tail when truncating
        normalize_ws: bool = True,
        num_ctx: Optional[int] = None, # forwarded to server options if set
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.max_chars = max_chars
        self.tail_chars = tail_chars
        self.normalize_ws = normalize_ws
        self.num_ctx = num_ctx

        model_kwargs = {}
        if self.num_ctx:
            model_kwargs["options"] = {"num_ctx": self.num_ctx}

        self.model = OllamaEmbeddings(
            model=self.model_name,
            base_url=self.base_url,
            model_kwargs=model_kwargs or None,
        )

    # ----- public -----
    def encode_many(self, texts: List[str]) -> List[List[float]]:
        """Batch encode (best-effort). If server errors, raise to caller."""
        if isinstance(texts, str):
            texts = [texts]
        proc = [self._preprocess(t) for t in texts]
        return self.model.embed_documents(proc)

    def encode_one(self, text: str) -> List[float]:
        """Encode a single text; raise on error."""
        return self.encode_many([text])[0]

    # ----- internals -----
    def _preprocess(self, text: str) -> str:
        if not text:
            return ""
        t = text
        if self.normalize_ws:
            t = re.sub(r"[ \t\r\f\v]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t).strip()
        if len(t) <= self.max_chars:
            return t
        head_keep = max(self.max_chars - self.tail_chars, 0)
        head = t[:head_keep]
        tail = t[-self.tail_chars:] if self.tail_chars > 0 else ""
        return head + "\n...\n" + tail
