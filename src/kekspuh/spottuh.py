from typing import Any

import httpx

from kekspuh.spot_auth import get_valid_access_token

BASE_URL = "https://api.spotify.com/v1"


def create_public_playlist_interactive() -> dict[str, Any]:
    """
    Prompts for playlist name and description via terminal input
    and creates a new empty public playlist on the current user's profile.
    """
    name = input("Enter playlist name: ").strip()
    while not name:
        print("Playlist name cannot be empty.")
        name = input("Enter playlist name: ").strip()

    description = input("Enter playlist description (optional): ").strip()

    token = get_valid_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "name": name,
        "description": description,
        "public": True,
    }

    with httpx.Client(base_url=BASE_URL, headers=headers) as client:
        create_response = client.post("/me/playlists", json=payload)
        create_response.raise_for_status()
        playlist_data = create_response.json()

    print(f"\nPlaylist created successfully: {playlist_data['name']}")
    print(f"URL: {playlist_data['external_urls'].get('spotify')}")
    print(f"ID:  {playlist_data['id']}\n")

    return playlist_data


if __name__ == "__main__":
    create_public_playlist_interactive()
