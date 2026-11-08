import re
from dataclasses import dataclass

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

    def _get_headers(self) -> dict[str, str]:
        token = get_valid_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def clean_query_term(self, text: str) -> str:
        cleaned = re.sub(r"[\(\[].*?[\)\]]", "", text)
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
            clean_a = self.clean_query_term(artist_name)

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

    def _execute_search(self, client: httpx.Client, query: str) -> SpotifyMatch | None:
        resp = client.get(
            "/search",
            params={
                "q": query,
                "type": "track",
                "limit": 5,
            },
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

    def get_playlist_track_count(self, playlist_id: str) -> int:
        with httpx.Client(
            base_url=self.base_url, headers=self._get_headers()
        ) as client:
            resp = client.get(f"/playlists/{playlist_id}?fields=tracks.total")
            resp.raise_for_status()
            return resp.json().get("tracks", {}).get("total", 0)

    def get_recent_playlist_uris(self, playlist_id: str, limit: int = 10) -> set[str]:
        with httpx.Client(
            base_url=self.base_url, headers=self._get_headers()
        ) as client:
            resp = client.get(
                f"/playlists/{playlist_id}/items",
                params={"limit": limit, "fields": "items(track(uri))"},
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return {
                item["track"]["uri"]
                for item in items
                if item.get("track") and item["track"].get("uri")
            }

    def add_track_to_top(
        self, playlist_id: str, track_uri: str, max_limit: int = 200
    ) -> None:
        headers = self._get_headers()
        with httpx.Client(base_url=self.base_url, headers=headers) as client:
            recent_uris = self.get_recent_playlist_uris(playlist_id, limit=3)
            if track_uri in recent_uris:
                print(
                    f"[Spotify] {track_uri} is already at the top of the playlist. Skipping."
                )
                return

            add_resp = client.post(
                f"/playlists/{playlist_id}/items",
                json={
                    "uris": [track_uri],
                    "position": 0,
                },
            )
            add_resp.raise_for_status()
            print(
                f"[Spotify] Successfully prepended {track_uri} to playlist {playlist_id}"
            )

            total_tracks = self.get_playlist_track_count(playlist_id)
            if total_tracks > max_limit:
                excess_count = total_tracks - max_limit
                self._trim_playlist_bottom(
                    client, playlist_id, offset=max_limit, count=excess_count
                )

    def _trim_playlist_bottom(
        self, client: httpx.Client, playlist_id: str, offset: int, count: int
    ) -> None:
        resp = client.get(
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
            client.request(
                "DELETE",
                f"/playlists/{playlist_id}/items",
                json={"tracks": uris_to_remove},
            )
            print(
                f"[Spotify] Trimmed {len(uris_to_remove)} overflow tracks from bottom of playlist."
            )
