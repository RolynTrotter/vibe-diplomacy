"""Human seats over HTTP: the same powers a seat has at the CLI."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from vibe import game as gamemod
from vibe import serve
from vibe.game import POWERS, Match


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    monkeypatch.setattr(serve, "start_runner", lambda match: None)
    server = serve.Server(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers["Content-Type"].endswith("json")
                                  else raw.decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    server.shutdown()


def test_a_human_creates_claims_submits_and_readies(api):
    code, m = api("/api/new", {"humans": ["FRANCE"], "model": "hold", "name": "h1",
                               "deadline": 3600})
    assert code == 200 and m["seats"]["FRANCE"]["open"] and m["deadline_at"]
    assert api("/api/matches")[1][0]["name"] == "h1"
    code, claim = api("/api/claim", {"match": "h1", "power": "FRANCE"})
    assert code == 200
    assert api("/api/claim", {"match": "h1", "power": "FRANCE"})[0] == 400   # taken
    assert api("/api/claim", {"match": "h1", "power": "ENGLAND"})[0] == 400  # not human
    tok = claim["token"]

    code, seat = api(f"/api/seat/{tok}")
    assert seat["power"] == "FRANCE" and seat["season"] == "Spring 1901"
    assert "A PAR - BUR" in seat["options"]["PAR"]["orders"]
    assert seat["options"]["PAR"]["unit"] == "A PAR" and seat["submitted"] is None
    assert api(f"/api/seat/{tok}/map.svg")[1].lstrip().startswith("<")

    assert api(f"/api/seat/{tok}/submit", {"orders": ["F BRE - LON"]})[0] == 400
    code, seat = api(f"/api/seat/{tok}/submit", {"orders": ["A PAR - BUR"], "phase": "S1901M"})
    assert seat["submitted"] == ["A PAR - BUR"] and not seat["ready"]

    match = Match.open("h1")
    for p in POWERS:
        if p != "FRANCE":
            match.submit(p, [], ready=True)
    assert match.phase() == "S1901M"                       # waiting on France's Ready
    code, seat = api(f"/api/seat/{tok}/ready", {"ready": True, "phase": "S1901M"})
    assert seat["phase"] == "F1901M" and seat["submitted"] is None and not seat["ready"]
    assert "A BUR" in seat["units"]
    assert api(f"/api/seat/{tok}/ready", {"ready": True, "phase": "S1901M"})[0] == 409


def test_model_seats_are_not_served_and_bad_settings_are_refused(api):
    api("/api/new", {"humans": ["ITALY"], "model": "fake", "name": "h2"})
    tok = Match.open("h2").config["seats"]["AUSTRIA"]
    assert api(f"/api/seat/{tok}")[0] == 400
    assert api("/api/new", {"humans": [], "model": "fake"})[0] == 400
    assert api("/api/new", {"humans": ["ITALY"], "model": "gpt-9"})[0] == 400


def _raw(api_base, path, headers, data=b"{}"):
    req = urllib.request.Request(api_base + path, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    monkeypatch.setattr(serve, "start_runner", lambda match: None)
    server = serve.Server(("127.0.0.1", 0), serve.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_no_cross_site_posts_and_bounded_bodies(base):
    body = json.dumps({"humans": ["FRANCE"], "model": "hold"}).encode()
    js = {"Content-Type": "application/json"}
    assert _raw(base, "/api/new", {**js, "Origin": "https://evil.example"}, body)[0] == 403
    assert _raw(base, "/api/new", {"Content-Type": "text/plain"}, body)[0] == 415
    code, headers = _raw(base, "/api/new", {**js, "Origin": "https://skandha-1.tailafb97d.ts.net"}, body)
    assert code == 200 and headers["Access-Control-Allow-Origin"] == "https://skandha-1.tailafb97d.ts.net"
    assert _raw(base, "/api/new", {**js, "Origin": "https://evil.example"}, body)[1].get(
        "Access-Control-Allow-Origin") is None
    import socket
    host, port = base.split("//")[1].split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s:
        s.sendall(b"POST /api/new HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                  b"Content-Length: -1\r\n\r\n")
        assert b" 400 " in s.recv(200)


def test_model_matches_are_capped(api):
    for i in range(serve.MAX_MODEL_MATCHES):
        assert api("/api/new", {"humans": ["FRANCE"], "model": "claude:haiku", "name": f"q{i}"})[0] == 200
    code, err = api("/api/new", {"humans": ["FRANCE"], "model": "claude:haiku", "name": "over"})
    assert code == 400 and "already" in err["error"]
    assert api("/api/new", {"humans": ["FRANCE"], "model": "fake", "name": "free"})[0] == 200
