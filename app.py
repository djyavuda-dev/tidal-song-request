"""
Tidal Song Request Kiosk
-------------------------
Same idea as the Spotify version: guests scan a QR code, search, and request
a song. It lands only in TARGET_PLAYLIST_ID. Guests never log in to Tidal and
never see your other playlists.

How the two Tidal tokens work here:
  - Search uses a "client credentials" token (app-only, no user involved).
  - Adding to the playlist uses YOUR token (authorization code + PKCE),
    obtained once via /login. The refresh token it returns is stored in the
    TIDAL_REFRESH_TOKEN env var so it survives restarts on a free host.

One-time setup (you, the DJ):
  1. developer.tidal.com/dashboard -> your app -> add the redirect URI
     <your-domain>/callback (must match exactly).
  2. Put client ID / secret etc. in env vars (see .env.example).
  3. Deploy, visit /login once, approve with YOUR Tidal account.
  4. Copy the TIDAL_REFRESH_TOKEN shown on the /callback page into your host's
     environment variables.
"""

import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from collections import deque
from html import escape

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request

load_dotenv()

CLIENT_ID = os.environ["TIDAL_CLIENT_ID"]
CLIENT_SECRET = os.environ["TIDAL_CLIENT_SECRET"]
REDIRECT_URI = os.environ["TIDAL_REDIRECT_URI"]
TARGET_PLAYLIST_ID = os.environ["TARGET_PLAYLIST_ID"]  # the ONLY playlist this app can touch
COUNTRY_CODE = os.environ.get("COUNTRY_CODE", "US")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

API = "https://openapi.tidal.com/v2"
AUTH_URL = "https://login.tidal.com/authorize"
TOKEN_URL = "https://auth.tidal.com/v1/oauth2/token"
SCOPE = "playlists.read playlists.write"
JSON_API = "application/vnd.api+json"

app = Flask(__name__)

_state = {}  # in-memory: "app" token, "user" token, pending PKCE verifier

REQUEST_COOLDOWN_SECONDS = 45
RECENT_TRACK_WINDOW_SECONDS = 60 * 20
_last_request_by_ip = {}
_recently_added_tracks = deque()
_request_log = deque(maxlen=200)


# ---------- tokens ----------

def _token_request(data):
    resp = requests.post(TOKEN_URL, data=data, auth=(CLIENT_ID, CLIENT_SECRET), timeout=15)
    if not resp.ok:
        app.logger.error("Tidal token error %s: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
    return resp.json()


def get_app_token():
    tok = _state.get("app")
    if tok and tok["expires_at"] - 30 > time.time():
        return tok["access_token"]
    data = _token_request({"grant_type": "client_credentials"})
    _state["app"] = {
        "access_token": data["access_token"],
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
    }
    return _state["app"]["access_token"]


def get_user_token():
    tok = _state.get("user")
    if tok and tok["expires_at"] - 30 > time.time():
        return tok["access_token"]
    refresh = (tok or {}).get("refresh_token") or os.environ.get("TIDAL_REFRESH_TOKEN")
    if not refresh:
        raise RuntimeError("No DJ token available — visit /login once first.")
    data = _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLIENT_ID}
    )
    _state["user"] = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", refresh),
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
    }
    return _state["user"]["access_token"]


def is_recently_added(track_id):
    now = time.time()
    while _recently_added_tracks and now - _recently_added_tracks[0][1] > RECENT_TRACK_WINDOW_SECONDS:
        _recently_added_tracks.popleft()
    return any(tid == track_id for tid, _ in _recently_added_tracks)


# ---------- DJ-only one-time setup ----------

@app.route("/login")
def login():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _state["pkce_verifier"] = verifier
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return redirect(AUTH_URL + "?" + urllib.parse.urlencode(params))


@app.route("/callback")
def callback():
    code = request.args.get("code")
    verifier = _state.get("pkce_verifier")
    if not code or not verifier:
        return f"Giriş tamamlanamadı: {escape(str(dict(request.args)))}. /login'den tekrar dene.", 400
    data = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }
    )
    _state["user"] = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + int(data.get("expires_in", 3600)),
    }
    return (
        "<p>Tidal bağlantısı kuruldu.</p>"
        "<p>Hosting panelinden şu ortam değişkenini ekle, sonra bu sayfayı kapat:</p>"
        f"<p><b>TIDAL_REFRESH_TOKEN</b> = <code>{escape(data.get('refresh_token', '(boş geldi)'))}</code></p>"
    )


# ---------- search parsing ----------

