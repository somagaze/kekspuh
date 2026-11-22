from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import httpx

from kekspuh.spot_auth import get_valid_access_token

BASE_URL = "https://api.spotify.com/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
USAGE_LOG_PATH = PROJECT_ROOT / "data" / "spotify_usage.json"
ROLLING_WINDOW_SECONDS = 86400


@dataclass(frozen=True)
class SpotifyMatch:
    track_uri: str
    track_name: str
    artist_uri: str
    artist_name: str
    album_uri: str
    album_name: str
    match_tier: int


class SpotifyQuotaTracker:
    def __init__(self, log_path: Path = USAGE_LOG_PATH) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_counts: dict[str, int] = {"search": 0, "playlist": 0, "other": 0}

    def _load_events(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        try:
            data = json.loads(self.log_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except json.JSONDecodeError, OSError:
            return []

    def _save_events(self, events: list[dict[str, Any]]) -> None:
        try:
            self.log_path.write_text(json.dumps(events), encoding="utf-8")
        except OSError:
            pass

    def record_call(self, url: str) -> None:
        now = time.time()
        cutoff = now - ROLLING_WINDOW_SECONDS

        if url.startswith("/search"):
            bucket = "search"
        elif url.startswith("/playlists"):
            bucket = "playlist"
        else:
            bucket = "other"

        self.session_counts[bucket] = self.session_counts.get(bucket, 0) + 1

        events = [e for e in self._load_events() if e.get("ts", 0) >= cutoff]
        events.append({"ts": now, "bucket": bucket})
        self._save_events(events)

    def get_24h_summary(self) -> dict[str, int]:
        cutoff = time.time() - ROLLING_WINDOW_SECONDS
        events = [e for e in self._load_events() if e.get("ts", 0) >= cutoff]
        summary = {"search": 0, "playlist": 0, "other": 0}
        for e in events:
            b = e.get("bucket", "other")
            summary[b] = summary.get(b, 0) + 1
        summary["total"] = sum(summary.values())
        return summary


class SpotifyClient:
    def __init__(self) -> None:
        self.base_url = BASE_URL
        self._shared_client: httpx.Client | None = None
        self.quota = SpotifyQuotaTracker()

    def __enter__(self) -> Self:
        self._shared_client = httpx.Client(
            base_url=self.base_url, headers=self._get_headers(), timeout=15.0
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._shared_client is not None:
            self._shared_client.close()
            self._shared_client = None

    def _get_client(self) -> tuple[httpx.Client, bool]:
        if self._shared_client is not None:
            self._shared_client.headers.update(self._get_headers())
            return self._shared_client, False
        return (
            httpx.Client(
                base_url=self.base_url, headers=self._get_headers(), timeout=15.0
            ),
            True,
        )

    def print_quota_summary(self) -> None:
        s = self.quota.session_counts
        d = self.quota.get_24h_summary()
        print(
            f"[Spotify Quota] This run -> Search: {s['search']}, Playlist: {s['playlist']} | "
            f"Rolling 24h -> Search: {d['search']}, Playlist: {d['playlist']}, Total: {d['total']}"
        )

    @staticmethod
    def _get_headers() -> dict[str, str]:
        token = get_valid_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def clean_query_term(text: str) -> str:
        cleaned = re.sub(r"[(\[].*?[)\]]", "", text)
        cleaned = re.sub(
            r"\s*-\s*(remaster(ed)?|live|radio edit|bonus track).*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r'["\']', "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _artist_similarity(
        target_artist: str, spotify_artists: list[dict[str, Any]]
    ) -> float:
        target = target_artist.strip().lower()
        best = 0.0
        for artist in spotify_artists:
            candidate = (artist.get("name") or "").strip().lower()
            if not candidate:
                continue
            if target in candidate or candidate in target:
                best = max(best, 0.95)
            else:
                ratio = SequenceMatcher(None, target, candidate).ratio()
                best = max(best, ratio)
        return best

    def search_track(
        self, track_name: str, artist_name: str | None = None
    ) -> SpotifyMatch | None:
        client, should_close = self._get_client()
        try:
            clean_t = self.clean_query_term(track_name)
            clean_a = self.clean_query_term(artist_name) if artist_name else None

            if clean_a:
                query_p1 = f'track:"{clean_t}" artist:"{clean_a}"'
                result = self._execute_search(
                    client, query_p1, expected_artist=clean_a, match_tier=1
                )
                if result:
                    return result

                query_p2 = f"{clean_a} {clean_t}"
                return self._execute_search(
                    client, query_p2, expected_artist=clean_a, match_tier=2
                )

            query_p1 = f'track:"{clean_t}"'
            result = self._execute_search(client, query_p1, match_tier=1)
            if result:
                return result

            return self._execute_search(client, track_name, match_tier=2)
        finally:
            if should_close:
                client.close()

    def _execute_search(
        self,
        client: httpx.Client,
        query: str,
        expected_artist: str | None = None,
        match_tier: int = 1,
    ) -> SpotifyMatch | None:
        resp = self._request_with_retry(
            client,
            "GET",
            "/search",
            params={"q": query, "type": "track", "limit": 5},
        )
        if resp.is_error:
            return None

        items = resp.json().get("tracks", {}).get("items", [])
        if not items:
            return None

        best_item: dict[str, Any] | None = None
        best_score = -1.0

        for rank_idx, item in enumerate(items):
            artists = item.get("artists") or []
            if not artists:
                continue

            if expected_artist:
                sim = self._artist_similarity(expected_artist, artists)
                if sim < 0.65:
                    continue
            else:
                sim = 1.0

            album_type = (item.get("album") or {}).get("album_type", "")
            type_bonus = 0.15 if album_type in ("album", "single") else 0.0
            rank_bonus = (5 - rank_idx) * 0.02
            score = sim + type_bonus + rank_bonus

            if score > best_score:
                best_score = score
                best_item = item

        if not best_item:
            return None

        primary_artist = best_item["artists"][0]
        album = best_item["album"]

        return SpotifyMatch(
            track_uri=best_item["uri"],
            track_name=best_item["name"],
            artist_uri=primary_artist["uri"],
            artist_name=primary_artist["name"],
            album_uri=album["uri"],
            album_name=album["name"],
            match_tier=match_tier,
        )

    def _get_playlist_track_count(self, client: httpx.Client, playlist_id: str) -> int:
        resp = self._request_with_retry(
            client,
            "GET",
            f"/playlists/{playlist_id}",
            params={"fields": "items.total"},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data.get("items"), dict):
            return data["items"].get("total", 0)
        return data.get("tracks", {}).get("total", 0)

    def add_track_to_top(
        self, playlist_id: str, track_uri: str, max_limit: int = 200
    ) -> None:
        client, should_close = self._get_client()
        try:
            add_resp = self._request_with_retry(
                client,
                "POST",
                f"/playlists/{playlist_id}/items",
                json={"uris": [track_uri], "position": 0},
            )
            add_resp.raise_for_status()
            print(
                f"[Spotify] Successfully prepended {track_uri} "
                f"to playlist {playlist_id}"
            )

            total_tracks = self._get_playlist_track_count(client, playlist_id)
            if total_tracks > max_limit:
                excess_count = total_tracks - max_limit
                self._trim_playlist_bottom(
                    client, playlist_id, offset=max_limit, count=excess_count
                )

            time.sleep(0.5)
        finally:
            if should_close:
                client.close()

    def _trim_playlist_bottom(
        self, client: httpx.Client, playlist_id: str, offset: int, count: int
    ) -> None:
        resp = self._request_with_retry(
            client,
            "GET",
            f"/playlists/{playlist_id}/items",
            params={
                "offset": offset,
                "limit": count,
                "fields": "items(item(uri),track(uri))",
            },
        )
        if resp.is_error:
            print(
                f"[Spotify] Failed to fetch overflow items: {resp.status_code} {resp.text}"
            )
            return

        items = resp.json().get("items", [])
        uris_to_remove: list[dict[str, str]] = []
        for entry in items:
            media = entry.get("item") or entry.get("track")
            if media and media.get("uri"):
                uris_to_remove.append({"uri": media["uri"]})

        if uris_to_remove:
            del_resp = self._request_with_retry(
                client,
                "DELETE",
                f"/playlists/{playlist_id}/items",
                json={"items": uris_to_remove},
            )
            if del_resp.is_error:
                print(
                    f"[Spotify] Failed to delete overflow items: "
                    f"{del_resp.status_code} {del_resp.text}"
                )
                return

            print(
                f"[Spotify] Trimmed {len(uris_to_remove)} overflow "
                "tracks from bottom of playlist."
            )

    def _request_with_retry(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        max_retries: int = 4,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(1, max_retries + 1):
            try:
                self.quota.record_call(url)
                resp = client.request(method, url, **kwargs)
            except httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError:
                if attempt == max_retries:
                    raise
                backoff = 2.0 * attempt
                print(
                    f"[Spotify] Connection hiccup (attempt {attempt}/{max_retries}). "
                    f"Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 5)) + 1
                if retry_after > 120:
                    hours = retry_after / 3600
                    self.print_quota_summary()
                    raise RuntimeError(
                        f"Spotify extended rate limit active (Retry-After: {retry_after}s / ~{hours:.1f}h). "
                        "Aborting instead of sleeping."
                    )
                print(f"[Spotify] Rate limited (429). Sleeping {retry_after}s...")
                time.sleep(retry_after)
                continue

            if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                backoff = 2.0 * attempt
                print(
                    f"[Spotify] Server error {resp.status_code}. "
                    f"Retrying in {backoff}s..."
                )
                time.sleep(backoff)
                continue

            return resp

        raise RuntimeError(f"Spotify request failed after {max_retries} attempts.")
