from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

BASE_V2_URL = "https://api.kexp.org/v2"


class KexpClient:
    def __init__(self, base_url: str = BASE_V2_URL, timeout: float = 15.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def paginate_endpoint(
        self,
        endpoint_name: str,
        limit: int = 100,
        max_pages: int = 1,
        params: dict[str, Any] | None = None,
    ) -> Iterator[list[dict[str, Any]]]:

        query_params: dict[str, Any] = {"limit": limit}
        if params:
            query_params.update(params)

        url: str | None = f"{self.base_url}/{endpoint_name}/"

        pages_fetched = 0

        with httpx.Client(timeout=self.timeout) as client:
            while url and pages_fetched < max_pages:
                current_params = query_params if pages_fetched == 0 else None
                resp = client.get(url, params=current_params)
                resp.raise_for_status()
                data = resp.json()
                results: list[dict[str, Any]] = data.get("results") or []
                if results:
                    yield results

                url = data.get("next")
                pages_fetched += 1
                time.sleep(0.3)