def parse_search(payload):
    """Turn Tidal's JSON:API search response into a flat list of tracks."""
    included = {(i.get("type"), i.get("id")): i for i in payload.get("included", [])}
    # Since mid-2026 Tidal returns "data" as a list of search-result resources;
    # older responses had a single object. Handle both.
    data = payload.get("data") or {}
    if isinstance(data, list):
        data = data[0] if data else {}
    rels = data.get("relationships", {})
    out = []
    for ref in (rels.get("tracks", {}).get("data") or [])[:8]:
        track = included.get((ref["type"], ref["id"]))
        if not track:
            continue
        attrs = track.get("attributes", {})
        title = attrs.get("title", "")
        if attrs.get("version"):
            title += f" ({attrs['version']})"

        trels = track.get("relationships", {})
        artist_names = []
        for a in trels.get("artists", {}).get("data") or []:
            art = included.get((a["type"], a["id"]))
            if art:
                artist_names.append(art.get("attributes", {}).get("name", ""))

        cover = None
        for al in (trels.get("albums", {}).get("data") or [])[:1]:
            album = included.get((al["type"], al["id"]))
            for c in ((album or {}).get("relationships", {}).get("coverArt", {}).get("data") or [])[:1]:
                artwork = included.get((c["type"], c["id"]))
                files = (artwork or {}).get("attributes", {}).get("files") or []
                files = sorted(files, key=lambda f: (f.get("meta") or {}).get("width", 0))
                big_enough = [f for f in files if (f.get("meta") or {}).get("width", 0) >= 80]
                pick = (big_enough or files or [None])[0]
                cover = pick.get("href") if pick else None

        out.append({
            "id": track["id"],
            "name": title,
            "artist": ", ".join(n for n in artist_names if n),
            "album_art": cover,
        })
    return out


# ---------- guest-facing ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    try:
        resp = requests.get(
            f"{API}/searchResults",
            params={
                "filter[query]": query,
                "countryCode": COUNTRY_CODE,
                "include": "tracks,tracks.artists,tracks.albums,tracks.albums.coverArt",
            },
            headers={"Authorization": f"Bearer {get_app_token()}", "Accept": JSON_API},
            timeout=15,
        )
        if not resp.ok:
            app.logger.error("Tidal search error %s: %s", resp.status_code, resp.text[:300])
            return jsonify([]), 502
        return jsonify(parse_search(resp.json()))
    except Exception:
        app.logger.exception("search failed")
        return jsonify([]), 502


@app.route("/api/request", methods=["POST"])
def request_song():
    ip = request.remote_addr
    now = time.time()

    last = _last_request_by_ip.get(ip, 0)
    if now - last < REQUEST_COOLDOWN_SECONDS:
        wait = int(REQUEST_COOLDOWN_SECONDS - (now - last))
        return jsonify({"ok": False, "error": f"Az önce istek gönderdin, {wait} saniye bekle."}), 429

    data = request.get_json(force=True)
    track_id = str(data.get("id", "")).strip()
    track_name = str(data.get("name", ""))[:120]
    track_artist = str(data.get("artist", ""))[:120]
    requester_name = (data.get("requester_name") or "").strip()[:40]

    if not track_id.isdigit():
        return jsonify({"ok": False, "error": "Geçersiz şarkı."}), 400
    if not requester_name:
        return jsonify({"ok": False, "error": "Adını yazmayı unuttun."}), 400
    if is_recently_added(track_id):
        return jsonify({"ok": False, "error": "Bu şarkı zaten listede — başka bir şey dene."}), 409

    try:
        # The ONLY write this app performs, and only into TARGET_PLAYLIST_ID.
        resp = requests.post(
            f"{API}/playlists/{TARGET_PLAYLIST_ID}/relationships/items",
            params={"countryCode": COUNTRY_CODE},
            json={"data": [{"id": track_id, "type": "tracks"}]},
            headers={
                "Authorization": f"Bearer {get_user_token()}",
                "Content-Type": JSON_API,
                "Accept": JSON_API,
            },
            timeout=15,
        )
    except Exception:
        app.logger.exception("add failed")
        return jsonify({"ok": False, "error": "Bağlantı sorunu, tekrar dene."}), 502

    if not resp.ok:
        app.logger.error("Tidal add error %s: %s", resp.status_code, resp.text[:300])
        return jsonify({"ok": False, "error": "Şarkı eklenemedi, birazdan tekrar dene."}), 502

    _last_request_by_ip[ip] = now
    _recently_added_tracks.append((track_id, now))
    _request_log.appendleft({
        "name": track_name,
        "artist": track_artist,
        "requester": requester_name,
        "time": time.strftime("%H:%M:%S", time.localtime(now)),
    })
    return jsonify({"ok": True})


# ---------- DJ-only: who requested what ----------

@app.route("/admin")
def admin():
    if ADMIN_KEY and request.args.get("key") != ADMIN_KEY:
        return "Yetkisiz.", 403
    rows = "".join(
        f"<tr><td>{escape(r['time'])}</td><td>{escape(r['requester'])}</td>"
        f"<td>{escape(r['name'])} — {escape(r['artist'])}</td></tr>"
        for r in _request_log
    )
    return f"""
    <html><head><meta http-equiv="refresh" content="15">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body {{ font-family: sans-serif; background:#15181B; color:#EDE9E0; padding:16px; }}
      table {{ width:100%; border-collapse: collapse; }}
      td {{ padding:8px 6px; border-bottom:1px solid #333; font-size:0.9rem; }}
      h1 {{ font-size:1.2rem; }}
    </style></head>
    <body><h1>İstekler ({len(_request_log)})</h1>
    <table>{rows}</table></body></html>
    """


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8888, debug=True)
