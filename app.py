#!/usr/bin/env python3
"""
FiveQThoughts — Compact Cross-Platform Viewer & Manager for the 5 Newest TheBrain 15 Quick Thoughts.
Runs on macOS and Windows using only Python's standard library and TheBrain's official REST API (/api/v2/quick-thoughts).
"""

import argparse
import base64
import concurrent.futures
import datetime
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
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

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

        env_url = os.environ.get("THEBRAIN_API_URL", "").strip()
        if env_url:
            self.base_url = env_url.rstrip("/")
        env_key = os.environ.get("THEBRAIN_API_KEY", "").strip()
        if env_key:
            self.api_key = env_key

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


def thebrain_request(
    method: str,
    path: str,
    body: bytes = None,
    content_type: str = None,
    timeout: float = 20.0,
) -> tuple[bytes, str]:
    """Perform an HTTP request against TheBrain's REST API."""
    if not CONFIG.api_key:
        raise TheBrainApiError(
            401,
            "Kein TheBrain Local API Key konfiguriert. Bitte in den API-Einstellungen den Key aus 'TheBrain -> Settings -> User -> Local API' eintragen.",
        )

    url = f"{CONFIG.base_url}{path}"
    headers = {
        "Authorization": f"Bearer {CONFIG.api_key}",
        "Accept": "application/json, */*",
    }
    if content_type:
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_ct = resp.headers.get("Content-Type", "application/octet-stream")
            return resp.read(), resp_ct
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


