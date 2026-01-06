import os 
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
import pandas as pd
from typing import Union

class FileReader:
    """
    Utility class for reading files, especially prompt templates.
    """

    @staticmethod
    def read_text(path: str) -> str:
        """
        Read a UTF-8 text file and return its content.

        Args:
            path: Path to the file.

        Returns:
            The file content as a string.
        """
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def read_csv(path: str, **kwargs) -> pd.DataFrame:
        """
        Read a CSV file into a pandas DataFrame.

        Args:
            path: Path to the CSV file.
            **kwargs: Passed through to pandas.read_csv (e.g., sep, dtype).

        Returns:
            pandas.DataFrame
        """
        # utf-8-sig handles BOM if present; user can override via kwargs
        kwargs.setdefault("encoding", "utf-8-sig")
        return pd.read_csv(path, **kwargs)

    @staticmethod
    def read_xlsx(path: str, sheet_name: Union[str, int] = 0, **kwargs) -> pd.DataFrame:
        """
        Read an Excel (.xlsx) sheet into a pandas DataFrame.

        Args:
            path: Path to the Excel file.
            sheet_name: Sheet name or index; defaults to the first/active sheet.
            **kwargs: Passed through to pandas.read_excel (e.g., dtype).

        Returns:
            pandas.DataFrame
        """
        return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl", **kwargs)
    
    @staticmethod
    def read_json(path: str) -> Union[dict, list]:
        """
        Read a JSON file and return the parsed Python object (dict or list).

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed JSON content as a dict or list.
        """
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)