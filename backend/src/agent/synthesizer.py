import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.src.llm.copilot_client import CopilotClient
from backend.src.data_io.file_reader import FileReader


class Synthesizer:
    """
    Convert retrieved incidents (hits/evidence) into an actionable, structured answer.
    - Loads prompts via FileReader.
    - Uses low temperature for stability.
    - Prompt enforces: rely ONLY on provided incidents.
    """

    def __init__(
        self,
        copilot: Optional[CopilotClient] = None,
        prompts_dir: Optional[Path] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        """
        Args:
            copilot: Optional external CopilotClient instance.
            prompts_dir: Directory containing synth.system.txt & synth.user.txt.
            max_tokens: Max tokens allowed per synthesis call.
            temperature: Low temperature for deterministic outputs.
        """
        self.copilot = copilot or CopilotClient(max_tokens=max_tokens, temperature=temperature)
        self.prompts_dir = Path(prompts_dir) if prompts_dir else Path(__file__).resolve().parents[1] / "prompts"
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)

        self.system_path = self.prompts_dir / "synth.system.txt"
        self.user_path = self.prompts_dir / "synth.user.txt"

        self.system_prompt = FileReader.read_text(str(self.system_path))
        self.user_template = FileReader.read_text(str(self.user_path))

    # ---------------- Public API ----------------

    def synthesize(self, user_text: str, incidents: List[Dict[str, Any]]) -> str:
        """
        Produce a structured, step-by-step resolution using ONLY the given incidents.

        Args:
            user_text: Original user query / message.
            incidents: Retrieved incidents (distilled evidence or raw hits).

        Returns:
            String answer formatted per synth.system.txt structure.
        """
        rendered_user = self._render_user(user_text, incidents)
        reply = self.copilot.chat_text(
            system_prompt=self.system_prompt,
            user_prompt=rendered_user,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return reply

    # ---------------- Internal ----------------

    def _render_user(self, user_text: str, incidents: List[Dict[str, Any]]) -> str:
        """
        Prepare user prompt with compact JSON evidence.
        """
        compact = json.dumps(incidents, ensure_ascii=False)
        return self.user_template.format(user_text=user_text, retrieved_json=compact)


if __name__ == "__main__":
    user_text = "HYSYS ejector missing from palette"
    fake_incidents = [
        {
            "id": "INC-123",
            "description": "Ejector not visible due to palette filter state.",
            "resolution": "Reset Palette Filter (View > Palette Filter > Reset) and restart HYSYS.",
            "source_file": "incidents/2024/Q3/hysys_ui.csv",
            "score_final": 0.71,
            "score_tfidf_fuzzy": 0.74,
        }
    ]
    synth = Synthesizer()
    print(synth.synthesize(user_text, fake_incidents))
