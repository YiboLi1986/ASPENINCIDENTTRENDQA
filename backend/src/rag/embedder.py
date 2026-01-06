import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from pathlib import Path
from typing import List, Dict, Optional
import numpy as np
import pandas as pd

from backend.src.data_io.file_reader import FileReader
from backend.src.data_io.file_writer import FileWriter
from backend.src.embeddings.embedding_handler import EmbeddingHandler

class IncidentEmbedder:
    """
    Build and query an embedding index over incidents.csv using the 'description' column.
    Backend: Ollama `/api/embeddings` via EmbeddingHandler (e.g., `nomic-embed-text:latest`).

    Offline artifacts:
      - embeddings.npy        : (M, D) embedding matrix (M ≤ total rows if some are skipped)
      - kept_indices.npy      : (M,) row indices in the original CSV that were embedded
      - embedder_meta.json    : metadata including rows_total/rows_kept/rows_skipped/limit, etc.

    Online:
      - Semantic search over all valid rows or a Stage-1 subset via `restrict_indices`.
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        processed_subdir: str = "src/data/processed",
        index_subdir: str = "src/data/processed/embeddings",
        model_name: str = "nomic-embed-text:latest",
        normalize: bool = True,
        embed_base_url: Optional[str] = None,
        max_input_chars: int = 8000,
        tail_keep_chars: int = 2000,
        num_ctx: Optional[int] = None,
    ) -> None:
        # Paths
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.proc_dir = (self.project_root / processed_subdir).resolve()
        self.index_dir = (self.project_root / index_subdir).resolve()

        self.incidents_csv = self.proc_dir / "incidents.csv"
        self.emb_path = self.index_dir / "embeddings.npy"
        self.kept_idx_path = self.index_dir / "kept_indices.npy"
        self.meta_path = self.index_dir / "embedder_meta.json"
        self.skipped_csv = self.index_dir / "skipped_rows.csv"  # optional audit log

        # Config
        self.model_name = model_name
        self.normalize = normalize
        self.embed_base_url = embed_base_url or os.getenv("OLLAMA_HOST") or "http://172.22.5.186:32000/ollama-dev"
        self.max_input_chars = max_input_chars
        self.tail_keep_chars = tail_keep_chars
        self.num_ctx = num_ctx or (int(os.getenv("EMBED_NUM_CTX")) if os.getenv("EMBED_NUM_CTX") else None)

        # Runtime
        self.df: Optional[pd.DataFrame] = None
        self.emb: Optional[np.ndarray] = None              # (M, D)
        self.kept_indices: Optional[np.ndarray] = None     # (M,)
        self.model: Optional[EmbeddingHandler] = None

        self._load_df()
        self._init_model()

    # ---------------- public APIs ----------------
    def build_embeddings(
        self,
        limit: Optional[int] = None,
        batch_size: int = 64,
        start_offset: int = 0,
        shuffle: bool = False,
        write_skipped_csv: bool = True,
    ) -> Dict[str, str]:
        """
        Encode descriptions with batching and optional early stop.

        Args:
            limit: if set (e.g., 300), only process the first `limit` rows (after offset/shuffle).
            batch_size: number of rows per embedding request; larger batches reduce HTTP overhead.
            start_offset: skip the first `start_offset` rows before processing.
            shuffle: if True, shuffle candidate indices before truncation (limit).
            write_skipped_csv: if True, write a small CSV of skipped rows for auditing.

        Returns:
            Dict of artifact paths.
        """
        # Select candidate indices
        n_total = len(self.df)
        all_idx = list(range(n_total))

        # Optional shuffle before slicing
        if shuffle:
            rng = np.random.default_rng(42)
            rng.shuffle(all_idx)

        # Apply offset and limit
        start = max(0, int(start_offset))
        cand_idx = all_idx[start:]
        if limit is not None:
            cand_idx = cand_idx[: int(limit)]

        # Prepare texts
        texts = self.df.iloc[cand_idx]["description"].astype(str).tolist()

        kept_vecs: List[List[float]] = []
        kept_idx: List[int] = []
        skipped: List[int] = []
        skipped_reasons: List[str] = []

        # Batch encode with fallback on failure
        for b in range(0, len(texts), batch_size):
            chunk = texts[b:b + batch_size]
            chunk_idx = cand_idx[b:b + batch_size]
            try:
                vecs = self.model.encode_many(chunk)  # fast path
                for j, v in enumerate(vecs):
                    kept_vecs.append(v)
                    kept_idx.append(chunk_idx[j])
            except Exception as e:
                # Fallback: try per-item; on failure, skip the row
                for j, t in enumerate(chunk):
                    try:
                        v = self.model.encode_one(t)
                        kept_vecs.append(v)
                        kept_idx.append(chunk_idx[j])
                    except Exception as ee:
                        skipped.append(chunk_idx[j])
                        skipped_reasons.append(str(ee)[:200])

        if not kept_vecs:
            raise RuntimeError("No embeddings were created. All rows failed or were skipped.")

        vecs = np.asarray(kept_vecs, dtype=np.float32)
        if self.normalize:
            vecs = self._l2_normalize(vecs)

        # Persist artifacts
        self.index_dir.mkdir(parents=True, exist_ok=True)
        np.save(self.emb_path, vecs)
        np.save(self.kept_idx_path, np.asarray(kept_idx, dtype=np.int64))
        self.emb = vecs
        self.kept_indices = np.asarray(kept_idx, dtype=np.int64)

        # Optional audit file for skipped rows
        if write_skipped_csv and skipped:
            rows = []
            for i, reason in zip(skipped, skipped_reasons or ["error"] * len(skipped)):
                row = self.df.iloc[i]
                rows.append({
                    "row_index": i,
                    "id": row.get("id", ""),
                    "source_file": row.get("source_file", ""),
                    "desc_head": str(row.get("description", ""))[:200],
                    "reason": reason,
                })
            audit_df = pd.DataFrame(rows)
            FileWriter.write_csv(audit_df, str(self.skipped_csv))

        meta = {
            "backend": "ollama",
            "model": self.model_name,
            "base_url": self.embed_base_url,
            "normalize": self.normalize,
            "rows_total": n_total,
            "rows_candidate": len(cand_idx),
            "rows_kept": int(vecs.shape[0]),
            "rows_skipped": len(skipped),
            "dim": int(vecs.shape[1]),
            "faiss": False,
            "max_input_chars": self.max_input_chars,
            "tail_keep_chars": self.tail_keep_chars,
            "num_ctx": self.num_ctx or "default",
            "start_offset": start,
            "limit": int(limit) if limit is not None else "all",
            "batch_size": int(batch_size),
            "shuffle": bool(shuffle),
            "note": "embeddings.npy aligns with kept_indices.npy, not the raw CSV row order.",
        }
        FileWriter.write_json(meta, str(self.meta_path), ensure_ascii=False, pretty=True)

        return {
            "embeddings": str(self.emb_path),
            "kept_indices": str(self.kept_idx_path),
            "meta": str(self.meta_path),
            "skipped": str(self.skipped_csv) if skipped else "",
        }

    def load_embeddings(self) -> None:
        """Load embeddings.npy and kept_indices.npy if present."""
        if self.emb_path.exists():
            self.emb = np.load(self.emb_path).astype(np.float32)
        if self.kept_idx_path.exists():
            self.kept_indices = np.load(self.kept_idx_path).astype(np.int64)

    def search(
        self,
        query: str,
        top_k: int = 20,
        restrict_indices: Optional[List[int]] = None,  # indices in original CSV coordinate space
    ) -> List[Dict]:
        if not query:
            return []

        if self.emb is None or self.kept_indices is None:
            self.load_embeddings()
        if self.emb is None or self.kept_indices is None:
            raise RuntimeError("Embeddings not built/loaded. Run build_embeddings() first.")

        # Encode query
        q_vec = np.asarray(self.model.encode_one(query), dtype=np.float32)
        if self.normalize:
            q_vec = self._l2_normalize(q_vec.reshape(1, -1)).reshape(-1)

        # Candidate set
        if restrict_indices:
            pos_map = {orig_idx: pos for pos, orig_idx in enumerate(self.kept_indices.tolist())}
            candidate_pos = [pos_map[i] for i in restrict_indices if i in pos_map]
            if not candidate_pos:
                return []
            sub = self.emb[candidate_pos]
            sims = sub @ q_vec
            k = min(top_k, sims.shape[0])
            top_idx = np.argpartition(-sims, k - 1)[:k]
            order = top_idx[np.argsort(-sims[top_idx])]
            chosen_pos = [candidate_pos[i] for i in order]
            scores = sims[order].astype(float).tolist()
        else:
            sims = self.emb @ q_vec
            k = min(top_k, sims.shape[0])
            top_idx = np.argpartition(-sims, k - 1)[:k]
            order = top_idx[np.argsort(-sims[top_idx])]
            chosen_pos = order.tolist()
            scores = sims[order].astype(float).tolist()

        chosen_csv_idx = [int(self.kept_indices[pos]) for pos in chosen_pos]

        out = []
        for csv_i, sc in zip(chosen_csv_idx, scores):
            row = self.df.iloc[csv_i]
            out.append({
                "row_index": csv_i,
                "id": row.get("id", ""),
                "description": row.get("description", ""),
                "resolution": row.get("resolution", ""),
                "source_file": row.get("source_file", ""),
                "score_embed": round(float(sc), 4),
            })
        return out

    # ---------------- internals ----------------
    def _load_df(self) -> None:
        if not self.incidents_csv.exists():
            raise FileNotFoundError(f"incidents.csv not found: {self.incidents_csv}")
        df = FileReader.read_csv(str(self.incidents_csv)).fillna("")
        if "description" not in df.columns:
            raise ValueError("Missing required column 'description' in incidents.csv")
        self.df = df

    def _init_model(self) -> None:
        self.model = EmbeddingHandler(
            model_name=self.model_name,
            base_url=self.embed_base_url,
            max_chars=self.max_input_chars,
            tail_chars=self.tail_keep_chars,
            num_ctx=self.num_ctx,
        )

    @staticmethod
    def _l2_normalize(x: np.ndarray) -> np.ndarray:
        if x.ndim == 1:
            denom = max(np.linalg.norm(x), 1e-12)
            return (x / denom).astype(np.float32)
        denom = np.clip(np.linalg.norm(x, axis=1, keepdims=True), 1e-12, None)
        return (x / denom).astype(np.float32)

if __name__ == "__main__":
    emb = IncidentEmbedder()

    # Direct local control – easiest for testing
    LIMIT = 300        # only embed first 300 rows
    BATCH_SIZE = 64    # batch size for embedding requests
    OFFSET = 0         # skip first rows
    SHUFFLE = False    # keep order for reproducibility

    if not emb.emb_path.exists() or LIMIT is not None:
        print("Building embeddings (Ollama nomic-embed-text) ...")
        print(emb.build_embeddings(
            limit=LIMIT,
            batch_size=BATCH_SIZE,
            start_offset=OFFSET,
            shuffle=SHUFFLE,
        ))
    else:
        print("Loading embeddings...")
        emb.load_embeddings()

    while True:
        q = input("\nQuery (blank to exit): ").strip()
        if not q:
            break
        results = emb.search(q, top_k=10)
        for i, r in enumerate(results, 1):
            print(f"\n[{i}] score_embed={r['score_embed']} file={r['source_file']}")
            print("D:", r["description"][:200])
            print("R:", r["resolution"][:200])