#!/usr/bin/env python3
"""lbm_eval_models の全モデル (SDF / URDF / dmd.yaml) をブラウザで見るビューア。

  app.py serve            モデル一覧ページ (WEB_PORT) を起動。選んだモデルを Meshcat で表示する。
  app.py show <model>     1モデルを Meshcat (MESHCAT_PORT) で表示する (serve が子プロセスとして使う)。
  app.py parts <model>    モデルの部品と寸法を表示。
  app.py list             モデル一覧を表示。
  app.py check            全モデルが読み込めるか確認。
"""
import json
import os
import queue
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


# ------------------------------------------------------------------ 部品と寸法

def _mm(values):
    return [round(float(v) * 1000.0, 1) for v in values]


def _describe(shape, extent):
    """形状の種類、寸法 [mm]、表示用の文字列を返す。"""
    from pydrake.geometry import (Box, Capsule, Convex, Cylinder, Ellipsoid,
                                  Mesh, Sphere)

    if isinstance(shape, Box):
        d = _mm([shape.width(), shape.depth(), shape.height()])
        return "箱", d, f"{d[0]} × {d[1]} × {d[2]}"
    if isinstance(shape, Cylinder):
        dia, length = _mm([2 * shape.radius(), shape.length()])
        return "円柱", [dia, dia, length], f"直径 {dia} × 長さ {length}"
    if isinstance(shape, Sphere):
        dia = _mm([2 * shape.radius()])[0]
        return "球", [dia, dia, dia], f"直径 {dia}"
    if isinstance(shape, Capsule):
        dia, length = _mm([2 * shape.radius(), shape.length()])
        return "カプセル", [dia, dia, round(length + dia, 1)], \
            f"直径 {dia} × 円柱部の長さ {length}"
    if isinstance(shape, Ellipsoid):
        d = _mm([2 * shape.a(), 2 * shape.b(), 2 * shape.c()])
        return "楕円体", d, f"{d[0]} × {d[1]} × {d[2]}"
    kind = "メッシュ" if isinstance(shape, Mesh) else \
        "凸メッシュ" if isinstance(shape, Convex) else type(shape).__name__
    if extent is None:
        return kind, None, "寸法なし"
    d = _mm(extent)
    return kind, d, f"x {d[0]} × y {d[1]} × z {d[2]}"


def _extent_in_part_frame(insp, gid):
    """メッシュを部品 (リンク) の座標軸に沿った箱で囲んだときの3辺 [m]。"""
    import numpy as np

    try:
        hull = insp.GetConvexHull(gid)
    except Exception:  # noqa: BLE001
        hull = None
    if hull is None:
        return None
    X_FG = insp.GetPoseInFrame(gid)
    pts = np.array([X_FG.multiply(hull.vertex(i)) for i in range(hull.num_vertices())])
    return pts.max(axis=0) - pts.min(axis=0)


def collect_parts(diagram, context):
    """部品 (リンク) ごとに、見た目と衝突形状の寸法を集める。"""
    from pydrake.geometry import Role

    sg = diagram.scene_graph()
    insp = sg.get_query_output_port().Eval(sg.GetMyContextFromRoot(context)).inspector()
    parts = {}
    for role, label in ((Role.kIllustration, "見た目"), (Role.kProximity, "衝突")):
        for gid in insp.GetAllGeometryIds(role):
            frame = insp.GetName(insp.GetFrameId(gid))
            gname = insp.GetName(gid)
            # 慣性の可視化や座標軸など、ビューアが足した補助形状は除く
            if frame.startswith("InertiaVisualizer::") or gname.startswith(("$", "_")):
                continue
            shape = insp.GetShape(gid)
            extent = None
            if type(shape).__name__ in ("Mesh", "Convex"):
                extent = _extent_in_part_frame(insp, gid)
            kind, dims, text = _describe(shape, extent)
            part = parts.setdefault(frame, {
                "name": frame,
                "path": "/drake/illustration/" + frame.replace("::", "/"),
                "geoms": []})
            part["geoms"].append({"role": label, "name": gname.split("::")[-1],
                                  "shape": kind, "dims": dims, "text": text})
    return sorted(parts.values(), key=lambda p: p["name"])


# ---------------------------------------------------------------- show / check

def _load(model, meshcat=None, frames=False):
    viz = make_visualizer(meshcat, frames)
    viz.AddModels(os.path.join(pkg_dir(), model))
    viz.Finalize()
    # ModelVisualizer は構築済みの図を公開していないので内部属性を使う (Drake の版は固定)。
    return viz, collect_parts(viz._diagram, viz._context)


