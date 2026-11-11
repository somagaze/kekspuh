import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

REDIRECT_URI = "http://127.0.0.1:8888/callback"
PORT = 8888

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = PROJECT_ROOT / "_auth" / "spotify_token.json"
TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SCOPE = "playlist-modify-public playlist-modify-private playlist-read-private"

EXPIRY_BUFFER_SECONDS = 60


class AuthState:
    code: str | None = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed_url = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        if "code" in query_params:
            AuthState.code = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"Authentication successful. You may return to the console."
            )
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"Authorization failed. No code parameter detected.")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def _load_token_store() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        return {}
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError, OSError:
        return {}


def _save_token_store(tokens: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    mode = 0o600
    with open(os.open(TOKEN_FILE, flags, mode), "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def _purge_token_store() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def _is_token_expired(tokens: dict[str, Any]) -> bool:
    expires_at = tokens.get("expires_at", 0)
    return time.time() >= (expires_at - EXPIRY_BUFFER_SECONDS)


def _execute_authorization_code_flow() -> dict[str, Any]:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET environment variable."
        )

    AuthState.code = None
    server = HTTPServer(("0.0.0.0", PORT), CallbackHandler)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("\n--- Spotify Authorization Required ---")
    print(f"1. Open this link in your browser:\n{url}")
    print(f"2. Waiting for redirect callback on port {PORT}...\n")

    server.handle_request()
    server.server_close()

    if not AuthState.code:
        raise RuntimeError(
            "Authorization aborted: Failed to capture authorization code."
        )

    payload = {
        "grant_type": "authorization_code",
        "code": AuthState.code,
        "redirect_uri": REDIRECT_URI,
    }

    with httpx.Client() as client:
        response = client.post(
            TOKEN_URL,
            data=payload,
            auth=(CLIENT_ID, CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()

    now = time.time()
    token_record = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in", 3600),
        "expires_at": now + data.get("expires_in", 3600),
    }

    _save_token_store(token_record)
    return token_record


def _refresh_access_token(refresh_token: str) -> dict[str, Any] | None:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET environment variable."
        )

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    with httpx.Client() as client:
        response = client.post(
            TOKEN_URL,
            data=payload,
            auth=(CLIENT_ID, CLIENT_SECRET),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = response.json()

    if response.is_error:
        if data.get("error") == "invalid_grant":
            _purge_token_store()
            return None
        raise RuntimeError(
            f"Token refresh request failed: {data.get('error_description', data.get('error'))}"
        )

    now = time.time()
    tokens = _load_token_store()
    tokens["access_token"] = data["access_token"]
    tokens["expires_in"] = data.get("expires_in", 3600)
    tokens["expires_at"] = now + data.get("expires_in", 3600)

    if "refresh_token" in data:
        tokens["refresh_token"] = data["refresh_token"]

    _save_token_store(tokens)
    return tokens


def get_valid_access_token() -> str:
    tokens = _load_token_store()

    if tokens.get("access_token") and not _is_token_expired(tokens):
        return tokens["access_token"]

    if tokens.get("refresh_token"):
        refreshed_tokens = _refresh_access_token(tokens["refresh_token"])
        if refreshed_tokens and refreshed_tokens.get("access_token"):
            return refreshed_tokens["access_token"]

    new_tokens = _execute_authorization_code_flow()
    print(new_tokens)
    return new_tokens["access_token"]
