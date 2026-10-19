"""轻量 H5 / 快照 HTTP 服务（仅标准库）。"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import PROJECT_ROOT
from .snapshot import list_snapshots, load_latest_snapshot

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    h5_dir = PROJECT_ROOT / "reports" / "h5"
    snapshot_dir = PROJECT_ROOT / "data" / "snapshots"

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/h5", "/h5/"):
            self._send_file(self.h5_dir / "latest.html")
            return
        if path == "/health":
            entries = self._index()
            self._send_json(
                {
                    "status": "ok",
                    "h5": (self.h5_dir / "latest.html").exists(),
                    "snapshots": len(entries),
                    "latest": entries[0].get("key") if entries else None,
                }
            )
            return
        if path == "/api/latest":
            snapshot = self._latest_snapshot()
            if snapshot:
                self._send_json(snapshot)
            else:
                self._send_json({"error": "no snapshot"}, status=404)
            return
        if path == "/api/snapshots":
            self._send_json(self._index())
            return
        if path.startswith("/h5/"):
            relative = unquote(path[4:])
            target = (self.h5_dir / relative).resolve()
            if not _inside(target, self.h5_dir.resolve()):
                self._send_text("forbidden", status=403)
                return
            self._send_file(target)
            return
        if path.startswith("/snapshots/"):
            relative = unquote(path[len("/snapshots/") :])
            target = (self.snapshot_dir / relative).resolve()
            if not _inside(target, self.snapshot_dir.resolve()):
                self._send_text("forbidden", status=403)
                return
            self._send_file(target)
            return
        self._send_text("not found", status=404)

    def _latest_snapshot(self):
        # 与 publish/快照索引共用同一套回退逻辑，索引中的失效路径不会影响读取。
        return load_latest_snapshot(self.snapshot_dir)

    def _index(self):
        return list_snapshots(self.snapshot_dir, limit=500)

    def _send_file(self, path: Path):
        try:
            data = path.read_bytes()
        except OSError:
            self._send_text("not found", status=404)
            return
        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self._write(data)

    def _send_json(self, payload, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(data)

    def _send_text(self, text: str, status: int = 200):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(data)

    def _write(self, data: bytes):
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        sys.stderr.write("[http] " + (fmt % args) + "\n")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="A股量价 H5 / 快照 HTTP 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "reports"))
    parser.add_argument("--snapshot-dir", default=str(PROJECT_ROOT / "data" / "snapshots"))
    args = parser.parse_args(argv)

    Handler.h5_dir = Path(args.output_dir) / "h5"
    Handler.snapshot_dir = Path(args.snapshot_dir)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"H5 服务: http://{args.host}:{args.port}/")
    print(f"API:    http://{args.host}:{args.port}/api/latest")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
