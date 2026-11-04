#!/usr/bin/env python3
"""
FiveQThoughts — Compact Cross-Platform Viewer & Manager for the 5 Newest TheBrain 15 Quick Thoughts.
Runs on macOS and Windows using only Python's standard library and TheBrain's official REST API (/api/v2/quick-thoughts).
"""

import argparse
import base64
import concurrent.futures
import json
import mimetypes
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
LOCAL_CONFIG_PATH = APP_DIR / "config.local.json"
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"
USER_CONFIG_PATH = Path.home() / ".fiveqthoughts.json"

DEFAULT_BASE_URL = "http://localhost:11524"
DEFAULT_CARD_COUNT = 5


class AppConfig:
    def __init__(self):
        self.base_url: str = DEFAULT_BASE_URL
        self.api_key: str = ""
        self.card_count: int = DEFAULT_CARD_COUNT
        self.load()

    def load(self):
        # Load from config files in order of precedence (lowest to highest)
        for path in [DEFAULT_CONFIG_PATH, USER_CONFIG_PATH, LOCAL_CONFIG_PATH]:
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data.get("baseUrl"):
                        self.base_url = str(data["baseUrl"]).rstrip("/")
                    if data.get("apiKey"):
                        self.api_key = str(data["apiKey"]).strip()
                    if data.get("cardCount"):
                        self.card_count = int(data["cardCount"])
                except Exception as exc:
                    print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)

        # Environment variables override config files
        env_url = os.environ.get("THEBRAIN_API_URL", "").strip()
        if env_url:
            self.base_url = env_url.rstrip("/")
        env_key = os.environ.get("THEBRAIN_API_KEY", "").strip()
        if env_key:
            self.api_key = env_key

        # Normalize if user pasted /mcp or /api at the end of base_url
        for suffix in ["/mcp", "/api/v2", "/api"]:
            if self.base_url.endswith(suffix):
                self.base_url = self.base_url[: -len(suffix)].rstrip("/")

    def save(self, base_url: str, api_key: str, card_count: int = DEFAULT_CARD_COUNT):
        base_url = base_url.strip().rstrip("/")
        for suffix in ["/mcp", "/api/v2", "/api"]:
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)].rstrip("/")
        self.base_url = base_url or DEFAULT_BASE_URL
        self.api_key = api_key.strip()
        self.card_count = max(1, min(25, int(card_count)))

        payload = {
            "baseUrl": self.base_url,
            "apiKey": self.api_key,
            "cardCount": self.card_count,
        }
        LOCAL_CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def masked_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "*" * len(self.api_key)
        return f"{self.api_key[:4]}…{self.api_key[-4:]}"


CONFIG = AppConfig()


