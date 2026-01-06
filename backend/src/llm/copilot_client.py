import os
import sys 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import time
import requests
from typing import Dict, List, Optional, Any
from backend.src.llm.config_loader import load_github_models_config


class CopilotClient:
    """
    Minimal client for GitHub Models /inference/chat/completions.
    - Keeps a thin HTTP wrapper so you can later swap to an SDK if needed.
    - Provides simple prompt templating and message composition helpers.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.2,
        top_p: float = 1.0,
        max_tokens: int = 2048,
        request_timeout: int = 120,
        retries: int = 3,
        backoff: float = 1.6,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """
        Args:
            model: Model id, e.g. "openai/gpt-4.1". Defaults to config file value.
            temperature: Sampling temperature.
            top_p: Nucleus sampling.
            max_tokens: Max tokens to generate per call.
            request_timeout: HTTP timeout in seconds.
            retries: Automatic retries for 429/5xx.
            backoff: Exponential backoff factor (seconds^attempt).
            api_key, base_url: Optional overrides; otherwise loaded from config.
        """
        cfg = load_github_models_config()
        self.api_key = api_key or cfg["api_key"]
        self.base_url = (base_url or cfg["base_url"]).rstrip("/")
        self.model = model or cfg["model"]

        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.max_tokens = int(max_tokens)
        self.request_timeout = int(request_timeout)
        self.retries = int(retries)
        self.backoff = float(backoff)

        self.session = requests.Session()
        self._common_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }

    # ---------- Prompt helpers ----------

    @staticmethod
    def build_user_prompt(template: str, **kwargs: Any) -> str:
        """
        Render a user prompt from a Python .format template.

        Example:
            template = "Analyze this code:\n```\n{code_snippet}\n```"
            user = CopilotClient.build_user_prompt(template, code_snippet=snippet)
        """
        return template.format(**kwargs)

    @staticmethod
    def compose_messages(system_prompt: str, user_prompt: str, extra: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        """
        Build an OpenAI-style messages list with optional extra messages.
        """
        msgs: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        if extra:
            msgs.extend(extra)
        return msgs

    # ---------- Core calls ----------

    def chat_raw(
        self,
        messages: List[Dict[str, str]],
        **overrides: Any,
    ) -> Dict[str, Any]:
        """
        Call /inference/chat/completions and return the raw JSON payload.

        Args:
            messages: OpenAI-style messages list.
            **overrides: Optional payload overrides, e.g. {"max_tokens": 4096}.

        Returns:
            Dict[str, Any]: Raw response JSON from the API.
        """
        url = f"{self.base_url}/inference/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,  # non-stream for simplicity
        }
        payload.update(overrides or {})

        attempt = 0
        while True:
            attempt += 1
            resp = self.session.post(url, headers=self._common_headers, json=payload, timeout=self.request_timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt <= self.retries:
                time.sleep(self.backoff ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        extra_messages: Optional[List[Dict[str, str]]] = None,
        **overrides: Any,
    ) -> str:
        """
        High-level convenience: compose messages and return assistant text only.

        Args:
            system_prompt: System instruction.
            user_prompt: User content (already rendered).
            extra_messages: Optional additional messages.
            **overrides: Optional payload overrides (e.g., temperature, max_tokens).

        Returns:
            Assistant reply text.
        """
        messages = self.compose_messages(system_prompt, user_prompt, extra_messages)
        data = self.chat_raw(messages, **overrides)
        # Robust extraction
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            return str(data)

    # ---------- Utilities ----------

    def list_models(self) -> Any:
        """GET /catalog/models to verify connectivity and see available models."""
        url = f"{self.base_url}/catalog/models"
        r = self.session.get(url, headers={k: v for k, v in self._common_headers.items() if k != "Content-Type"}, timeout=60)
        r.raise_for_status()
        return r.json()
