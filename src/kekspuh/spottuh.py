import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from kekspuh.spot_auth import get_valid_access_token

BASE_URL = "https://api.spotify.com/v1"


@dataclass(frozen=True)
class SpotifyMatch:
    track_uri: str
    track_name: str
    artist_uri: str
    artist_name: str
    album_uri: str
    album_name: str


class SpotifyClient:
    def __init__(self) -> None:
        self.base_url = BASE_URL

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

    def search_track(
        self, track_name: str, artist_name: str | None = None
    ) -> SpotifyMatch | None:
        with httpx.Client(
            base_url=self.base_url, headers=self._get_headers()
        ) as client:
            clean_t = self.clean_query_term(track_name)
            clean_a = self.clean_query_term(artist_name) if artist_name else None

            if clean_a:
                query_p1 = f'track:"{clean_t}" artist:"{clean_a}"'
                result = self._execute_search(client, query_p1)
                if result:
                    return result

                query_p2 = f"{clean_a} {clean_t}"
                result = self._execute_search(client, query_p2)
                if result:
                    return result

                query_p3 = f"{artist_name} {track_name}"
                return self._execute_search(client, query_p3)

            query_p1 = f'track:"{clean_t}"'
            result = self._execute_search(client, query_p1)
            if result:
                return result

            return self._execute_search(client, track_name)

    def _execute_search(self, client: httpx.Client, query: str) -> SpotifyMatch | None:
        resp = self._request_with_retry(
            client,
            "GET",
            "/search",
            params={"q": query, "type": "track", "limit": 5},
        )
        if resp.is_error:
            return None

        data = resp.json()
        items = data.get("tracks", {}).get("items", [])
        if not items:
            return None

        top_track = items[0]
        primary_artist = top_track["artists"][0]
        album = top_track["album"]

        return SpotifyMatch(
            track_uri=top_track["uri"],
            track_name=top_track["name"],
            artist_uri=primary_artist["uri"],
            artist_name=primary_artist["name"],
            album_uri=album["uri"],
            album_name=album["name"],
        )

    def _get_playlist_track_count(self, client: httpx.Client, playlist_id: str) -> int:
        resp = self._request_with_retry(
            client,
            "GET",
            f"/playlists/{playlist_id}",
            params={"fields": "tracks.total"},
        )
        resp.raise_for_status()
        return resp.json().get("tracks", {}).get("total", 0)

    def add_track_to_top(
        self, playlist_id: str, track_uri: str, max_limit: int = 200
    ) -> None:
        headers = self._get_headers()
        with httpx.Client(base_url=self.base_url, headers=headers) as client:
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

            time.sleep(1.0)

    def _trim_playlist_bottom(
        self, client: httpx.Client, playlist_id: str, offset: int, count: int
    ) -> None:
        resp = self._request_with_retry(
            client,
            "GET",
            f"/playlists/{playlist_id}/items",
            params={"offset": offset, "limit": count, "fields": "items(track(uri))"},
        )
        if resp.is_error:
            return

        items = resp.json().get("items", [])
        uris_to_remove = [
            {"uri": item["track"]["uri"]} for item in items if item.get("track")
        ]

        if uris_to_remove:
            self._request_with_retry(
                client,
                "DELETE",
                f"/playlists/{playlist_id}/items",
                json={"tracks": uris_to_remove},
            )
            print(
                f"[Spotify] Trimmed {len(uris_to_remove)} overflow "
                "tracks from bottom of playlist."
            )

    @staticmethod
    def _request_with_retry(
        client: httpx.Client,
        method: str,
        url: str,
        *,
        max_retries: int = 4,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(1, max_retries + 1):
            try:
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
                    raise RuntimeError(
                        f"Spotify extended rate limit active (Retry after: {retry_after}s / ~{hours:.1f}h. "
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