class TheBrainApiError(Exception):
    def __init__(self, status: int, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def thebrain_request(method: str, path: str, timeout: float = 15.0) -> tuple[bytes, str]:
    """Perform an HTTP request against TheBrain's REST API."""
    if not CONFIG.api_key:
        raise TheBrainApiError(
            401,
            "Kein TheBrain Local API Key konfiguriert. Bitte in den API-Einstellungen den Key aus 'TheBrain -> Settings -> User -> Local API' eintragen.",
        )

    url = f"{CONFIG.base_url}{path}"
    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {CONFIG.api_key}",
            "Accept": "application/json, */*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            return resp.read(), content_type
    except urllib.error.HTTPError as err:
        raw_body = b""
        try:
            raw_body = err.read()
        except Exception:
            pass
        text_body = raw_body.decode("utf-8", errors="replace").strip()
        details = None
        try:
            details = json.loads(text_body)
            if isinstance(details, dict) and details.get("message"):
                text_body = details["message"]
        except Exception:
            pass
        if not text_body:
            text_body = f"HTTP {err.code}: {err.reason}"
        raise TheBrainApiError(err.code, text_body, details=details)
    except urllib.error.URLError as err:
        raise TheBrainApiError(
            503,
            f"TheBrain Server unter {CONFIG.base_url} nicht erreichbar ({err.reason}). Läuft TheBrain 15?",
        )


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".heic"}
INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def is_image_file(name: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return True
    ext = Path(name or "").suffix.lower()
    return ext in IMAGE_EXTENSIONS


def enrich_thought_dto(dto: dict) -> dict:
    """
    Enrich a QuickThoughtDto from GET /api/v2/quick-thoughts/{id} with normalized
    inline images and attached images so the frontend can display and copy them easily.
    """
    thought_id = dto.get("id", "")
    markdown = dto.get("markdown") or ""

    inline_images = []
    for idx, match in enumerate(INLINE_IMAGE_RE.finditer(markdown)):
        alt_text = match.group(1) or ""
        raw_src = match.group(2).strip()
        # Strip optional markdown title in!("url" "title")
        if " " in raw_src and not raw_src.startswith("data:"):
            raw_src = raw_src.split(" ", 1)[0].strip()

        if raw_src.startswith("data:image/"):
            proxy_url = raw_src
            source_kind = "data"
            file_name = alt_text or f"inline-{idx + 1}.png"
        elif "/images/" in raw_src:
            file_name = urllib.parse.unquote(raw_src.rsplit("/images/", 1)[-1])
            proxy_url = f"/api/proxy/image?thoughtId={urllib.parse.quote(thought_id)}&fileName={urllib.parse.quote(file_name)}"
            source_kind = "inline"
        elif raw_src.startswith("http://") or raw_src.startswith("https://"):
            file_name = Path(urllib.parse.urlparse(raw_src).path).name or f"image-{idx + 1}.png"
            proxy_url = f"/api/proxy/external?url={urllib.parse.quote(raw_src)}"
            source_kind = "external"
        else:
            file_name = Path(urllib.parse.unquote(raw_src)).name
            proxy_url = f"/api/proxy/image?thoughtId={urllib.parse.quote(thought_id)}&fileName={urllib.parse.quote(file_name)}"
            source_kind = "inline"

        inline_images.append(
            {
                "id": f"inline-{idx}",
                "name": alt_text or file_name,
                "fileName": file_name,
                "rawSrc": match.group(2),
                "proxyUrl": proxy_url,
                "sourceKind": source_kind,
                "origin": "inline",
            }
        )

    attached_images = []
    other_files = []
    for f in dto.get("files") or []:
        f_id = f.get("id", "")
        f_name = f.get("name") or "attachment"
        f_ct = f.get("contentType") or ""
        f_size = f.get("byteLength") or 0
        proxy_url = (
            f"/api/proxy/file?thoughtId={urllib.parse.quote(thought_id)}"
            f"&fileId={urllib.parse.quote(f_id)}"
            f"&contentType={urllib.parse.quote(f_ct)}"
            f"&name={urllib.parse.quote(f_name)}"
        )
        entry = {
            "id": f_id,
            "name": f_name,
            "fileName": f_name,
            "byteLength": f_size,
            "contentType": f_ct,
            "proxyUrl": proxy_url,
            "sourceKind": "attachment",
            "origin": "attachment",
        }
        if is_image_file(f_name, f_ct):
            attached_images.append(entry)
        else:
            other_files.append(entry)

    dto["inlineImages"] = inline_images
    dto["attachedImages"] = attached_images
    dto["allImages"] = inline_images + attached_images
    dto["otherFiles"] = other_files
    return dto


def fetch_single_thought(thought_id: str) -> dict:
    raw, _ = thebrain_request("GET", f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}")
    dto = json.loads(raw.decode("utf-8"))
    return enrich_thought_dto(dto)


def fetch_top_thoughts(limit: int = DEFAULT_CARD_COUNT) -> dict:
    raw, _ = thebrain_request("GET", "/api/v2/quick-thoughts")
    summaries = json.loads(raw.decode("utf-8"))
    if not isinstance(summaries, list):
        summaries = []

    top_summaries = summaries[:limit]
    top_ids = [item["id"] for item in top_summaries if "id" in item]

    details_by_id = {}
    if top_ids:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(top_ids))) as pool:
            future_map = {pool.submit(fetch_single_thought, tid): tid for tid in top_ids}
            for fut in concurrent.futures.as_completed(future_map):
                tid = future_map[fut]
                try:
                    details_by_id[tid] = fut.result()
                except Exception as exc:
                    # Fallback to summary if detail fetch fails for one item
                    summary = next((s for s in top_summaries if s.get("id") == tid), {"id": tid})
                    details_by_id[tid] = enrich_thought_dto(
                        {
                            "id": tid,
                            "title": summary.get("title"),
                            "markdown": summary.get("preview") or "",
                            "deviceName": summary.get("deviceName"),
                            "capturedAt": summary.get("capturedAt"),
                            "createdAt": summary.get("createdAt"),
                            "modifiedAt": summary.get("modifiedAt"),
                            "links": [],
                            "files": [],
                            "error": str(exc),
                        }
                    )

    ordered_cards = [details_by_id[tid] for tid in top_ids if tid in details_by_id]
    return {
        "totalCount": len(summaries),
        "cards": ordered_cards,
        "allSummaries": summaries,
    }