def cmd_show(model, frames, parts_out=None, managed=False):
    from pydrake.geometry import Meshcat

    if model not in all_models():
        print(f"unknown model: {model}", file=sys.stderr)
        return 2
    meshcat = Meshcat(port=MESHCAT_PORT)
    viz, parts = _load(model, meshcat, frames)
    if parts_out:  # 読み込み完了の合図を兼ねる
        with open(parts_out + ".tmp", "w", encoding="utf-8") as f:
            json.dump(parts, f, ensure_ascii=False)
        os.replace(parts_out + ".tmp", parts_out)
    viz.Run(loop_once=True)  # 初回の描画

    # serve から標準入力で届く指示 (部品の単独表示) を受け取る。
    # Meshcat は生成したスレッドからしか操作できないので、読むだけ別スレッドにする。
    cmds = queue.Queue()

    def reader():
        for line in sys.stdin:
            cmds.put(line.strip())
        cmds.put("__eof__")

    if managed:
        threading.Thread(target=reader, daemon=True).start()

    paths = {p["name"]: p["path"] for p in parts}
    diagram, context, sliders = viz._diagram, viz._context, viz._sliders
    plant = diagram.plant()
    stop = "Stop Running"
    meshcat.AddButton(stop, "Escape")
    try:
        while meshcat.GetButtonClicks(stop) == 0:
            q = sliders.get_output_port().Eval(sliders.GetMyContextFromRoot(context))
            plant.SetPositions(plant.GetMyMutableContextFromRoot(context), q)
            diagram.ForcedPublish(context)
            while not cmds.empty():
                cmd = cmds.get()
                if cmd == "__eof__":
                    return 0
                only = cmd[len("isolate "):] if cmd.startswith("isolate ") else None
                for name, path in paths.items():
                    meshcat.SetProperty(path, "visible", only is None or name == only)
            time.sleep(1 / 32.0)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_parts(model):
    if model not in all_models():
        print(f"unknown model: {model}", file=sys.stderr)
        return 2
    _, parts = _load(model)
    for p in parts:
        print(p["name"])
        for g in p["geoms"]:
            print(f"    [{g['role']}] {g['shape']}  {g['text']} mm  ({g['name']})")
    return 0


def cmd_check():
    models = all_models()
    bad = 0
    for m in models:
        try:
            _load(m)
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
        self.parts = []
        self.isolated = None
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
        self.model, self.parts, self.isolated = None, [], None
        deadline = time.time() + 5
        while self._port_open() and time.time() < deadline:
            time.sleep(0.1)

    def state(self):
        alive = self.proc is not None and self.proc.poll() is None
        return {"current": self.model if alive else None,
                "parts": self.parts if alive else [],
                "isolated": self.isolated if alive else None}

    def show(self, model, frames):
        with self.lock:
            self._stop()
            self.log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
            parts_file = os.path.join(tempfile.mkdtemp(), "parts.json")
            cmd = [sys.executable, os.path.abspath(__file__), "show", model,
                   "--managed", "--parts-out", parts_file]
            if frames:
                cmd.append("--frames")
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True,
                                         stdout=self.log, stderr=self.log)
            deadline = time.time() + 180
            while time.time() < deadline and self.proc.poll() is None:
                if os.path.exists(parts_file):  # 読み込み完了
                    with open(parts_file, encoding="utf-8") as f:
                        self.parts = json.load(f)
                    self.model = model
                    return {"ok": True, "model": model, "parts": self.parts}
                time.sleep(0.1)
            self.log.flush()
            self.log.seek(0)
            lines = [ln.strip() for ln in self.log.read().splitlines() if ln.strip()]
            err = lines[-1] if lines else "viewer did not start"
            self._stop()
            return {"ok": False, "model": model, "error": err[:400]}

    def isolate(self, part):
        """part だけを表示する。None なら全部品を表示に戻す。"""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                return {"ok": False, "error": "viewer is not running"}
            if part is not None and part not in {p["name"] for p in self.parts}:
                return {"ok": False, "error": "unknown part"}
            self.proc.stdin.write(("showall" if part is None else f"isolate {part}") + "\n")
            self.proc.stdin.flush()
            self.isolated = part
            return {"ok": True, "isolated": part}


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
        q = parse_qs(url.query)
        if url.path == "/":
            self._file("index.html")
        elif url.path.startswith("/static/"):
            self._file(url.path[len("/static/"):])
        elif url.path == "/api/models":
            self._json({"models": MODELS, "meshcatPort": PUBLIC_MESHCAT_PORT,
                        "default": DEFAULT_MODEL if DEFAULT_MODEL in MODELS else None,
                        **VIEWER.state()})
        elif url.path == "/api/show":
            model = q.get("m", [""])[0]
            if model not in MODELS:  # 一覧にあるモデルだけを許可する
                self._json({"ok": False, "error": "unknown model"}, 400)
                return
            self._json(VIEWER.show(model, q.get("frames", ["0"])[0] == "1"))
        elif url.path == "/api/isolate":
            res = VIEWER.isolate(q.get("part", [""])[0] or None)
            self._json(res, 200 if res["ok"] else 400)
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
        res = VIEWER.show(DEFAULT_MODEL, False)
        print("ok" if res["ok"] else res)
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
        parts_out = args[args.index("--parts-out") + 1] if "--parts-out" in args else None
        return cmd_show(args[1], "--frames" in args, parts_out, "--managed" in args)
    if cmd == "parts" and len(args) >= 2:
        return cmd_parts(args[1])
    if cmd == "list":
        print("\n".join(all_models()))
        return 0
    if cmd == "check":
        return cmd_check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
