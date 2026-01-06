import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

import hashlib
import joblib
import pandas as pd
from scipy import sparse
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from backend.src.data_io.file_reader import FileReader
from sklearn.feature_extraction.text import TfidfVectorizer


class IncidentIndexer:
    """
    Read all .xlsx files under backend/src/data/raw,
    extract two columns (Description, Resolution__c),
    and compile them into a normalized CSV file.
    Optionally, build a TF-IDF index for text retrieval.
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        raw_subdir: str = "src/data/raw",
        processed_subdir: str = "src/data/processed",
        index_subdir: str = "src/data/processed/index",
    ) -> None:
        # .../backend/src/rag/indexer.py -> parents[2] == .../backend
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
        self.raw_dir = (self.project_root / raw_subdir).resolve()
        self.processed_dir = (self.project_root / processed_subdir).resolve()
        self.index_dir = (self.project_root / index_subdir).resolve()

        for p in [self.raw_dir, self.processed_dir, self.index_dir]:
            p.mkdir(parents=True, exist_ok=True)

        self.processed_csv = self.processed_dir / "incidents.csv"

    # ------------------------------------------------------------------
    def build_processed_csv(
        self,
        only_files: Optional[List[str]] = None,
        drop_duplicates: bool = True,
    ) -> pd.DataFrame:
        """
        Scan all Excel workbooks and extract Description / Resolution__c.
        Combine and save as incidents.csv.

        Returns:
            Normalized DataFrame with columns:
            id, description, resolution, source_file, row_index
        """
        excel_files = self._collect_excels(only_files)
        frames: List[pd.DataFrame] = []

        for xf in excel_files:
            df = self._read_xlsx(xf)
            if df is None or df.empty:
                continue

            # Clean column names to avoid trailing/leading spaces issues
            df.columns = [str(c).strip() for c in df.columns]

            # Robust column resolution (case-insensitive + contains fallback)
            col_desc = self._resolve_col(df, ["Description", "description", "DESC", "Desc"])
            col_reso = self._resolve_col(df, ["Resolution__c", "resolution", "Resolution", "RESOLUTION"])
            if col_desc is None or col_reso is None:
                continue

            sub = df[[col_desc, col_reso]].copy()
            sub.columns = ["description", "resolution"]

            # Normalize/clean text
            sub["description"] = sub["description"].map(self._clean_text)
            sub["resolution"] = sub["resolution"].map(self._clean_text)

            # Drop invalid/garbage rows (empty, placeholders, too short, low-ascii ratio)
            sub = sub[sub["description"].apply(self._is_valid_text) & sub["resolution"].apply(self._is_valid_text)]
            if sub.empty:
                continue

            # Add metadata
            sub["source_file"] = xf.name
            sub["row_index"] = sub.index.astype(int)
            sub["id"] = sub.apply(lambda r: self._make_id(r["source_file"], int(r["row_index"])), axis=1)

            frames.append(sub[["id", "description", "resolution", "source_file", "row_index"]])

        if not frames:
            out = pd.DataFrame(columns=["id", "description", "resolution", "source_file", "row_index"])
        else:
            out = pd.concat(frames, ignore_index=True)

        if drop_duplicates and not out.empty:
            out = out.drop_duplicates(subset=["description", "resolution"], keep="first").reset_index(drop=True)

        out.to_csv(self.processed_csv, index=False, encoding="utf-8")
        return out

    # ------------------------------------------------------------------
    def build_tfidf_index(
        self,
        df: Optional[pd.DataFrame] = None,
        text_col: str = "description",
        min_df: int = 1,
        max_df: float = 0.9,
        ngram_range: Tuple[int, int] = (1, 2),
    ) -> Dict[str, str]:
        """
        Create baseline TF-IDF index artifacts:
            vectorizer.pkl
            tfidf_csr.npz
            mapping.csv  (row_id ↔ id/source_file)
        """
        if df is None:
            if not self.processed_csv.exists():
                raise FileNotFoundError(f"Processed CSV not found: {self.processed_csv}")
            df = pd.read_csv(self.processed_csv).fillna("")
        if df.empty:
            return {"warning": "processed DataFrame is empty."}

        texts = df[text_col].astype(str).tolist()
        vec = TfidfVectorizer(min_df=min_df, max_df=max_df, ngram_range=ngram_range)
        mat = vec.fit_transform(texts)

        self.index_dir.mkdir(parents=True, exist_ok=True)
        vec_path = self.index_dir / "vectorizer.pkl"
        mat_path = self.index_dir / "tfidf_csr.npz"
        map_path = self.index_dir / "mapping.csv"

        joblib.dump(vec, vec_path)
        sparse.save_npz(mat_path, mat)
        df[["id", "source_file", "row_index"]].to_csv(map_path, index=False, encoding="utf-8")

        return {"vectorizer": str(vec_path), "matrix": str(mat_path), "mapping": str(map_path)}

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def _collect_excels(self, only_files: Optional[List[str]] = None) -> List[Path]:
        if only_files:
            return [self.raw_dir / f for f in only_files if (self.raw_dir / f).exists()]
        return sorted([p for p in self.raw_dir.glob("*.xlsx") if p.is_file()])

    def _read_xlsx(self, path: Path) -> Optional[pd.DataFrame]:
        """Always use FileReader.read_xlsx with openpyxl engine."""
        try:
            return FileReader.read_xlsx(str(path), header=0, dtype=str).fillna("")
        except Exception:
            return None

    @staticmethod
    def _resolve_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """
        Resolve a column by exact (case-insensitive) match first,
        then fallback to contains-based fuzzy matching.
        """
        # exact (case-insensitive)
        cols_lower = {c.lower(): c for c in df.columns}
        for name in candidates:
            key = name.lower()
            if key in cols_lower:
                return cols_lower[key]
        # contains fallback (handle trailing spaces or slight variations)
        for c in df.columns:
            cl = c.strip().lower()
            for cand in candidates:
                if cand.lower() in cl or cl in cand.lower():
                    return c
        return None

    @staticmethod
    def _clean_text(v) -> str:
        """
        Normalize cell text:
          - remove BOM
          - unify line breaks
          - strip spaces
          - drop common Excel placeholders like '_x000D_'
        """
        if pd.isna(v):
            return ""
        s = str(v).replace("\ufeff", "")
        s = s.replace("_x000D_", "\n")  # Excel newline artifact
        s = s.replace("\r", "\n")
        # Collapse multiple blank lines and trim
        s = "\n".join(ln.strip() for ln in s.split("\n") if ln.strip())
        return s.strip()

    @staticmethod
    def _is_valid_text(text: str) -> bool:
        """
        Heuristics to drop garbage/empty rows:
          - must not be empty after cleaning
          - length >= 10
          - ASCII ratio >= 0.6 (tolerate some non-ASCII but avoid gibberish)
          - must contain at least one alphanumeric character
        """
        if not text:
            return False
        t = text.strip()
        if not t:
            return False
        # Remove trivial placeholders again before checks
        t = t.replace("_x000D_", "")
        if len(t) < 10:
            return False
        ascii_ratio = sum(ch.isascii() for ch in t) / max(len(t), 1)
        if ascii_ratio < 0.6:
            return False
        if not any(ch.isalnum() for ch in t):
            return False
        return True

    @staticmethod
    def _make_id(source_file: str, row_index: int) -> str:
        raw = f"{source_file}::{row_index}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    def run(self, only_files: Optional[List[str]] = None, build_index: bool = True) -> Dict[str, str]:
        """One-click pipeline: extract → normalize → save CSV → (optional) build TF-IDF index."""
        df = self.build_processed_csv(only_files=only_files)
        result = {"processed_csv": str(self.processed_csv), "rows": str(len(df))}
        if build_index and not df.empty:
            result.update(self.build_tfidf_index(df))
        return result


if __name__ == "__main__":
    idx = IncidentIndexer()
    info = idx.run()
    print("Index build info:", info)