def copy_text_to_os_clipboard(text: str) -> None:
    """Copy UTF-8 text to the native OS clipboard on macOS, Windows, or Linux."""
    system = platform.system()
    if system == "Darwin":
        env = os.environ.copy()
        env["LANG"] = "en_US.UTF-8"
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, env=env)
        proc.communicate(input=text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError("pbcopy failed")
    elif system == "Windows":
        # Use PowerShell Set-Clipboard reading UTF-8 from stdin
        ps_cmd = (
            "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
            "$inputText = [Console]::In.ReadToEnd(); "
            "Set-Clipboard -Value $inputText"
        )
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _, err = proc.communicate(input=text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(f"PowerShell Set-Clipboard failed: {err.decode('utf-8', 'replace')}")
    else:
        for cmd in [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
            if shutil.which(cmd[0]):
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                proc.communicate(input=text.encode("utf-8"))
                if proc.returncode == 0:
                    return
        raise RuntimeError("No clipboard utility found on this system.")


def copy_image_bytes_to_os_clipboard(image_bytes: bytes, suffix: str = ".png") -> None:
    """Copy raw image bytes as a bitmap/PNG image to the native OS clipboard on macOS or Windows."""
    system = platform.system()
    if not suffix.startswith("."):
        suffix = "." + suffix

    with tempfile.TemporaryDirectory(prefix="fiveqthoughts_") as tmpdir:
        src_path = Path(tmpdir) / f"source{suffix}"
        src_path.write_bytes(image_bytes)

        if system == "Darwin":
            png_path = Path(tmpdir) / "clipboard.png"
            if suffix.lower() == ".png":
                png_path = src_path
            else:
                # Convert JPEG/WebP/GIF/HEIC/TIFF to PNG via macOS built-in sips
                subprocess.run(
                    ["/usr/bin/sips", "-s", "format", "png", str(src_path), "--out", str(png_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            apple_script = f'set the clipboard to (read (POSIX file "{png_path}") as «class PNGf»)'
            subprocess.run(["osascript", "-e", apple_script], check=True)

        elif system == "Windows":
            # PowerShell STA mode with System.Windows.Forms.Clipboard::SetImage
            escaped_path = str(src_path).replace("'", "''")
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                f"$img = [System.Drawing.Image]::FromFile('{escaped_path}'); "
                "try { [System.Windows.Forms.Clipboard]::SetImage($img) } "
                "finally { $img.Dispose() }"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps_cmd],
                capture_output=True,
                text=True,
            )
            if res.returncode != 0:
                raise RuntimeError(f"PowerShell SetImage failed: {res.stderr.strip()}")
        else:
            if shutil.which("wl-copy"):
                proc = subprocess.Popen(["wl-copy", "--type", "image/png"], stdin=subprocess.PIPE)
                proc.communicate(input=image_bytes)
            elif shutil.which("xclip"):
                proc = subprocess.Popen(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", str(src_path)]
                )
                proc.wait()
            else:
                raise RuntimeError("No image clipboard tool available.")


class FiveQRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep console logs concise
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/api/config":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "baseUrl": CONFIG.base_url,
                        "hasApiKey": bool(CONFIG.api_key),
                        "maskedKey": CONFIG.masked_key(),
                        "cardCount": CONFIG.card_count,
                        "platform": platform.system(),
                    },
                )
                return

            if path == "/api/thoughts":
                limit = int(qs.get("limit", [CONFIG.card_count])[0])
                data = fetch_top_thoughts(limit=limit)
                self._send_json(HTTPStatus.OK, data)
                return

            if path.startswith("/api/thoughts/"):
                thought_id = urllib.parse.unquote(path.split("/api/thoughts/", 1)[1].strip("/"))
                dto = fetch_single_thought(thought_id)
                self._send_json(HTTPStatus.OK, dto)
                return

            if path == "/api/proxy/file":
                thought_id = qs.get("thoughtId", [""])[0]
                file_id = qs.get("fileId", [""])[0]
                hint_ct = qs.get("contentType", [""])[0]
                name = qs.get("name", ["file"])[0]
                raw, upstream_ct = thebrain_request(
                    "GET",
                    f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/files/{urllib.parse.quote(file_id)}",
                    timeout=30.0,
                )
                content_type = hint_ct or upstream_ct or mimetypes.guess_type(name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/proxy/image":
                thought_id = qs.get("thoughtId", [""])[0]
                file_name = qs.get("fileName", [""])[0]
                raw, upstream_ct = thebrain_request(
                    "GET",
                    f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/images/{urllib.parse.quote(file_name)}",
                    timeout=30.0,
                )
                content_type = upstream_ct
                if not content_type or content_type == "application/octet-stream":
                    content_type = mimetypes.guess_type(file_name)[0] or "image/png"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "private, max-age=300")
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/proxy/external":
                ext_url = qs.get("url", [""])[0]
                if not (ext_url.startswith("http://") or ext_url.startswith("https://")):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid external URL"})
                    return
                req = urllib.request.Request(ext_url, headers={"User-Agent": "FiveQThoughts/1.0"})
                with urllib.request.urlopen(req, timeout=15.0) as resp:
                    raw = resp.read()
                    content_type = resp.headers.get("Content-Type", "image/png")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            # Static files
            if path == "/" or path == "/index.html":
                self._serve_static(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path == "/styles.css":
                self._serve_static(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
                return
            if path == "/app.js":
                self._serve_static(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Not found: {path}"})

        except TheBrainApiError as api_err:
            self._send_json(
                api_err.status,
                {"error": api_err.message, "status": api_err.status, "details": api_err.details},
            )
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json_body()

            if path == "/api/config":
                base_url = body.get("baseUrl") or CONFIG.base_url
                api_key = body.get("apiKey")
                # If apiKey is omitted or empty, keep existing key unless explicitly cleared
                if api_key is None or api_key == "":
                    api_key = CONFIG.api_key
                card_count = int(body.get("cardCount") or CONFIG.card_count)
                CONFIG.save(base_url=base_url, api_key=api_key, card_count=card_count)
                # Test the connection
                data = fetch_top_thoughts(limit=CONFIG.card_count)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "baseUrl": CONFIG.base_url,
                        "maskedKey": CONFIG.masked_key(),
                        "cardCount": CONFIG.card_count,
                        "totalCount": data["totalCount"],
                    },
                )
                return

            if path == "/api/clipboard/text":
                text = body.get("text") or ""
                copy_text_to_os_clipboard(text)
                self._send_json(HTTPStatus.OK, {"ok": True})
                return

            if path == "/api/clipboard/image":
                source_kind = body.get("sourceKind") or "attachment"
                thought_id = body.get("thoughtId") or ""
                file_id = body.get("fileId") or ""
                file_name = body.get("fileName") or "image.png"
                raw_url = body.get("url") or ""

                if source_kind == "attachment":
                    img_bytes, _ = thebrain_request(
                        "GET",
                        f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/files/{urllib.parse.quote(file_id)}",
                        timeout=30.0,
                    )
                elif source_kind == "inline":
                    img_bytes, _ = thebrain_request(
                        "GET",
                        f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/images/{urllib.parse.quote(file_name)}",
                        timeout=30.0,
                    )
                elif source_kind == "data" and raw_url.startswith("data:image/"):
                    header, b64_data = raw_url.split(",", 1)
                    img_bytes = base64.b64decode(b64_data)
                elif source_kind == "external" and (raw_url.startswith("http://") or raw_url.startswith("https://")):
                    req = urllib.request.Request(raw_url, headers={"User-Agent": "FiveQThoughts/1.0"})
                    with urllib.request.urlopen(req, timeout=15.0) as resp:
                        img_bytes = resp.read()
                else:
                    raise ValueError(f"Unbekannte Bildquelle: {source_kind}")

                suffix = Path(file_name).suffix or ".png"
                copy_image_bytes_to_os_clipboard(img_bytes, suffix=suffix)
                self._send_json(HTTPStatus.OK, {"ok": True})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})

        except TheBrainApiError as api_err:
            self._send_json(
                api_err.status,
                {"error": api_err.message, "status": api_err.status, "details": api_err.details},
            )
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path.startswith("/api/thoughts/"):
                thought_id = urllib.parse.unquote(path.split("/api/thoughts/", 1)[1].strip("/"))
                thebrain_request("DELETE", f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}")
                self._send_json(HTTPStatus.OK, {"ok": True, "deletedId": thought_id})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})

        except TheBrainApiError as api_err:
            self._send_json(
                api_err.status,
                {"error": api_err.message, "status": api_err.status, "details": api_err.details},
            )
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _serve_static(self, file_path: Path, content_type: str):
        if not file_path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Missing static file: {file_path.name}"})
            return
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def find_free_port(preferred: int = 11525) -> int:
    for port in [preferred, 11526, 11527, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return 11525


def open_app_window(url: str):
    """Open the UI in a compact chromeless app window (Chrome/Edge/Brave) or fallback to default browser."""
    system = platform.system()
    candidates = []

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    elif system == "Windows":
        prog_files = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        for base in prog_files:
            if not base:
                continue
            candidates.extend(
                [
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
                ]
            )

    for binary in candidates:
        if os.path.isfile(binary):
            try:
                subprocess.Popen(
                    [binary, f"--app={url}", "--window-size=1160,840"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except Exception:
                pass

    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description="FiveQThoughts — TheBrain 15 Quick Thoughts Viewer")
    parser.add_argument("--base-url", help="TheBrain Local API Base URL (default: http://localhost:11524)")
    parser.add_argument("--api-key", help="TheBrain Local API Bearer Token (from Settings > User > Local API)")
    parser.add_argument("--port", type=int, default=0, help="Local port for FiveQThoughts UI (default: auto)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser window automatically")
    args = parser.parse_args()

    if args.base_url or args.api_key:
        CONFIG.save(
            base_url=args.base_url or CONFIG.base_url,
            api_key=args.api_key or CONFIG.api_key,
            card_count=CONFIG.card_count,
        )

    port = args.port or find_free_port(11525)
    server = ThreadingHTTPServer(("127.0.0.1", port), FiveQRequestHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"FiveQThoughts läuft auf {url}")
    print(f"Verbunden mit TheBrain API: {CONFIG.base_url}/api/v2/quick-thoughts")
    if CONFIG.api_key:
        print(f"API Key geladen: {CONFIG.masked_key()}")
    else:
        print("Hinweis: Noch kein API Key hinterlegt. Bitte in der App unter 'API-Einstellungen' eingeben.")

    if not args.no_browser:
        threading.Timer(0.4, open_app_window, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFiveQThoughts beendet.")
        server.server_close()


if __name__ == "__main__":
    main()
