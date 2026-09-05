#!/usr/bin/env python3
"""Get a Strava refresh token for use with strava_sync.py.

Create an app at https://www.strava.com/settings/api first and set its
"Authorization Callback Domain" to `localhost`. Then run:

    python run_page/get_strava_token.py ${client_id} ${client_secret}

The script opens the Strava authorization page, catches the redirect on
http://localhost:8000/exchange_token, and prints the refresh token. Pass
--manual if the local callback server cannot be used (e.g. port blocked);
you will be asked to paste the redirected URL instead.
"""

import argparse
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

REDIRECT_PORT = 8000
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/exchange_token"
# activity:read_all is required to see private activities as well.
SCOPE = "read,activity:read_all,profile:read_all"
AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"


def build_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPE,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        _CallbackHandler.code = query.get("code", [None])[0]
        _CallbackHandler.error = query.get("error", [None])[0]
        granted = query.get("scope", [""])[0]

        if _CallbackHandler.code and "activity:read_all" in granted:
            body = "Authorized. You can close this tab and go back to the terminal."
        elif _CallbackHandler.code:
            body = (
                "Authorized, but 'activity:read_all' was not granted - private "
                "activities will be missing. Re-run and tick every box."
            )
        else:
            body = f"Authorization failed: {_CallbackHandler.error}"

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args) -> None:  # silence the default stderr logging
        pass


def get_code_via_server(client_id: str) -> str:
    url = build_auth_url(client_id, REDIRECT_URI)
    print(f"Opening the Strava authorization page:\n  {url}\n")
    print(
        "Tick every permission box, especially 'View data about your private activities'."
    )
    webbrowser.open(url)

    server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
    print(f"Waiting for the callback on {REDIRECT_URI} ...")
    server.handle_request()
    server.server_close()

    if not _CallbackHandler.code:
        sys.exit(f"No authorization code received: {_CallbackHandler.error}")
    return _CallbackHandler.code


def get_code_manually(client_id: str) -> str:
    url = build_auth_url(client_id, REDIRECT_URI)
    print(f"Open this URL in your browser and authorize:\n  {url}\n")
    print(
        "The browser will land on a localhost page that fails to load - that is fine."
    )
    pasted = input("Paste the full redirected URL (or just the code): ").strip()
    if "code=" in pasted:
        code = parse_qs(urlparse(pasted).query).get("code", [None])[0]
        if not code:
            sys.exit("Could not find a 'code' parameter in that URL.")
        return code
    return pasted


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if response.status_code != 200:
        sys.exit(f"Token exchange failed ({response.status_code}): {response.text}")
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("client_id", help="strava client id")
    parser.add_argument("client_secret", help="strava client secret")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="paste the redirected URL instead of running a local callback server",
    )
    options = parser.parse_args()

    code = (
        get_code_manually(options.client_id)
        if options.manual
        else get_code_via_server(options.client_id)
    )
    payload = exchange_code(options.client_id, options.client_secret, code)

    athlete = payload.get("athlete") or {}
    name = " ".join(filter(None, [athlete.get("firstname"), athlete.get("lastname")]))
    print(f"\nAuthorized as: {name or 'unknown'} (athlete id {athlete.get('id')})")
    print(f"\nSTRAVA_CLIENT_REFRESH_TOKEN={payload['refresh_token']}\n")
    print("Sync with:")
    print(
        f"  python run_page/strava_sync.py {options.client_id} "
        f"{options.client_secret} {payload['refresh_token']} --only-run"
    )


if __name__ == "__main__":
    main()
