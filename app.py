#!/usr/bin/env python3
"""lbm_eval_models の全モデル (SDF / URDF / dmd.yaml) をブラウザで見るビューア。

  app.py serve            モデル一覧ページ (WEB_PORT) を起動。選んだモデルを Meshcat で表示する。
  app.py show <model>     1モデルを Meshcat (MESHCAT_PORT) で表示する (serve が子プロセスとして使う)。
  app.py list             モデル一覧を表示。
  app.py check            全モデルが読み込めるか確認。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
# ブラウザから見たポート (docker のポート割り当てを変えた場合に合わせる)。
PUBLIC_WEB_PORT = int(os.environ.get("PUBLIC_WEB_PORT", str(WEB_PORT)))
MESHCAT_PORT = int(os.environ.get("MESHCAT_PORT", "7000"))
PUBLIC_MESHCAT_PORT = int(os.environ.get("PUBLIC_MESHCAT_PORT", str(MESHCAT_PORT)))
DEFAULT_MODEL = os.environ.get(
    "DEFAULT_MODEL", "stations/cabot/add_cabot_simulation.dmd.yaml")
EXTS = (".sdf", ".urdf", ".dmd.yaml")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_FILES = {"index.html": "text/html", "style.css": "text/css",
                "app.js": "text/javascript"}


def pkg_dir():
    import lbm_eval_models

    return list(lbm_eval_models.__path__)[0]


def all_models():
    root_dir = pkg_dir()
    found = []
    for root, _, files in os.walk(root_dir):
        for f in files:
            if f.endswith(EXTS):
                found.append(os.path.relpath(os.path.join(root, f), root_dir))
    return sorted(found)


def make_visualizer(meshcat=None, frames=False):
    from pydrake.visualization import ModelVisualizer

    viz = ModelVisualizer(meshcat=meshcat, browser_new=False,
                          visualize_frames=frames)
    viz.package_map().Add("lbm_eval_models", pkg_dir())
    return viz


# ---------------------------------------------------------------- show / check

def cmd_show(model, frames):
    from pydrake.geometry import Meshcat

    if model not in all_models():
        print(f"unknown model: {model}", file=sys.stderr)
        return 2
    meshcat = Meshcat(port=MESHCAT_PORT)
    viz = make_visualizer(meshcat, frames)
    viz.AddModels(os.path.join(pkg_dir(), model))
    viz.Run()
    return 0


def cmd_check():
    models = all_models()
    bad = 0
    for m in models:
        try:
            viz = make_visualizer()
            viz.AddModels(os.path.join(pkg_dir(), m))
            viz.Finalize()
            print(f"ok    {m}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL  {m}\n        {str(e).strip().splitlines()[0][:160]}")
    print(f"\n{len(models) - bad} / {len(models)} loaded")
    return 0


# ----------------------------------------------------------------------- serve

class Viewer:
    """Meshcat を持つ子プロセスを1つだけ動かし、モデル切り替えのたびに入れ替える。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.model = None
        self.frames = False
        self.log = None

    def _port_open(self):
        with socket.socket() as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", MESHCAT_PORT)) == 0

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None
        deadline = time.time() + 5
        while self._port_open() and time.time() < deadline:
            time.sleep(0.1)

    def show(self, model, frames):
        with self.lock:
            self._stop()
            self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
            cmd = [sys.executable, os.path.abspath(__file__), "show", model]
            if frames:
                cmd.append("--frames")
            self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=self.log)
            deadline = time.time() + 120
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    break
                if self._port_open():
                    # Meshcat は読み込み前に待ち受けを始めるので、失敗で落ちないか少し待つ。
                    time.sleep(1.0)
                    if self.proc.poll() is None:
                        self.model, self.frames = model, frames
                        return {"ok": True, "model": model}
                    break
                time.sleep(0.2)
            self.log.flush()
            self.log.seek(0)
            lines = [ln.strip() for ln in self.log.read().splitlines() if ln.strip()]
            err = lines[-1] if lines else "viewer did not start"
            self._stop()
            self.model = None
            return {"ok": False, "model": model, "error": err[:400]}


VIEWER = Viewer()
MODELS = []



class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, name):
        # static/ 直下にある決まったファイルだけを返す
        if name not in STATIC_FILES:
            self._send(404, "not found", "text/plain")
            return
        with open(os.path.join(STATIC_DIR, name), encoding="utf-8") as f:
            self._send(200, f.read(), STATIC_FILES[name])

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/":
            self._file("index.html")
        elif url.path.startswith("/static/"):
            self._file(url.path[len("/static/"):])
        elif url.path == "/api/models":
            self._json({"models": MODELS, "current": VIEWER.model,
                        "meshcatPort": PUBLIC_MESHCAT_PORT,
                        "default": DEFAULT_MODEL if DEFAULT_MODEL in MODELS else None})
        elif url.path == "/api/show":
            q = parse_qs(url.query)
            model = q.get("m", [""])[0]
            if model not in MODELS:  # 一覧にあるモデルだけを許可する
                self._json({"ok": False, "error": "unknown model"}, 400)
                return
            self._json(VIEWER.show(model, q.get("frames", ["0"])[0] == "1"))
        else:
            self._send(404, "not found", "text/plain")

    def log_message(self, fmt, *args):
        if "/api/show" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))


def cmd_serve():
    global MODELS
    MODELS = all_models()
    print(f"{len(MODELS)} models found in {pkg_dir()}")
    if DEFAULT_MODEL in MODELS:
        print(f"loading default model: {DEFAULT_MODEL}")
        print(VIEWER.show(DEFAULT_MODEL, False))
    print(f"\n  モデル一覧:  http://localhost:{PUBLIC_WEB_PORT}\n"
          f"  Meshcat 単体: http://localhost:{PUBLIC_MESHCAT_PORT}\n", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        VIEWER._stop()
    return 0


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "serve"
    if cmd == "serve":
        return cmd_serve()
    if cmd == "show" and len(args) >= 2:
        return cmd_show(args[1], "--frames" in args)
    if cmd == "list":
        print("\n".join(all_models()))
        return 0
    if cmd == "check":
        return cmd_check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
