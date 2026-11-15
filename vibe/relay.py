"""Local model seats: a model server this machine reaches only through a command.

Some hosts can't open a plain TCP connection to the machine running the model
(skandha-1's Tailscale runs in userspace, so it reaches Cutie only through
`tailscale nc`). A seat spec `local:<model>` sends its calls to a relay on
127.0.0.1 that pipes each connection through that command.

The host describes the server in a JSON file named by VIBE_LOCAL:

    {"name": "Cutie",                       shown on the page
     "listen": "127.0.0.1:12340",           where the relay listens
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

_started: set[str] = set()
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "models": None}


def config() -> dict | None:
    path = os.environ.get("VIBE_LOCAL")
    if not path:
        return None
    cfg = json.loads(Path(path).expanduser().read_text())
    cfg.setdefault("name", "Local")
    cfg.setdefault("listen", "127.0.0.1:12340")
    cfg.setdefault("concurrency", 1)
    home = os.path.expanduser("~")
    cfg["command"] = [os.path.expanduser(c).replace("=~/", f"={home}/")   # --socket=~/...
                      for c in cfg["command"]]
    return cfg


def base_url(cfg: dict | None = None) -> str:
    cfg = cfg or config()
    return f"http://{cfg['listen']}/v1" if cfg else ""


def api_key(cfg: dict | None = None) -> str:
    cfg = cfg or config()
    f = Path(cfg.get("key_file") or "").expanduser() if cfg else None
    return f.read_text().strip() if f and f.is_file() else ""


def _pipe(client: socket.socket, command: list[str]) -> None:
    """One connection: the client's bytes to the command, its output back.

    The command's stdin is left open when the client stops sending: closing
    it can end `nc` before the reply arrives. The connection ends when the
    server's side does, or when the client goes away.
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

    threading.Thread(target=upstream, daemon=True).start()
    try:
        while data := proc.stdout.read1(65536):
            client.sendall(data)
    except OSError:
        pass
    finally:
        proc.kill()
        client.close()


def ensure(cfg: dict | None = None) -> bool:
    """Start the relay in this process unless something already listens there."""
    cfg = cfg or config()
    if not cfg:
        return False
    with _lock:
        if cfg["listen"] in _started:
            return True
        host, port = cfg["listen"].rsplit(":", 1)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind((host, int(port)))
        except OSError:
            srv.close()
            return True                   # another process (the server) has it
        srv.listen(16)
        _started.add(cfg["listen"])

    def serve():
        while True:
            client, _ = srv.accept()
            threading.Thread(target=_pipe, args=(client, cfg["command"]), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    return True


def models(timeout: float = 8.0, fresh: float = 30.0) -> list[str] | None:
    """The chat models the local server offers now, or None if it isn't answering.

    Cached for `fresh` seconds, so the page can ask often.
    """
    cfg = config()
    if not cfg:
        return None
    if time.time() - _cache["at"] < fresh:
        return _cache["models"]
    ensure(cfg)
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