def build_multipart_formdata(files: list[dict]) -> tuple[bytes, str]:
    """
    Build a multipart/form-data body for uploading files to POST /api/v2/quick-thoughts/{id}/files.
    Each item in `files` has {"name": filename, "contentType": mime, "data": bytes}.
    """
    boundary = f"----FiveQThoughtsBoundary{uuid.uuid4().hex}"
    chunks = []
    for idx, f in enumerate(files):
        fname = (f.get("name") or f"attachment-{idx + 1}.png").replace('"', "_")
        ctype = f.get("contentType") or mimetypes.guess_type(fname)[0] or "application/octet-stream"
        data = f.get("data") or b""
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="files"; filename="{fname}"\r\n'.encode("utf-8")
        )
        chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


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
    inline images and attached images so the frontend can display, copy, and edit them easily.
    """
    thought_id = dto.get("id", "")
    markdown = dto.get("markdown") or ""

    inline_images = []
    for idx, match in enumerate(INLINE_IMAGE_RE.finditer(markdown)):
        alt_text = match.group(1) or ""
        raw_src = match.group(2).strip()
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


def fetch_summaries_only(limit: int = DEFAULT_CARD_COUNT) -> dict:
    """Lightweight poll endpoint to check if the top Quick Thoughts changed."""
    raw, _ = thebrain_request("GET", "/api/v2/quick-thoughts")
    summaries = json.loads(raw.decode("utf-8"))
    if not isinstance(summaries, list):
        summaries = []
    top = summaries[:limit]
    signature = "|".join(
        f"{s.get('id')}:{s.get('modifiedAt')}:{s.get('fileCount')}:{s.get('linkCount')}"
        for s in top
    )
    return {
        "totalCount": len(summaries),
        "signature": f"{len(summaries)}#{signature}",
        "topSummaries": top,
    }


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
    signature = "|".join(
        f"{s.get('id')}:{s.get('modifiedAt')}:{s.get('fileCount')}:{s.get('linkCount')}"
        for s in top_summaries
    )
    return {
        "totalCount": len(summaries),
        "signature": f"{len(summaries)}#{signature}",
        "cards": ordered_cards,
        "allSummaries": summaries,
    }


def parse_data_uri_files(attachments: list[dict]) -> list[dict]:
    """Convert frontend base64/dataUrl attachment objects into raw bytes for multipart upload."""
    parsed = []
    for idx, att in enumerate(attachments or []):
        data_url = att.get("dataUrl") or ""
        name = att.get("name") or f"Clipboard-{idx + 1}.png"
        content_type = att.get("contentType") or "image/png"
        if data_url.startswith("data:"):
            header, b64_part = data_url.split(",", 1)
            if ";" in header and ":" in header:
                content_type = header.split(":", 1)[1].split(";", 1)[0] or content_type
            raw_bytes = base64.b64decode(b64_part)
        else:
            raw_bytes = base64.b64decode(data_url)
        parsed.append({"name": name, "contentType": content_type, "data": raw_bytes})
    return parsed


def create_quick_thought(markdown: str, links: list, attachments: list) -> dict:
    """Create a new Quick Thought via POST /api/v2/quick-thoughts and upload any attached files."""
    payload = {
        "markdown": markdown or "",
        "links": links or [],
    }
    raw_resp, _ = thebrain_request(
        "POST",
        "/api/v2/quick-thoughts",
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )
    dto = json.loads(raw_resp.decode("utf-8"))
    thought_id = dto.get("id")

    files_to_upload = parse_data_uri_files(attachments)
    if thought_id and files_to_upload:
        mp_body, mp_ct = build_multipart_formdata(files_to_upload)
        thebrain_request(
            "POST",
            f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/files",
            body=mp_body,
            content_type=mp_ct,
            timeout=60.0,
        )
        dto = fetch_single_thought(thought_id)
        return dto

    return enrich_thought_dto(dto)


def update_quick_thought(
    thought_id: str,
    markdown: str,
    links: list,
    new_attachments: list = None,
    delete_file_ids: list = None,
) -> dict:
    """Update an existing Quick Thought via PATCH /api/v2/quick-thoughts/{id} and manage its files."""
    payload = {"markdown": markdown}
    if links is not None:
        payload["links"] = links

    thebrain_request(
        "PATCH",
        f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}",
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )

    for fid in delete_file_ids or []:
        if fid:
            thebrain_request(
                "DELETE",
                f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/files/{urllib.parse.quote(fid)}",
            )

    files_to_upload = parse_data_uri_files(new_attachments or [])
    if files_to_upload:
        mp_body, mp_ct = build_multipart_formdata(files_to_upload)
        thebrain_request(
            "POST",
            f"/api/v2/quick-thoughts/{urllib.parse.quote(thought_id)}/files",
            body=mp_body,
            content_type=mp_ct,
            timeout=60.0,
        )

    return fetch_single_thought(thought_id)


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
                subprocess.run(
                    ["/usr/bin/sips", "-s", "format", "png", str(src_path), "--out", str(png_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            apple_script = f'set the clipboard to (read (POSIX file "{png_path}") as «class PNGf»)'
            subprocess.run(["osascript", "-e", apple_script], check=True)

        elif system == "Windows":
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


def read_image_from_os_clipboard() -> tuple[bytes, str]:
    """Read an image from the native macOS or Windows clipboard and return (png_bytes, filename)."""
    system = platform.system()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"Clipboard-{timestamp}.png"

    with tempfile.TemporaryDirectory(prefix="fiveq_clipread_") as tmpdir:
        png_path = Path(tmpdir) / "clip.png"

        if system == "Darwin":
            script = f"""
            try
                set imgData to the clipboard as «class PNGf»
                set fRef to open for access POSIX file "{png_path}" with write permission
                set eof fRef to 0
                write imgData to fRef
                close access fRef
                return "OK"
            on error errMsg
                try
                    close access POSIX file "{png_path}"
                end try
                return "ERR:" & errMsg
            end try
            """
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            out = res.stdout.strip()
            if not out.startswith("OK") or not png_path.is_file() or png_path.stat().st_size == 0:
                raise ValueError("Keine Grafik in der System-Zwischenablage gefunden.")
            return png_path.read_bytes(), filename

        elif system == "Windows":
            escaped_path = str(png_path).replace("'", "''")
            ps_cmd = (
                "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                "if ([System.Windows.Forms.Clipboard]::ContainsImage()) { "
                "  $img = [System.Windows.Forms.Clipboard]::GetImage(); "
                f"  try {{ $img.Save('{escaped_path}', [System.Drawing.Imaging.ImageFormat]::Png); Write-Output 'OK' }} "
                "  finally { $img.Dispose() } "
                "} else { Write-Output 'EMPTY' }"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps_cmd],
                capture_output=True,
                text=True,
            )
            if "OK" not in res.stdout or not png_path.is_file():
                raise ValueError("Keine Grafik in der Windows-Zwischenablage gefunden.")
            return png_path.read_bytes(), filename

        else:
            raise ValueError("Lesen von Bildern aus der System-Zwischenablage wird auf diesem OS nur über Cmd+V / Ctrl+V unterstützt.")


class FiveQRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
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

            if path == "/api/thoughts/poll":
                limit = int(qs.get("limit", [CONFIG.card_count])[0])
                data = fetch_summaries_only(limit=limit)
                self._send_json(HTTPStatus.OK, data)
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

            if path == "/api/clipboard/image":
                img_bytes, fname = read_image_from_os_clipboard()
                b64 = base64.b64encode(img_bytes).decode("ascii")
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "name": fname,
                        "contentType": "image/png",
                        "byteLength": len(img_bytes),
                        "dataUrl": f"data:image/png;base64,{b64}",
                    },
                )
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
                if api_key is None or api_key == "":
                    api_key = CONFIG.api_key
                card_count = int(body.get("cardCount") or CONFIG.card_count)
                CONFIG.save(base_url=base_url, api_key=api_key, card_count=card_count)
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

            if path == "/api/thoughts":
                markdown = body.get("markdown") or ""
                links = body.get("links") or []
                attachments = body.get("attachments") or []
                created_dto = create_quick_thought(markdown=markdown, links=links, attachments=attachments)
                self._send_json(HTTPStatus.OK, created_dto)
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
                    _, b64_data = raw_url.split(",", 1)
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

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path.startswith("/api/thoughts/"):
                thought_id = urllib.parse.unquote(path.split("/api/thoughts/", 1)[1].strip("/"))
                body = self._read_json_body()
                markdown = body.get("markdown") if "markdown" in body else ""
                links = body.get("links")
                new_attachments = body.get("newAttachments") or []
                delete_file_ids = body.get("deleteFileIds") or []
                updated_dto = update_quick_thought(
                    thought_id=thought_id,
                    markdown=markdown,
                    links=links,
                    new_attachments=new_attachments,
                    delete_file_ids=delete_file_ids,
                )
                self._send_json(HTTPStatus.OK, updated_dto)
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


MACOS_SWIFT_SOURCE = APP_DIR / "native" / "macos_host.swift"
MACOS_APP_BUNDLE = APP_DIR / "FiveQThoughts.app"
MACOS_APP_BINARY = MACOS_APP_BUNDLE / "Contents" / "MacOS" / "FiveQThoughts"
MACOS_INFO_PLIST = MACOS_APP_BUNDLE / "Contents" / "Info.plist"

MACOS_PLIST_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>FiveQThoughts</string>
    <key>CFBundleIdentifier</key>
    <string>com.mbaas.fiveqthoughts</string>
    <key>CFBundleName</key>
    <string>FiveQThoughts</string>
    <key>CFBundleDisplayName</key>
    <string>FiveQThoughts</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""


def find_free_port(preferred: int = 11525) -> int:
    for port in [preferred, 11526, 11527, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return 11525


def ensure_macos_native_app() -> Optional[Path]:
    """Compile native/macos_host.swift into FiveQThoughts.app if needed."""
    if platform.system() != "Darwin" or not MACOS_SWIFT_SOURCE.is_file():
        return None

    MACOS_APP_BINARY.parent.mkdir(parents=True, exist_ok=True)
    if not MACOS_INFO_PLIST.is_file():
        MACOS_INFO_PLIST.write_text(MACOS_PLIST_CONTENT, encoding="utf-8")

    needs_build = not MACOS_APP_BINARY.is_file()
    if not needs_build:
        try:
            needs_build = MACOS_SWIFT_SOURCE.stat().st_mtime > MACOS_APP_BINARY.stat().st_mtime
        except OSError:
            needs_build = True

    if needs_build:
        swiftc = "/usr/bin/swiftc"
        if not os.path.isfile(swiftc):
            return None
        print("Kompiliere native macOS-App (FiveQThoughts.app)...")
        proc = subprocess.run(
            [swiftc, "-O", str(MACOS_SWIFT_SOURCE), "-o", str(MACOS_APP_BINARY)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"Warnung: Native macOS-App konnte nicht kompiliert werden: {proc.stderr}")
            return None

    return MACOS_APP_BINARY if MACOS_APP_BINARY.is_file() else None


def start_windows_global_hotkey(url: str):
    """Register global hotkey Ctrl+Alt+Q on Windows to toggle or summon FiveQThoughts."""
    if platform.system() != "Windows":
        return

    def _hotkey_loop():
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            MOD_ALT = 0x0001
            MOD_CONTROL = 0x0002
            MOD_NOREPEAT = 0x4000
            VK_Q = 0x51
            WM_HOTKEY = 0x0312
            SW_RESTORE = 9
            SW_MINIMIZE = 6
            HOTKEY_ID = 1

            if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_Q):
                return

            print("Globaler Shortcut aktiv: Ctrl+Alt+Q (Fenster ein-/ausblenden)")

            def _toggle_or_open():
                matched_hwnd = []

                WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                def _enum_cb(hwnd, lparam):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buf = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buf, length + 1)
                            if "FiveQThoughts" in buf.value:
                                matched_hwnd.append(hwnd)
                                return False
                    return True

                user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
                if matched_hwnd:
                    hwnd = matched_hwnd[0]
                    fg = user32.GetForegroundWindow()
                    if fg == hwnd and not user32.IsIconic(hwnd):
                        user32.ShowWindow(hwnd, SW_MINIMIZE)
                    else:
                        user32.ShowWindow(hwnd, SW_RESTORE)
                        user32.SetForegroundWindow(hwnd)
                else:
                    open_browser_app_window(url)

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    _toggle_or_open()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass

    t = threading.Thread(target=_hotkey_loop, daemon=True)
    t.start()


def open_browser_app_window(url: str):
    """Fallback: Open the UI in a compact chromeless app window (Edge/Chrome/Brave) or default browser."""
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
                    os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                    os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
                ]
            )

    for binary in candidates:
        if os.path.isfile(binary):
            try:
                subprocess.Popen(
                    [binary, f"--app={url}", "--window-size=1180,860"],
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
    parser.add_argument("--no-browser", action="store_true", help="Do not open window automatically")
    parser.add_argument("--browser-mode", action="store_true", help="Force browser mode instead of native macOS window")
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

    # Native macOS standalone app mode (own ⌘+Tab entry, Menu Bar ⚡5Q, global hotkey ⌃⌥Q)
    if not args.no_browser and not args.browser_mode and platform.system() == "Darwin":
        native_bin = ensure_macos_native_app()
        if native_bin:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            print("Starte eigenständige macOS-App FiveQThoughts (Globaler Shortcut: ⌃⌥Q)...")
            native_proc = subprocess.Popen([str(native_bin), "--url", url])
            try:
                native_proc.wait()
            except KeyboardInterrupt:
                native_proc.terminate()
            finally:
                print("\nFiveQThoughts beendet.")
                server.shutdown()
                server.server_close()
            return

    if not args.no_browser:
        if platform.system() == "Windows":
            start_windows_global_hotkey(url)
        threading.Timer(0.4, open_browser_app_window, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFiveQThoughts beendet.")
        server.server_close()


if __name__ == "__main__":
    main()
