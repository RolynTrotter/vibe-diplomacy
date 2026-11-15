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


def test_the_france_austria_map_from_the_page(api):
    code, m = api("/api/new", {"humans": ["FRANCE"], "model": "fake", "name": "fa",
                               "map": "standard_france_austria"})
    assert code == 200 and set(m["seats"]) == {"AUSTRIA", "FRANCE"}
    assert m["map"] == "standard_france_austria"
    assert api("/api/new", {"humans": ["ITALY"], "model": "fake", "name": "fa2",
                            "map": "standard_france_austria"})[0] == 400
    assert api("/api/new", {"humans": ["FRANCE"], "model": "fake", "map": "mars"})[0] == 400
    tok = api("/api/claim", {"match": "fa", "power": "FRANCE"})[1]["token"]
    seat = api(f"/api/seat/{tok}")[1]
    assert "A PAR - BUR" in seat["options"]["PAR"]["orders"] and seat["owing_count"] == 2


def test_serve_waits_for_storage_before_anything(tmp_path, monkeypatch):
    target = tmp_path / "drive" / "games"
    monkeypatch.setattr(gamemod, "GAMES", target)
    monkeypatch.setattr(gamemod, "EXTERNAL", True)
    lines = []
    sleeps = []

    def nap(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            target.mkdir(parents=True)          # an empty mount point: keep waiting
        if len(sleeps) == 3:
            (target / gamemod.STORAGE_MARKER).touch()   # the drive mounts
    monkeypatch.setattr(serve.time, "sleep", nap)
    serve.wait_for_storage(log=lines.append, pause=30)
    assert len(sleeps) == 3 and "waiting for match storage" in lines[0]
    assert lines[-1].startswith(f"match storage: {target}") and "after 90s" in lines[-1]


def test_local_models_are_offered_only_while_the_server_answers(api, monkeypatch):
    from vibe import relay
    monkeypatch.setattr(relay, "config", lambda: None)
    local = api("/api/local")[1]
    assert not local["available"] and local["reason"] == "not set up on this host"
    monkeypatch.setattr(relay, "config", lambda: {"name": "Cutie"})
    monkeypatch.setattr(relay, "models", lambda **k: None)
    local = api("/api/local")[1]
    assert not local["available"] and local["reason"] == "Cutie is not answering"
    assert api("/api/new", {"humans": ["FRANCE"], "model": "local:flint", "name": "l1"})[0] == 400
    monkeypatch.setattr(relay, "models", lambda **k: ["flint"])
    assert api("/api/local")[1] == {"name": "Cutie", "models": ["flint"], "available": True,
                                    "reason": ""}
    assert api("/api/new", {"humans": ["FRANCE"], "model": "local:flint", "name": "l2"})[0] == 200
    assert api("/api/new", {"humans": ["FRANCE"], "model": "local:gpt9", "name": "l3"})[0] == 400


def test_a_local_seat_holds_and_says_so_when_its_server_is_down(tmp_path, monkeypatch):
    from vibe import relay, run
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    monkeypatch.setattr(relay, "models", lambda **k: None)
    m = Match.create("down", max_year=1901)
    seats = {p: run.Seat("fake") for p in m.powers}
    seats["FRANCE"] = run.Seat("openai", "flint", "http://127.0.0.1:9/v1", local="Cutie")
    lines = []
    r = run.Runner(m, seats, seed=1, log=lines.append)
    r.play(max_phases=1)
    assert m.phase() == "F1901M" and m.history("S1901M")["orders"]["FRANCE"] == []
    assert any("Cutie is not answering; holds this phase" in l for l in lines)


def test_a_local_server_that_dies_mid_game_costs_seconds_not_minutes(tmp_path, monkeypatch):
    """The health check said yes; the server is gone by the time the seat calls."""
    import socket as sk
    import time as tm
    from vibe import relay, run
    monkeypatch.setattr(gamemod, "GAMES", tmp_path)
    monkeypatch.setattr(relay, "models", lambda **k: ["flint"])        # stale "up"
    forgot = []
    monkeypatch.setattr(relay, "forget", lambda: forgot.append(1))
    dead = sk.socket(); dead.bind(("127.0.0.1", 0)); port = dead.getsockname()[1]
    dead.close()                                                        # nothing listens
    m = Match.create("mid", max_year=1901)
    seats = {p: run.Seat("fake") for p in m.powers}
    seats["FRANCE"] = run.Seat("openai", "flint", f"http://127.0.0.1:{port}/v1", local="Cutie")
    lines = []
    t = tm.monotonic()
    run.Runner(m, seats, seed=1, log=lines.append).play(max_phases=1)
    assert tm.monotonic() - t < 20 and m.phase() == "F1901M"
    assert m.history("S1901M")["orders"]["FRANCE"] == [] and forgot
    assert any("Cutie stopped answering" in l and "holds" in l for l in lines)


def test_the_relay_is_loopback_only_and_per_process(tmp_path, monkeypatch):
    import json as js
    from vibe import relay
    cfg = tmp_path / "local.json"
    cfg.write_text(js.dumps({"command": ["true"], "listen": "0.0.0.0:12340"}))
    monkeypatch.setenv("VIBE_LOCAL", str(cfg))
    with pytest.raises(ValueError, match="loopback"):
        relay.config()
    cfg.write_text(js.dumps({"command": ["true"], "listen": "127.0.0.1:12340"}))
    url = relay.base_url()
    assert url.startswith("http://127.0.0.1:") and ":12340" not in url
    assert relay.base_url() == url                    # one relay per process
