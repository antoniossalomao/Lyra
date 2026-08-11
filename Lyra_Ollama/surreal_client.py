"""surreal_client.py — single SurrealDB access point for the whole project.

Replaces five identical ad-hoc helpers (_sql_surreal, _sq, _sx, _surreal_query,
_sql) that lived in cerebro_maestro, lyra_agentes, lyra_agent, lyra_tools and
lyra_shadow_thoughts. One class, async + sync variants, shared config.
"""

import json
import uuid
from typing import Any

import httpx
import requests

from config import SURREAL_URL, SURREAL_HEADERS, SURREAL_AUTH, SURREAL_TIMEOUT_S


class SurrealClient:
    """Thin wrapper around SurrealDB's HTTP /sql endpoint.

    Stateless: no connection pool, no persistent socket — httpx/requests
    implicit keep-alive handles the ~1 req/s load adequately.
    # ponytail: no dedicated pool — add one if p95 latency exceeds 50 ms
    """

    def __init__(self, url: str = SURREAL_URL, headers: dict | None = None,
                 auth: tuple[str, str] = SURREAL_AUTH):
        self.url = url
        self.headers = headers or SURREAL_HEADERS
        self.auth = auth

    # ── Async variants ───────────────────────────────────────────────────────

    async def query(self, q: str, timeout: int = SURREAL_TIMEOUT_S) -> list:
        """Execute a SurrealQL statement and return the raw response list.

        Args:
            q:       SurrealQL query string.
            timeout: Request timeout in seconds.

        Returns:
            Raw response list from SurrealDB (one dict per statement, each
            with 'status' and 'result' keys). Use result() to unwrap.

        Raises:
            httpx.HTTPStatusError: on non-2xx responses.
        """
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.url, headers=self.headers,
                                     auth=self.auth, data=q, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    async def query_result(self, q: str, timeout: int = SURREAL_TIMEOUT_S) -> list:
        """Execute a query and return result[0] directly (the common case)."""
        return self.result(await self.query(q, timeout))

    async def execute(self, q: str, timeout: int = SURREAL_TIMEOUT_S) -> None:
        """Fire-and-forget variant — swallows the response, never raises on
        HTTP errors (used for best-effort writes like audit/telemetry)."""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(self.url, headers=self.headers,
                                  auth=self.auth, data=q, timeout=timeout)
        except Exception:
            pass

    # ── Sync variants (for lyra_tools — non-async context) ───────────────────

    def query_sync(self, q: str, timeout: int = 15) -> Any:
        """Synchronous query returning result[0].

        Raises:
            RuntimeError: when SurrealDB reports a statement-level error.
            requests.HTTPError: on non-2xx responses.
        """
        resp = requests.post(self.url, headers=self.headers, auth=self.auth,
                             data=q.encode("utf-8"), timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, list) and body and body[0].get("status") != "OK":
            raise RuntimeError(body[0].get("result", body))
        return body[0]["result"] if isinstance(body, list) and body else body

    # ── Static helpers ───────────────────────────────────────────────────────

    @staticmethod
    def result(data: list, idx: int = 0) -> list:
        """Extract result[idx] from a raw SurrealDB response list."""
        if data and len(data) > idx and isinstance(data[idx], dict):
            return data[idx].get("result") or []
        return []

    @staticmethod
    def safe_id() -> str:
        """Generate a URL-safe unique ID (20-char hex) for SurrealDB records."""
        return uuid.uuid4().hex[:20]

    @staticmethod
    def format_set(fields: dict) -> str:
        """Format a dict as a SurrealQL SET assignment list: k = v, ...
        Values are JSON-encoded, which makes user-controlled strings safe."""
        return ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False)}"
                         for k, v in fields.items())


# Module-level singleton — every consumer shares this default instance.
surreal = SurrealClient()
