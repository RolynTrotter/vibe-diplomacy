"""Local model seats: a model server this machine reaches only through a command.

Some hosts can't open a plain TCP connection to the machine running the model
(skandha-1's Tailscale runs in userspace, so it reaches Cutie only through
`tailscale nc`). A seat spec `local:<model>` sends its calls to a relay on
127.0.0.1 that pipes each connection through that command.

The host describes the server in a JSON file named by VIBE_LOCAL:

    {"name": "Cutie",                       shown on the page
     "listen": "127.0.0.1",                 loopback only; each process picks a free port
     "command": ["tailscale", "nc", "cutie-1", "1234"],   one per connection
     "key_file": "~/.config/lmstudio/token",              Bearer token, if any
     "concurrency": 1}                      calls at once: one GPU

Without VIBE_LOCAL there are no local seats. The server may be off at any
time: `models()` answers in a few seconds either way, and seats that can't
reach it hold rather than stall the game.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ports: dict[str, int] = {}             # listen host -> this process's relay port
_lock = threading.Lock()
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_cache: dict = {"at": 0.0, "models": None}


def config() -> dict | None:
    path = os.environ.get("VIBE_LOCAL")
    if not path:
        return None
    cfg = json.loads(Path(path).expanduser().read_text())
    cfg.setdefault("name", "Local")
    cfg.setdefault("listen", "127.0.0.1")
    cfg["listen"] = cfg["listen"].rsplit(":", 1)[0] if cfg["listen"].count(":") == 1 \
        else cfg["listen"]                 # an old "host:port" keeps its host
    if cfg["listen"] not in LOOPBACK:
        raise ValueError(f"local relay must listen on loopback, not {cfg['listen']!r}: "
                         "it has no authentication of its own")
    cfg.setdefault("concurrency", 1)
    home = os.path.expanduser("~")
    cfg["command"] = [os.path.expanduser(c).replace("=~/", f"={home}/")   # --socket=~/...
                      for c in cfg["command"]]
    return cfg


def base_url(cfg: dict | None = None) -> str:
    """This process's relay, started if need be."""
    cfg = cfg or config()
    if not cfg:
        return ""
    host = "[::1]" if cfg["listen"] == "::1" else cfg["listen"]
    return f"http://{host}:{ensure(cfg)}/v1"


def api_key(cfg: dict | None = None) -> str:
    cfg = cfg or config()
    f = Path(cfg.get("key_file") or "").expanduser() if cfg else None
    return f.read_text().strip() if f and f.is_file() else ""


def _pipe(client: socket.socket, command: list[str]) -> None:
    """One connection: the client's bytes to the command, its output back.

    The command's stdin is never closed early: closing it can end `nc`
    before the reply arrives. Our clients send a request and read the reply
    without half-closing, so the client's EOF means it is gone: the command
    is then stopped and reaped, as it is when the server's side ends.
    """
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
    except OSError:
        client.close()
        return

    def upstream():
        try:
            while data := client.recv(65536):
                proc.stdin.write(data)
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        proc.kill()                        # the client is gone: so is this request

    threading.Thread(target=upstream, daemon=True).start()
    try:
        while data := proc.stdout.read1(65536):
            client.sendall(data)
    except OSError:
        pass
    finally:
        proc.kill()
        proc.wait()
        client.close()


def ensure(cfg: dict | None = None) -> int:
    """This process's relay port, starting the relay on a free loopback port.

    Every process has its own: nothing else can be listening on it, so the
    token never goes to a stranger who took a fixed port first.
    """
    cfg = cfg or config()
    with _lock:
        if cfg["listen"] in _ports:
            return _ports[cfg["listen"]]
        family = socket.AF_INET6 if cfg["listen"] == "::1" else socket.AF_INET
        srv = socket.socket(family, socket.SOCK_STREAM)
        srv.bind((cfg["listen"], 0))
        srv.listen(16)
        _ports[cfg["listen"]] = srv.getsockname()[1]

    def serve():
        while True:
            client, _ = srv.accept()
            threading.Thread(target=_pipe, args=(client, cfg["command"]), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return _ports[cfg["listen"]]


def forget() -> None:
    """A call to the server just failed: the next check asks it again."""
    _cache.update(at=0.0, models=None)


def models(timeout: float = 8.0, fresh: float = 30.0) -> list[str] | None:
    """The chat models the local server offers now, or None if it isn't answering.

    Cached for `fresh` seconds, so the page can ask often.
    """
    cfg = config()
    if not cfg:
        return None
    if time.time() - _cache["at"] < fresh:
        return _cache["models"]
    found = None
    req = urllib.request.Request(base_url(cfg) + "/models",
                                 headers={"Authorization": f"Bearer {api_key(cfg)}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode()).get("data", [])
        found = [m["id"] for m in data if "embed" not in m.get("id", "")]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        found = None
    _cache.update(at=time.time(), models=found)
    return found
