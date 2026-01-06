import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import json
import asyncio
from typing import Any, Dict, List, Optional
from contextlib import AsyncExitStack

from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession


def _safe_dump(obj: Any) -> str:
    """Dump any Python object to JSON-ish string safely."""
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        try:
            return json.dumps(str(obj), ensure_ascii=False, indent=2)
        except Exception:
            return repr(obj)


class MCPClient:
    """
    Robust MCP stdio client:
      - launches server via StdioServerParameters (with cwd)
      - unwraps CallToolResult into plain Python data
      - supports persistent and one-shot modes
    """

    DEFAULT_TOP_K: int = 8
    DEFAULT_ALPHA: float = 0.8
    DEFAULT_BETA: float = 0.25
    DEFAULT_CANDIDATE_POOL: int = 200

    def __init__(
        self,
        server_cmd: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        request_timeout_s: int = 90,
        keep_alive: bool = True,
        cwd: Optional[str] = None,
    ) -> None:
        if server_cmd is None:
            raw = os.getenv("MCP_SERVER_CMD", "").strip()
            server_cmd = raw.split() if raw else ["python", "backend/src/server.py"]

        if not server_cmd or not isinstance(server_cmd, list):
            raise ValueError("server_cmd must be like ['python', 'backend/src/server.py']")

        self.server_cmd = list(server_cmd)
        self._env_extra = dict(env or {})
        self.request_timeout_s = int(request_timeout_s)
        self.keep_alive = bool(keep_alive)
        self._cwd = cwd or os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ---------- Context manager ----------

    def __enter__(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._aopen())
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._loop.run_until_complete(self._aclose())
        finally:
            self._loop.close()
            self._loop = None
            self._session = None
            self._exit_stack = None

    # ---------- Public API ----------

    def health(self) -> bool:
        try:
            if self.keep_alive and self._session:
                return self._loop.run_until_complete(self._health())
            else:
                return asyncio.run(self._one_shot(self._health()))
        except Exception:
            return False

    def reload_artifacts(self) -> str:
        coro = self._invoke_tool("reload_artifacts", {})
        if self.keep_alive and self._session:
            return self._loop.run_until_complete(coro)
        else:
            return asyncio.run(self._one_shot(coro))

    def lookup_solution(
        self,
        query: str,
        top_k: Optional[int] = None,
        alpha: Optional[float] = None,
        beta: Optional[float] = None,
        candidate_pool: Optional[int] = None,
        min_desc_len: int = 0,
        same_resolution_dedupe: bool = True,
    ) -> List[Dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("lookup_solution: 'query' must be non-empty")

        t = int(top_k) if top_k is not None else self.DEFAULT_TOP_K
        a = float(alpha) if alpha is not None else self.DEFAULT_ALPHA
        b = float(beta) if beta is not None else self.DEFAULT_BETA
        pool = int(candidate_pool) if candidate_pool is not None else self.DEFAULT_CANDIDATE_POOL
        if pool < t * 5:
            pool = max(t * 5, 100)

        args = {
            "query": query.strip(),
            "top_k": t,
            "alpha": a,
            "beta": b,
            "candidate_pool": pool,
            "min_desc_len": int(min_desc_len),
            "same_resolution_dedupe": bool(same_resolution_dedupe),
        }

        coro = self._invoke_tool("lookup_solution", args)
        if self.keep_alive and self._session:
            return self._loop.run_until_complete(coro)
        else:
            return asyncio.run(self._one_shot(coro))

    def run_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        coro = self._invoke_tool(name, arguments or {})
        if self.keep_alive and self._session:
            return self._loop.run_until_complete(coro)
        else:
            return asyncio.run(self._one_shot(coro))

    # ---------- Async internals ----------

    async def _aopen(self):
        if self._session is not None:
            return

        merged_env = dict(os.environ)
        merged_env.setdefault("FASTMCP_STDERR_LOG", "1")  # server logs to STDERR only
        merged_env.update(self._env_extra)

        command = self.server_cmd[0]
        args = self.server_cmd[1:]

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=merged_env,
            cwd=self._cwd,
        )

        self._exit_stack = AsyncExitStack()
        try:
            stdio, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            self._session = await self._exit_stack.enter_async_context(ClientSession(stdio, write))
            try:
                await self._session.initialize()
            except Exception:
                pass
        except FileNotFoundError as e:
            raise RuntimeError(f"Failed to launch MCP server: {self.server_cmd} (cwd={self._cwd})") from e

    async def _aclose(self):
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None

    async def _one_shot(self, task_coro):
        await self._aopen()
        try:
            return await task_coro
        finally:
            await self._aclose()

    # ---- result coercion ----

    @staticmethod
    def _maybe_call(x):
        try:
            return x() if callable(x) else x
        except Exception:
            return x

    def _coerce_tool_result(self, result: Any) -> Any:
        """
        Normalize SDK CallToolResult into plain Python data.
        Handles shapes where content items expose .json/.data/.value/.text
        possibly as callables.
        """
        try:
            content = getattr(result, "content", None)
            if content is None:
                # Some SDKs already return plain dict/list
                if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
                    return result
                # Try best-effort stringify
                return result

            # 1) Prefer JSON-like payloads
            for item in content:
                # common fields across SDK variants
                candidates = [
                    getattr(item, "json", None),
                    getattr(item, "data", None),
                    getattr(item, "value", None),
                ]
                for c in candidates:
                    c = self._maybe_call(c)
                    # If it's already JSON-serializable types, return directly
                    if isinstance(c, (dict, list, str, int, float, bool)) or c is None:
                        # If str looks like JSON, parse it
                        if isinstance(c, str):
                            t = c.strip()
                            if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
                                try:
                                    return json.loads(t)
                                except Exception:
                                    pass
                        return c

            # 2) Fallback to text
            for item in content:
                t = getattr(item, "text", None)
                t = self._maybe_call(t)
                if isinstance(t, str) and t.strip():
                    s = t.strip()
                    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                        try:
                            return json.loads(s)
                        except Exception:
                            pass
                    return s

            # 3) Last resort: return raw result
            return result
        except Exception:
            return result

    async def _health(self) -> bool:
        ok = False
        try:
            res = await self._invoke_tool("health", {})
            ok = bool(res)
        except Exception:
            tools = await self._list_tools()
            if isinstance(tools, dict) and "tools" in tools:
                tools = tools["tools"]
            ok = any((getattr(t, "name", None) or (isinstance(t, dict) and t.get("name"))) == "health" for t in tools)
        return ok

    async def _list_tools(self) -> List[Dict[str, Any]]:
        sess = await self._ensure_session()
        tools = await sess.list_tools()
        if hasattr(tools, "tools"):
            return [{"name": t.name, "description": getattr(t, "description", "")} for t in tools.tools]
        if isinstance(tools, dict) and "tools" in tools:
            return tools["tools"]
        return tools

    async def _invoke_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        sess = await self._ensure_session()
        raw = await asyncio.wait_for(
            sess.call_tool(name=name, arguments=arguments),
            timeout=self.request_timeout_s,
        )
        return self._coerce_tool_result(raw)

    async def _ensure_session(self) -> ClientSession:
        if self._session is None:
            await self._aopen()
        return self._session


if __name__ == "__main__":
    # One-shot smoke test
    client = MCPClient(keep_alive=False)
    ok = client.health()
    print("[health, one-shot bool] ->", ok)

    try:
        detail = client.run_tool("health", {})
        print("[health detail] ->", _safe_dump(detail))
    except Exception as e:
        print("[health detail] call failed:", repr(e))

    if ok:
        q = "HYSYS ejector missing from palette"
        try:
            hits = client.lookup_solution(q, top_k=5)
            # hits is plain Python now; safe print anyway
            print("[lookup_solution] ->", _safe_dump({
                "query": q,
                "n_hits": len(hits) if isinstance(hits, list) else None,
                "preview": hits[:2] if isinstance(hits, list) else hits
            }))
        except Exception as e:
            print("[lookup_solution] failed:", repr(e))

    # Switch to persistent mode after smoke test if you like:
    # with MCPClient(keep_alive=True) as c:
    #     print("[health] ->", c.health())
    #     print(_safe_dump(c.lookup_solution("some query", top_k=5)))
