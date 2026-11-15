from __future__ import annotations

import hashlib
import fnmatch
from html.parser import HTMLParser
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit
from zipfile import ZipFile
from xml.etree import ElementTree

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db
from .config import data_dir, settings
from .models import AgentChangeBatch, AuditLog, CapabilityEvidence, CapabilityProfile, DailyLog, DailyLogReview, ReviewCard, StudyTask, utcnow
from .model_routing import router as model_router
from .notes_models import KnowledgeTopic, Note

ALLOWED_EXTENSIONS = frozenset({
    ".md", ".txt", ".pdf", ".docx", ".json", ".yaml", ".yml", ".csv", ".html", ".htm", ".rst",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".cc", ".cxx", ".sql",
    ".gd", ".go", ".cs", ".css", ".sh", ".ps1",
})
TEXT_EXTENSIONS = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".rst", ".py", ".ts", ".tsx", ".js", ".jsx",
    ".css", ".sql", ".go", ".java", ".cs", ".c", ".h", ".cpp", ".cc", ".cxx", ".gd", ".sh", ".ps1",
})
EXCLUDED_DIRECTORIES = frozenset({".git", "node_modules", ".venv", ".env"})
SECRET_NAMES = frozenset({".env", ".env.local", ".env.production", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".secret")
CLOUD_ANALYSIS_CONTENT_LIMIT = 120_000
WEB_CONTENT_LIMIT = 5 * 1024 * 1024
WEB_REDIRECT_LIMIT = 3


class ApplicationState(Base):
    __tablename__ = "application_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


SCAN_JOBS: dict[str, dict[str, Any]] = {}
SCAN_JOBS_LOCK = threading.Lock()
SCAN_DIRECTORY_LOCKS: dict[int, threading.Lock] = {}


class ScanCancelled(Exception):
    """Raised inside a scan when the persisted job has been cancelled."""


class FileChangeAlert(Base):
    __tablename__ = "file_change_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    directory_id: Mapped[int] = mapped_column(ForeignKey("authorized_directories.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    change_type: Mapped[str] = mapped_column(String(20))
    old_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthorizedDirectory(Base):
    __tablename__ = "authorized_directories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(1024), unique=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    local_analysis: Mapped[bool] = mapped_column(Boolean, default=True)
    cloud_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    write_access: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_extensions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    allowed_extensions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    excluded_patterns: Mapped[list[Any]] = mapped_column(JSON, default=list)
    authorized_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scanned_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scan_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileImport(Base):
    __tablename__ = "file_imports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    directory_id: Mapped[int] = mapped_column(ForeignKey("authorized_directories.id", ondelete="CASCADE"))
    files: Mapped[list[Any]] = mapped_column(JSON, default=list)
    excluded: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportedFile(Base):
    __tablename__ = "imported_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("file_imports.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    original_path: Mapped[str] = mapped_column(String(2048))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_status: Mapped[str] = mapped_column(String(40), default="metadata_only")
    # Deprecated compatibility column. New imports keep正文 in content_file_path instead.
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    content_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    index_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_status: Mapped[str] = mapped_column(String(40), default="missing")
    last_verified_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    imported_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileAnalysis(Base):
    __tablename__ = "file_analyses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_file_id: Mapped[int] = mapped_column(ForeignKey("imported_files.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40), default="ollama")
    model_name: Mapped[str] = mapped_column(String(160), default="")
    analysis_version: Mapped[str] = mapped_column(String(40), default="v1")
    status: Mapped[str] = mapped_column(String(40), default="pending_confirmation")
    # Deprecated compatibility column. New analysis results are stored as JSON files.
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebResource(Base):
    __tablename__ = "web_resources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048))
    final_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(500), default="")
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_status: Mapped[str] = mapped_column(String(40), default="metadata_only")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    content_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    index_file_path: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_status: Mapped[str] = mapped_column(String(40), default="missing")
    fetched_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileWriteBatch(Base):
    __tablename__ = "file_write_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    directory_id: Mapped[int] = mapped_column(ForeignKey("authorized_directories.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(String(1024))
    before_exists: Mapped[bool] = mapped_column(Boolean, default=False)
    before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="written")
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), default=utcnow)
    reverted_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthorizedDirectoryCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    label: str = Field(default="", max_length=200)
    local_analysis: bool = True
    cloud_transfer: bool = False
    write_access: bool = False
    excluded_extensions: list[str] = Field(default_factory=list)
    allowed_extensions: list[str] = Field(default_factory=list)
    excluded_patterns: list[str] = Field(default_factory=list)

    @field_validator("excluded_extensions")
    @classmethod
    def normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for extension in value:
            extension = extension.strip().lower()
            if not extension.startswith("."):
                extension = "." + extension
            if len(extension) > 32 or "/" in extension or "\\" in extension or extension == ".":
                raise ValueError("扩展名格式无效")
            if extension not in normalized:
                normalized.append(extension)
        return normalized

    @field_validator("allowed_extensions")
    @classmethod
    def normalize_allowed_extensions(cls, value: list[str]) -> list[str]:
        return cls.normalize_extensions(value)

    @field_validator("excluded_patterns")
    @classmethod
    def normalize_patterns(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for pattern in value:
            pattern = pattern.strip().replace("\\", "/")
            if not pattern or pattern.startswith("/") or ".." in Path(pattern).parts or len(pattern) > 240:
                raise ValueError("排除模式格式无效")
            if pattern not in normalized:
                normalized.append(pattern)
        return normalized


class ImportPermissionUpdate(BaseModel):
    local_analysis: bool | None = None
    cloud_transfer: bool | None = None
    write_access: bool | None = None
    excluded_extensions: list[str] | None = None
    allowed_extensions: list[str] | None = None
    excluded_patterns: list[str] | None = None

    @field_validator("excluded_extensions")
    @classmethod
    def normalize_optional_extensions(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return AuthorizedDirectoryCreate.normalize_extensions(value)

    @field_validator("allowed_extensions")
    @classmethod
    def normalize_optional_allowed_extensions(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else AuthorizedDirectoryCreate.normalize_extensions(value)

    @field_validator("excluded_patterns")
    @classmethod
    def normalize_optional_patterns(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else AuthorizedDirectoryCreate.normalize_patterns(value)


class DirectoryFileWrite(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(max_length=2 * 1024 * 1024)
    confirmed: bool = False


class DirectoryCloudAnalysis(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    prompt: str = Field(min_length=1, max_length=20000)
    confirmed: bool = False


class WebImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class WebImportConfirmRequest(BaseModel):
    confirmed: bool = False


class AuthorizedDirectoryRead(AuthorizedDirectoryCreate):
    id: int
    active: bool
    local_analysis: bool
    cloud_transfer: bool
    write_access: bool
    excluded_extensions: list[str]
    allowed_extensions: list[str]
    excluded_patterns: list[str]
    authorized_at: Any
    revoked_at: Any | None
    last_scanned_at: Any | None
    scan_enabled: bool
    model_config = {"from_attributes": True}


class DirectoryScanUpdate(BaseModel):
    scan_enabled: bool


def _safe_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise HTTPException(status_code=400, detail="授权目录必须是绝对路径")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise HTTPException(status_code=400, detail="目录不存在或不可访问")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="授权路径必须是目录")
    return resolved


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    return name in SECRET_NAMES or name.endswith(SECRET_SUFFIXES) or (name.startswith(".env") and name != ".env.example")


class _ReadableHtmlParser(HTMLParser):
    _ignored_tags = frozenset({"head", "script", "style", "noscript", "template", "svg"})
    _block_tags = frozenset({"address", "article", "aside", "blockquote", "dd", "div", "dl", "dt", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag in self._ignored_tags:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "br" or tag in self._block_tags:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() in self._ignored_tags:
            self._ignored_depth = max(0, self._ignored_depth - 1)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag in self._ignored_tags:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if not self._ignored_depth and tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = []
        for line in "".join(self.parts).splitlines():
            normalized = re.sub(r"[ \t]+", " ", line).strip()
            if normalized:
                lines.append(normalized)
        return "\n".join(lines).strip()

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.title_parts)).strip()[:500]


def _extract_html_text(path: Path) -> tuple[str | None, str]:
    try:
        parser = _ReadableHtmlParser()
        parser.feed(path.read_text(encoding="utf-8"))
        parser.close()
        text = parser.text()
        return text, "imported" if text else "empty"
    except (OSError, UnicodeDecodeError):
        return None, "unreadable_html"


def _parse_html_payload(raw: bytes, content_type: str = "") -> tuple[str, str, str]:
    charset_match = re.search(r"charset=([\w-]+)", content_type, flags=re.IGNORECASE)
    encoding = charset_match.group(1) if charset_match else "utf-8"
    try:
        source = raw.decode(encoding, errors="replace")
    except LookupError:
        source = raw.decode("utf-8", errors="replace")
    parser = _ReadableHtmlParser()
    parser.feed(source)
    parser.close()
    content = parser.text()
    return parser.title, content, "imported" if content else "empty"


def _validate_web_url(raw_url: str) -> str:
    try:
        parsed = urlsplit(raw_url.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="网页地址格式无效") from exc
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="仅支持不含账号信息的 HTTP/HTTPS 公网页面")
    if port is not None and not (1 <= port <= 65535):
        raise HTTPException(status_code=400, detail="网页端口无效")
    try:
        addresses = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="网页地址无法解析") from exc
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise HTTPException(status_code=400, detail="网页地址必须指向公网上的主机")
    return raw_url.strip()


def _fetch_web_page(raw_url: str) -> dict[str, Any]:
    current_url = _validate_web_url(raw_url)
    for _ in range(WEB_REDIRECT_LIMIT + 1):
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False, headers={"User-Agent": "LearningWorkstation/0.1"}) as client:
                with client.stream("GET", current_url) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(status_code=502, detail="网页重定向缺少目标地址")
                        current_url = _validate_web_url(urljoin(current_url, location))
                        continue
                    if response.status_code >= 400:
                        raise HTTPException(status_code=502, detail=f"网页请求失败（HTTP {response.status_code}）")
                    declared_length = response.headers.get("content-length")
                    try:
                        declared_size = int(declared_length) if declared_length else None
                    except ValueError:
                        declared_size = None
                    if declared_size is not None and declared_size > WEB_CONTENT_LIMIT:
                        raise HTTPException(status_code=413, detail="网页正文超过 5 MB 限制")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > WEB_CONTENT_LIMIT:
                            raise HTTPException(status_code=413, detail="网页正文超过 5 MB 限制")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    content_type = response.headers.get("content-type", "").lower()
        except HTTPException:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=502, detail="网页请求失败，请检查网络或稍后重试") from exc
        if content_type and not any(kind in content_type for kind in ("text/html", "application/xhtml+xml", "text/plain")):
            raise HTTPException(status_code=415, detail="网页响应不是可解析的 HTML 或纯文本")
        if "text/plain" in content_type:
            charset_match = re.search(r"charset=([\w-]+)", content_type, flags=re.IGNORECASE)
            encoding = charset_match.group(1) if charset_match else "utf-8"
            try:
                content = raw.decode(encoding, errors="replace").strip()
            except LookupError:
                content = raw.decode("utf-8", errors="replace").strip()
            title = urlsplit(current_url).path.rsplit("/", 1)[-1] or urlsplit(current_url).hostname or current_url
            status_value = "imported" if content else "empty"
        else:
            title, content, status_value = _parse_html_payload(raw, content_type)
            title = title or urlsplit(current_url).path.rsplit("/", 1)[-1] or urlsplit(current_url).hostname or current_url
        return {"url": raw_url.strip(), "final_url": current_url, "title": title, "mime_type": content_type or "text/html", "raw": raw, "content": content, "content_status": status_value}
    raise HTTPException(status_code=502, detail="网页重定向次数超过限制")


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_text(element: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        name = _xml_local_name(node.tag)
        if name == "t":
            parts.append(node.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name == "br":
            parts.append("\n")
    return re.sub(r" +", " ", "".join(parts)).strip()


def _extract_docx_text(path: Path) -> tuple[str | None, str]:
    try:
        with ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        body = next((node for node in root.iter() if _xml_local_name(node.tag) == "body"), None)
        if body is None:
            return "", "empty"
        lines: list[str] = []
        for child in body:
            name = _xml_local_name(child.tag)
            if name == "p":
                text = _docx_text(child)
                if text:
                    lines.append(text)
            elif name == "tbl":
                rows: list[list[str]] = []
                for row in child:
                    if _xml_local_name(row.tag) != "tr":
                        continue
                    cells: list[str] = []
                    for cell in row:
                        if _xml_local_name(cell.tag) == "tc":
                            cells.append(_docx_text(cell))
                    if any(cells):
                        rows.append(cells)
                if rows:
                    lines.append("| " + " | ".join(rows[0]) + " |")
                    lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
                    for row in rows[1:]:
                        padded = row + [""] * (len(rows[0]) - len(row))
                        lines.append("| " + " | ".join(padded[: len(rows[0])]) + " |")
        text = "\n".join(lines).strip()
        return text, "imported" if text else "empty"
    except (KeyError, OSError, ElementTree.ParseError):
        return None, "unreadable_document"


def _extract_document_text(path: Path) -> tuple[str | None, str]:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
            return text, "imported" if text.strip() else "empty"
        except ImportError:
            return None, "metadata_only"
        except Exception:
            return None, "metadata_only"
    if path.suffix.lower() == ".docx":
        return _extract_docx_text(path)
    if path.suffix.lower() in {".html", ".htm"}:
        return _extract_html_text(path)
    return None, "metadata_only"


STORAGE_LAYERS = ("raw", "content", "index", "analysis", "web_raw", "web_content", "web_index")


def _storage_root() -> Path:
    root = data_dir() / "imports"
    for layer in STORAGE_LAYERS:
        (root / layer).mkdir(parents=True, exist_ok=True)
    return root


def _storage_relative(layer: str, import_id: int, row_id: int, suffix: str) -> str:
    if layer not in STORAGE_LAYERS:
        raise ValueError("unknown storage layer")
    return f"imports/{layer}/{import_id}/{row_id}{suffix}"


def _storage_path(relative_path: str) -> Path:
    root = data_dir().resolve() / "imports"
    candidate = (data_dir().resolve() / relative_path).resolve()
    candidate.relative_to(root)
    return candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    return _write_bytes(path, encoded)


def _read_imported_content(item: ImportedFile) -> str:
    if item.content_file_path:
        try:
            return _storage_path(item.content_file_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            return ""
    return item.content or ""


def _read_web_content(item: WebResource) -> str:
    if not item.content_file_path:
        return ""
    try:
        return _storage_path(item.content_file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        return ""


def _source_file(db: Session, item: ImportedFile) -> Path | None:
    record = db.get(FileImport, item.import_id)
    directory = db.get(AuthorizedDirectory, record.directory_id) if record else None
    if not directory:
        return None
    try:
        root = Path(directory.path).resolve(strict=True)
        candidate = (root / item.relative_path).resolve(strict=True)
        candidate.relative_to(root)
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def _check_file_integrity(db: Session, item: ImportedFile) -> dict[str, Any]:
    source = _source_file(db, item)
    raw_path = _storage_path(item.raw_file_path) if item.raw_file_path else None
    content_path = _storage_path(item.content_file_path) if item.content_file_path else None
    index_path = _storage_path(item.index_file_path) if item.index_file_path else None
    source_exists = source is not None and source.exists()
    raw_exists = raw_path is not None and raw_path.exists()
    content_exists = content_path is not None and content_path.exists()
    index_exists = index_path is not None and index_path.exists()
    source_sha = _sha256_file(source) if source_exists else None
    raw_sha = _sha256_file(raw_path) if raw_exists else None
    content_sha = _sha256_file(content_path) if content_exists else None
    index_sha = _sha256_file(index_path) if index_exists else None
    source_changed = bool(source_sha and source_sha != item.sha256)
    content_valid = not item.content_sha256 or content_sha == item.content_sha256
    index_valid = bool(index_exists and (not item.index_sha256 or index_sha == item.index_sha256))
    status = "healthy"
    if not source_exists or not raw_exists or (item.content_file_path and not content_exists) or not index_exists:
        status = "missing"
    elif source_changed or raw_sha != item.sha256 or not content_valid or not index_valid:
        status = "stale"
    return {
        "imported_file_id": item.id,
        "import_id": item.import_id,
        "relative_path": item.relative_path,
        "status": status,
        "source_exists": source_exists,
        "raw_exists": raw_exists,
        "content_exists": content_exists,
        "index_exists": index_exists,
        "source_changed": source_changed,
        "raw_hash_matches": raw_sha == item.sha256 if raw_sha else False,
        "content_hash_matches": content_valid,
        "index_hash_matches": index_valid,
        "last_verified_at": utcnow().isoformat(),
    }


def _check_web_integrity(item: WebResource) -> dict[str, Any]:
    raw_path = _storage_path(item.raw_file_path) if item.raw_file_path else None
    content_path = _storage_path(item.content_file_path) if item.content_file_path else None
    index_path = _storage_path(item.index_file_path) if item.index_file_path else None
    raw_exists = raw_path is not None and raw_path.exists()
    content_exists = content_path is not None and content_path.exists()
    index_exists = index_path is not None and index_path.exists()
    raw_sha = _sha256_file(raw_path) if raw_exists else None
    content_sha = _sha256_file(content_path) if content_exists else None
    index_sha = _sha256_file(index_path) if index_exists else None
    content_valid = not item.content_sha256 or content_sha == item.content_sha256
    index_valid = bool(index_exists and (not item.index_sha256 or index_sha == item.index_sha256))
    state = "healthy"
    if not raw_exists or not content_exists or not index_exists:
        state = "missing"
    elif raw_sha != item.sha256 or not content_valid or not index_valid:
        state = "stale"
    return {"resource_id": item.id, "url": item.url, "status": state, "raw_exists": raw_exists, "content_exists": content_exists, "index_exists": index_exists, "raw_hash_matches": raw_sha == item.sha256 if raw_sha else False, "content_hash_matches": content_valid, "index_hash_matches": index_valid}


def _extract_cloud_content(path: Path) -> str:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="当前文件不是可读取的 UTF-8 文本") from exc
    if path.suffix.lower() in {".pdf", ".docx", ".html", ".htm"}:
        content, content_status = _extract_document_text(path)
        if content_status not in {"imported", "empty"} or content is None:
            raise HTTPException(status_code=400, detail="当前 PDF/DOCX 无法提取可分析正文")
        return content
    raise HTTPException(status_code=400, detail="当前文件类型不支持正文分析")


def _prepare_cloud_analysis_prompt(prompt: str, content: str) -> tuple[str, int]:
    from .model_routing import redact_sensitive

    safe_prompt = redact_sensitive(prompt).strip()
    safe_content = redact_sensitive(content)
    if len(safe_content) > CLOUD_ANALYSIS_CONTENT_LIMIT:
        safe_content = safe_content[:CLOUD_ANALYSIS_CONTENT_LIMIT] + "\n[正文已按云端分析上限裁剪]"
    outbound = f"分析要求：{safe_prompt}\n\n文件正文（已脱敏，最多 {CLOUD_ANALYSIS_CONTENT_LIMIT} 字符）：\n{safe_content}"
    return outbound, len(safe_content)


def _persist_import_layers(root: Path, record_id: int, imported: ImportedFile, file_item: dict[str, Any]) -> None:
    """Persist raw/content/index outside SQLite; paths are always data-dir relative."""
    _storage_root()
    source = (root / file_item["relative_path"]).resolve(strict=True)
    raw_relative = _storage_relative("raw", record_id, imported.id, source.suffix.lower() or ".bin")
    raw_path = _storage_path(raw_relative)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, raw_path)
    imported.raw_file_path = raw_relative

    content = file_item.get("content")
    if content is not None:
        content_relative = _storage_relative("content", record_id, imported.id, ".txt")
        content_path = _storage_path(content_relative)
        imported.content_file_path = content_relative
        imported.content_sha256 = _write_bytes(content_path, content.encode("utf-8"))
    index_relative = _storage_relative("index", record_id, imported.id, ".json")
    index_path = _storage_path(index_relative)
    imported.index_file_path = index_relative
    imported.index_sha256 = _write_json(index_path, {
        "imported_file_id": imported.id,
        "relative_path": imported.relative_path,
        "source_sha256": imported.sha256,
        "content_sha256": imported.content_sha256,
        "content_status": imported.content_status,
        "content_file_path": imported.content_file_path,
    })
    imported.index_status = "valid"


def _matches_excluded_pattern(relative_path: Path, patterns: list[str] | None) -> bool:
    normalized = relative_path.as_posix()
    return any(fnmatch.fnmatch(normalized, pattern) or any(fnmatch.fnmatch(part, pattern) for part in relative_path.parts) for pattern in (patterns or []))


def _scan(root: Path, target: Path | None = None, excluded_extensions: list[str] | None = None, allowed_extensions: list[str] | None = None, excluded_patterns: list[str] | None = None, progress_callback: Callable[[int, int], None] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    files: list[dict[str, Any]] = []
    excluded = {"unsupported_extension": 0, "secret": 0, "excluded_directory": 0, "excluded_pattern": 0, "unreadable": 0}
    candidates: list[Path] = []
    allowed = set(allowed_extensions) if allowed_extensions else ALLOWED_EXTENSIONS
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        relative_current = Path(current).relative_to(root)
        excluded_pattern_dirs = [d for d in dirs if _matches_excluded_pattern(relative_current / d, excluded_patterns)]
        excluded["excluded_pattern"] += len(excluded_pattern_dirs)
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRECTORIES and d not in excluded_pattern_dirs]
        excluded["excluded_directory"] += sum(1 for d in os.listdir(current) if (Path(current) / d).is_dir() and d in EXCLUDED_DIRECTORIES)
        for name in names:
            path = Path(current) / name
            if target is not None and path.resolve() != target:
                continue
            candidates.append(path)
    total = len(candidates)
    for index, path in enumerate(candidates, start=1):
        if _is_secret(path):
            excluded["secret"] += 1
            if progress_callback:
                progress_callback(index, total)
            continue
        if _matches_excluded_pattern(path.relative_to(root), excluded_patterns):
            excluded["excluded_pattern"] += 1
            if progress_callback:
                progress_callback(index, total)
            continue
        if path.suffix.lower() not in allowed or path.suffix.lower() in set(excluded_extensions or []):
            excluded["unsupported_extension"] += 1
            if progress_callback:
                progress_callback(index, total)
            continue
        try:
            real = path.resolve(strict=True)
            real.relative_to(root)
            digest = hashlib.sha256()
            with real.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            item = {"relative_path": real.relative_to(root).as_posix(), "size": real.stat().st_size, "sha256": digest.hexdigest(), "content_status": "metadata_only", "content": None, "mime_type": mimetypes.guess_type(real.name)[0]}
            if real.stat().st_size <= 2 * 1024 * 1024:
                if real.suffix.lower() in TEXT_EXTENSIONS:
                    try:
                        item["content"] = real.read_text(encoding="utf-8")
                        item["content_status"] = "imported"
                    except UnicodeDecodeError:
                        item["content_status"] = "unreadable_text"
                elif real.suffix.lower() in {".pdf", ".docx", ".html", ".htm"}:
                    item["content"], item["content_status"] = _extract_document_text(real)
            files.append(item)
        except (OSError, ValueError):
            excluded["unreadable"] += 1
        if progress_callback:
            progress_callback(index, total)
    return files, excluded


def _scan_single_file(root: Path, target: Path, excluded_extensions: list[str] | None = None, allowed_extensions: list[str] | None = None, excluded_patterns: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    files: list[dict[str, Any]] = []
    excluded = {"unsupported_extension": 0, "secret": 0, "excluded_directory": 0, "excluded_pattern": 0, "unreadable": 0}
    if _is_secret(target):
        excluded["secret"] = 1
        return files, excluded
    relative_target = target.resolve().relative_to(root.resolve())
    if _matches_excluded_pattern(relative_target, excluded_patterns):
        excluded["excluded_pattern"] = 1
        return files, excluded
    allowed = set(allowed_extensions) if allowed_extensions else ALLOWED_EXTENSIONS
    if target.suffix.lower() not in allowed or target.suffix.lower() in set(excluded_extensions or []):
        excluded["unsupported_extension"] = 1
        return files, excluded
    try:
        real = target.resolve(strict=True)
        real.relative_to(root)
        digest = hashlib.sha256()
        with real.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        item = {"relative_path": real.relative_to(root).as_posix(), "size": real.stat().st_size, "sha256": digest.hexdigest(), "content_status": "metadata_only", "content": None, "mime_type": mimetypes.guess_type(real.name)[0]}
        if real.stat().st_size <= 2 * 1024 * 1024:
            if real.suffix.lower() in TEXT_EXTENSIONS:
                try:
                    item["content"] = real.read_text(encoding="utf-8")
                    item["content_status"] = "imported"
                except UnicodeDecodeError:
                    item["content_status"] = "unreadable_text"
            elif real.suffix.lower() in {".pdf", ".docx", ".html", ".htm"}:
                item["content"], item["content_status"] = _extract_document_text(real)
        files.append(item)
    except (OSError, ValueError):
        excluded["unreadable"] = 1
    return files, excluded


def _get_active(db: Session, directory_id: int) -> AuthorizedDirectory:
    item = db.get(AuthorizedDirectory, directory_id)
    if not item or not item.active:
        raise HTTPException(status_code=403, detail="授权目录不存在或已撤销")
    return item


def _scan_snapshot(root: Path, excluded_extensions: list[str] | None = None, allowed_extensions: list[str] | None = None, excluded_patterns: list[str] | None = None) -> dict[str, str]:
    files, _ = _scan(root, excluded_extensions=excluded_extensions, allowed_extensions=allowed_extensions, excluded_patterns=excluded_patterns)
    return {item["relative_path"]: item["sha256"] for item in files}


def _record_file_changes(db: Session, directory: AuthorizedDirectory, before: dict[str, str], after: dict[str, str]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for relative_path in sorted(set(before) | set(after)):
        old_sha = before.get(relative_path)
        new_sha = after.get(relative_path)
        if old_sha == new_sha:
            continue
        change_type = "added" if old_sha is None else ("deleted" if new_sha is None else "modified")
        existing = db.scalar(select(FileChangeAlert).where(
            FileChangeAlert.directory_id == directory.id,
            FileChangeAlert.relative_path == relative_path,
            FileChangeAlert.change_type == change_type,
            FileChangeAlert.old_sha256 == old_sha,
            FileChangeAlert.new_sha256 == new_sha,
            FileChangeAlert.acknowledged_at.is_(None),
        ))
        if existing is None:
            db.add(FileChangeAlert(directory_id=directory.id, relative_path=relative_path, change_type=change_type, old_sha256=old_sha, new_sha256=new_sha))
        changes.append({"relative_path": relative_path, "change_type": change_type, "old_sha256": old_sha, "new_sha256": new_sha})
    return changes


def _get_authorized_file(item: AuthorizedDirectory, relative_path: str, *, require_supported: bool = False) -> Path:
    root = Path(item.path).resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径超出授权目录") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="目标路径不是文件")
    if _is_secret(candidate):
        raise HTTPException(status_code=403, detail="敏感文件禁止访问")
    relative_candidate = candidate.relative_to(root)
    allowed = set(item.allowed_extensions or ALLOWED_EXTENSIONS)
    if require_supported and candidate.suffix.lower() not in allowed:
        raise HTTPException(status_code=400, detail="文件扩展名不在导入白名单中")
    if candidate.suffix.lower() in set(item.excluded_extensions or []):
        raise HTTPException(status_code=403, detail="该扩展名已被授权目录排除")
    if _matches_excluded_pattern(relative_candidate, item.excluded_patterns):
        raise HTTPException(status_code=403, detail="该路径被授权目录排除模式禁止")
    return candidate


router = APIRouter()

@router.post("/authorized-directories", response_model=AuthorizedDirectoryRead, status_code=status.HTTP_201_CREATED)
def create_authorized_directory(payload: AuthorizedDirectoryCreate, db: Session = Depends(get_db)):
    path = _safe_path(payload.path)
    item = AuthorizedDirectory(
        path=str(path),
        label=payload.label,
        local_analysis=payload.local_analysis,
        cloud_transfer=payload.cloud_transfer,
        write_access=payload.write_access,
        excluded_extensions=payload.excluded_extensions,
        allowed_extensions=payload.allowed_extensions,
        excluded_patterns=payload.excluded_patterns,
        authorized_at=utcnow(),
        scan_enabled=True,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="该目录已经授权") from exc
    db.refresh(item)
    db.add(AuditLog(entity_type="authorized_directory", entity_id=item.id, action="authorize", before_data=None, after_data={"path": item.path, "label": item.label, "local_analysis": item.local_analysis, "cloud_transfer": item.cloud_transfer, "write_access": item.write_access, "excluded_extensions": item.excluded_extensions, "allowed_extensions": item.allowed_extensions, "excluded_patterns": item.excluded_patterns}))
    db.commit()
    return item

@router.get("/authorized-directories", response_model=list[AuthorizedDirectoryRead])
def list_authorized_directories(db: Session = Depends(get_db)):
    return list(db.scalars(select(AuthorizedDirectory).order_by(AuthorizedDirectory.id.desc())))

@router.patch("/authorized-directories/{directory_id}/permissions", response_model=AuthorizedDirectoryRead)
def update_directory_permissions(directory_id: int, payload: ImportPermissionUpdate, db: Session = Depends(get_db)):
    item = db.get(AuthorizedDirectory, directory_id)
    if not item:
        raise HTTPException(status_code=404, detail="授权目录不存在")
    if not item.active:
        raise HTTPException(status_code=403, detail="授权目录不存在或已撤销")
    before = {field: getattr(item, field) for field in ("local_analysis", "cloud_transfer", "write_access", "excluded_extensions", "allowed_extensions", "excluded_patterns")}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit(); db.refresh(item)
    after = {field: getattr(item, field) for field in before}
    db.add(AuditLog(entity_type="authorized_directory", entity_id=item.id, action="permissions_update", before_data=before, after_data=after))
    db.commit()
    return item

@router.patch("/authorized-directories/{directory_id}/scan-settings", response_model=AuthorizedDirectoryRead)
def update_directory_scan_settings(directory_id: int, payload: DirectoryScanUpdate, db: Session = Depends(get_db)):
    item = db.get(AuthorizedDirectory, directory_id)
    if not item:
        raise HTTPException(status_code=404, detail="授权目录不存在")
    if not item.active:
        raise HTTPException(status_code=403, detail="授权目录不存在或已撤销")
    before = {"scan_enabled": item.scan_enabled}
    item.scan_enabled = payload.scan_enabled
    db.commit(); db.refresh(item)
    db.add(AuditLog(entity_type="authorized_directory", entity_id=item.id, action="scan_settings_update", before_data=before, after_data={"scan_enabled": item.scan_enabled}))
    db.commit()
    return item

@router.delete("/authorized-directories/{directory_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_authorized_directory(directory_id: int, db: Session = Depends(get_db)):
    item = db.get(AuthorizedDirectory, directory_id)
    if not item: raise HTTPException(status_code=404, detail="授权目录不存在")
    if not item.active:
        return
    before = {"active": item.active, "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None}
    item.active = False
    item.scan_enabled = False
    item.revoked_at = utcnow()
    db.add(AuditLog(entity_type="authorized_directory", entity_id=item.id, action="revoke", before_data=before, after_data={"active": False, "scan_enabled": False, "revoked_at": item.revoked_at.isoformat()}))
    db.commit()

def _scan_job_snapshot(job_id: str, db: Session | None = None) -> dict[str, Any]:
    with SCAN_JOBS_LOCK:
        current = SCAN_JOBS.get(job_id)
    if current is not None:
        return dict(current)
    if db is not None:
        state = db.get(ApplicationState, f"scan_job:{job_id}")
        if state:
            return dict(state.value or {})
    return {"job_id": job_id, "status": "not_found"}


def _persist_scan_job(db: Session, job: dict[str, Any]) -> None:
    job = {**job, "updated_at": utcnow().isoformat()}
    state = db.get(ApplicationState, f"scan_job:{job['job_id']}")
    if state is None:
        state = ApplicationState(key=f"scan_job:{job['job_id']}", value=dict(job))
        db.add(state)
    else:
        state.value = dict(job)
        state.updated_at = utcnow()
    db.commit()


def _directory_scan_lock(directory_id: int) -> threading.Lock:
    with SCAN_JOBS_LOCK:
        return SCAN_DIRECTORY_LOCKS.setdefault(directory_id, threading.Lock())


def _scan_job_progress(job_id: str, processed: int, total: int) -> None:
    from .db import SessionLocal

    with SCAN_JOBS_LOCK:
        job = SCAN_JOBS.get(job_id)
        if not job:
            return
        if job.get("status") == "cancelled":
            raise ScanCancelled()
        next_progress = 5 if total <= 0 else min(95, 5 + round(processed / total * 90))
        if next_progress <= int(job.get("progress", 0)):
            return
        job["progress"] = next_progress
        snapshot = dict(job)
    with SessionLocal() as db:
        _persist_scan_job(db, snapshot)


def _run_scan_job(job_id: str, directory_id: int, payload: dict[str, str] | None) -> None:
    from .db import SessionLocal

    db = SessionLocal()
    directory_lock = _directory_scan_lock(directory_id)
    # Cancellation is cooperative: the previous worker may still be unwinding
    # after the API marks it cancelled. Let an immediate retry wait briefly
    # for that worker to release the directory lock instead of failing it.
    if not directory_lock.acquire(timeout=30):
        with SCAN_JOBS_LOCK:
            job = dict(SCAN_JOBS.get(job_id) or {})
            job.update({"status": "failed", "progress": 100, "error": "该目录已有扫描任务正在运行"})
            SCAN_JOBS[job_id] = job
        _persist_scan_job(db, job)
        db.close()
        return
    try:
        with SCAN_JOBS_LOCK:
            job = dict(SCAN_JOBS[job_id])
            if job.get("status") == "cancelled":
                _persist_scan_job(db, job)
                return
            job.update({"status": "running", "progress": 1, "attempts": int(job.get("attempts", 0)) + 1, "error": None})
            SCAN_JOBS[job_id] = job
        _persist_scan_job(db, job)
        result = _scan_authorized_directory(directory_id, payload, db, progress_callback=lambda processed, total: _scan_job_progress(job_id, processed, total))
        with SCAN_JOBS_LOCK:
            SCAN_JOBS[job_id].update({"status": "completed", "progress": 100, "result": result})
            job = dict(SCAN_JOBS[job_id])
        _persist_scan_job(db, job)
    except ScanCancelled:
        with SCAN_JOBS_LOCK:
            SCAN_JOBS[job_id].update({"status": "cancelled", "error": "用户取消扫描"})
            job = dict(SCAN_JOBS[job_id])
        _persist_scan_job(db, job)
    except Exception as exc:
        with SCAN_JOBS_LOCK:
            SCAN_JOBS[job_id].update({"status": "failed", "progress": 100, "error": str(exc)[:500]})
            job = dict(SCAN_JOBS[job_id])
        _persist_scan_job(db, job)
    finally:
        directory_lock.release()
        db.close()


def recover_scan_jobs() -> None:
    """Requeue jobs that were interrupted when the process stopped."""
    from .db import SessionLocal

    with SessionLocal() as db:
        states = list(db.scalars(select(ApplicationState).where(ApplicationState.key.like("scan_job:%"))))
        for state in states:
            job = dict(state.value or {})
            if job.get("status") not in {"queued", "running"}:
                continue
            if int(job.get("attempts", 0)) >= int(job.get("max_attempts", 3)):
                job.update({"status": "failed", "progress": 100, "error": "扫描任务达到最大重试次数"})
                _persist_scan_job(db, job)
                continue
            job.update({"status": "queued", "error": "服务重启后自动恢复"})
            with SCAN_JOBS_LOCK:
                SCAN_JOBS[job["job_id"]] = job
            _persist_scan_job(db, job)
            threading.Thread(target=_run_scan_job, args=(job["job_id"], int(job["directory_id"]), job.get("payload") or None), daemon=True).start()


@router.post("/authorized-directories/{directory_id}/scan")
def scan_authorized_directory(directory_id: int, payload: dict[str, str] | None = None, db: Session = Depends(get_db)):
    return _scan_authorized_directory(directory_id, payload, db)


def _scan_authorized_directory(directory_id: int, payload: dict[str, str] | None, db: Session, progress_callback: Callable[[int, int], None] | None = None):
    item = _get_active(db, directory_id)
    if not item.scan_enabled:
        raise HTTPException(status_code=403, detail="该授权目录已停用扫描")
    if not item.local_analysis:
        raise HTTPException(status_code=403, detail="该授权目录已禁止本地分析")
    root = Path(item.path).resolve(strict=True)
    candidate = None
    if payload and payload.get("path"):
        candidate = _get_authorized_file(item, payload["path"], require_supported=True)
    if candidate is not None:
        files, excluded = _scan_single_file(root, candidate, item.excluded_extensions, item.allowed_extensions, item.excluded_patterns)
        if progress_callback:
            progress_callback(1, 1)
    else:
        files, excluded = _scan(root, excluded_extensions=item.excluded_extensions, allowed_extensions=item.allowed_extensions, excluded_patterns=item.excluded_patterns, progress_callback=progress_callback)
    previous_record = db.scalar(select(FileImport).where(FileImport.directory_id == item.id).order_by(FileImport.id.desc()))
    previous_snapshot = {
        str(file_item.get("relative_path")): str(file_item.get("sha256"))
        for file_item in (previous_record.files if previous_record else [])
        if file_item.get("relative_path") and file_item.get("sha256")
    }
    current_snapshot = {str(file_item["relative_path"]): str(file_item["sha256"]) for file_item in files}
    changes = _record_file_changes(db, item, previous_snapshot, current_snapshot) if candidate is None and previous_record is not None else []
    metadata_files = [{key: value for key, value in file_item.items() if key != "content"} for file_item in files]
    record = FileImport(directory_id=item.id, files=metadata_files, excluded=excluded, files_scanned=len(files))
    db.add(record); db.flush()
    imported_rows: list[ImportedFile] = []
    for file_item in files:
        imported = ImportedFile(
            import_id=record.id,
            relative_path=file_item["relative_path"],
            # New rows never persist the user's absolute path in SQLite.
            original_path="",
            sha256=file_item["sha256"],
            size=file_item.get("size", 0),
            mime_type=file_item.get("mime_type"),
            content_status=file_item.get("content_status", "metadata_only"),
        )
        db.add(imported)
        db.flush()
        _persist_import_layers(root, record.id, imported, file_item)
        imported_rows.append(imported)
    item.last_scanned_at = utcnow()
    db.commit(); db.refresh(record)
    return {"import_id": record.id, "files_scanned": record.files_scanned, "files": files, "excluded": excluded, "changes": changes, "indexed_file_ids": [row.id for row in imported_rows]}


@router.post("/authorized-directories/{directory_id}/scan/jobs")
def start_scan_job(directory_id: int, payload: dict[str, str] | None = None, db: Session = Depends(get_db)):
    item = _get_active(db, directory_id)
    if not item.scan_enabled or not item.local_analysis:
        raise HTTPException(status_code=403, detail="该授权目录当前不可扫描")
    active_jobs = [state.value or {} for state in db.scalars(select(ApplicationState).where(ApplicationState.key.like("scan_job:%")))]
    if any(int(job.get("directory_id", -1)) == directory_id and job.get("status") in {"queued", "running"} for job in active_jobs):
        raise HTTPException(status_code=409, detail="该目录已有扫描任务排队或运行中")
    job_id = uuid.uuid4().hex
    job = {"job_id": job_id, "directory_id": directory_id, "status": "queued", "progress": 0, "attempts": 0, "max_attempts": 3, "payload": payload or {}, "error": None, "result": None, "created_at": utcnow().isoformat()}
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job_id] = job
    _persist_scan_job(db, job)
    threading.Thread(target=_run_scan_job, args=(job_id, directory_id, payload), daemon=True).start()
    return _scan_job_snapshot(job_id, db)


@router.get("/authorized-directories/{directory_id}/scan/jobs")
def list_scan_jobs(directory_id: int, limit: int = 20, db: Session = Depends(get_db)):
    if not db.get(AuthorizedDirectory, directory_id):
        raise HTTPException(status_code=404, detail="授权目录不存在")
    rows = [dict(state.value or {}) for state in db.scalars(select(ApplicationState).where(ApplicationState.key.like("scan_job:%")))]
    rows = [row for row in rows if int(row.get("directory_id", -1)) == directory_id]
    rows.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    return rows[: max(1, min(limit, 100))]


@router.get("/authorized-directories/{directory_id}/scan/jobs/{job_id}")
def get_scan_job(directory_id: int, job_id: str, db: Session = Depends(get_db)):
    job = _scan_job_snapshot(job_id, db)
    if job.get("directory_id") != directory_id:
        raise HTTPException(status_code=404, detail="扫描任务不存在")
    return job


@router.delete("/authorized-directories/{directory_id}/scan/jobs/{job_id}")
def cancel_scan_job(directory_id: int, job_id: str, db: Session = Depends(get_db)):
    job = _scan_job_snapshot(job_id, db)
    if job.get("directory_id") != directory_id or job.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="扫描任务不存在")
    if job.get("status") in {"completed", "failed", "cancelled"}:
        return job
    job["status"] = "cancelled"
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job_id] = dict(job)
    _persist_scan_job(db, job)
    return job


@router.post("/authorized-directories/{directory_id}/scan/jobs/{job_id}/retry")
def retry_scan_job(directory_id: int, job_id: str, db: Session = Depends(get_db)):
    job = _scan_job_snapshot(job_id, db)
    if job.get("directory_id") != directory_id or job.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="扫描任务不存在")
    if job.get("status") not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败或已取消的扫描任务可以重试")
    if int(job.get("attempts", 0)) >= int(job.get("max_attempts", 3)):
        raise HTTPException(status_code=409, detail="扫描任务已达到最大重试次数")
    job.update({"status": "queued", "progress": 0, "error": None, "result": None})
    with SCAN_JOBS_LOCK:
        SCAN_JOBS[job_id] = dict(job)
    _persist_scan_job(db, job)
    threading.Thread(target=_run_scan_job, args=(job_id, directory_id, job.get("payload") or None), daemon=True).start()
    return _scan_job_snapshot(job_id, db)


@router.get("/authorized-directories/{directory_id}/changes")
def list_directory_changes(directory_id: int, include_acknowledged: bool = False, db: Session = Depends(get_db)):
    item = db.get(AuthorizedDirectory, directory_id)
    if not item:
        raise HTTPException(status_code=404, detail="授权目录不存在")
    query = select(FileChangeAlert).where(FileChangeAlert.directory_id == directory_id).order_by(FileChangeAlert.detected_at.desc(), FileChangeAlert.id.desc())
    if not include_acknowledged:
        query = query.where(FileChangeAlert.acknowledged_at.is_(None))
    rows = list(db.scalars(query.limit(200)))
    return [{"id": row.id, "directory_id": row.directory_id, "relative_path": row.relative_path, "change_type": row.change_type, "old_sha256": row.old_sha256, "new_sha256": row.new_sha256, "detected_at": row.detected_at, "acknowledged_at": row.acknowledged_at} for row in rows]


@router.post("/authorized-directories/{directory_id}/changes/acknowledge")
def acknowledge_directory_changes(directory_id: int, db: Session = Depends(get_db)):
    item = db.get(AuthorizedDirectory, directory_id)
    if not item:
        raise HTTPException(status_code=404, detail="授权目录不存在")
    rows = list(db.scalars(select(FileChangeAlert).where(FileChangeAlert.directory_id == directory_id, FileChangeAlert.acknowledged_at.is_(None))))
    acknowledged_at = utcnow()
    for row in rows:
        row.acknowledged_at = acknowledged_at
    db.commit()
    return {"acknowledged": len(rows), "acknowledged_at": acknowledged_at}


@router.post("/authorized-directories/{directory_id}/write")
def write_authorized_file(directory_id: int, payload: DirectoryFileWrite, db: Session = Depends(get_db)):
    item = _get_active(db, directory_id)
    if not item.write_access:
        raise HTTPException(status_code=403, detail="该授权目录未开启写入权限")
    root = Path(item.path).resolve(strict=True)
    candidate = (root / payload.path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径超出授权目录") from exc
    relative_candidate = candidate.relative_to(root)
    allowed = set(item.allowed_extensions or ALLOWED_EXTENSIONS)
    if _is_secret(candidate) or candidate.suffix.lower() in set(item.excluded_extensions or []) or candidate.suffix.lower() not in allowed or _matches_excluded_pattern(relative_candidate, item.excluded_patterns):
        raise HTTPException(status_code=403, detail="目标文件类型被目录权限禁止")
    if candidate.exists() and not candidate.is_file():
        raise HTTPException(status_code=400, detail="目标路径不是文件")
    before_exists = candidate.exists()
    before_content = candidate.read_text(encoding="utf-8") if before_exists else None
    before_sha256 = _sha256_file(candidate) if before_exists else None
    after_sha256 = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    if not payload.confirmed:
        return {
            "executed": False,
            "requires_confirmation": True,
            "path": candidate.relative_to(root).as_posix(),
            "will_overwrite": before_exists,
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "before_bytes": len(before_content.encode("utf-8")) if before_content is not None else 0,
            "after_bytes": len(payload.content.encode("utf-8")),
        }
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(payload.content, encoding="utf-8")
    batch = FileWriteBatch(directory_id=item.id, relative_path=candidate.relative_to(root).as_posix(), before_exists=before_exists, before_sha256=before_sha256, before_content=before_content, after_sha256=after_sha256)
    db.add(batch)
    db.flush()
    db.add(AuditLog(entity_type="file_write", entity_id=batch.id, action="write", before_data={"path": batch.relative_path, "exists": before_exists, "sha256": before_sha256}, after_data={"path": batch.relative_path, "sha256": after_sha256, "bytes": len(payload.content.encode("utf-8"))}))
    db.commit()
    return {"executed": True, "written": True, "batch_id": batch.id, "path": batch.relative_path, "bytes": len(payload.content.encode("utf-8")), "sha256": after_sha256}


@router.post("/authorized-directories/{directory_id}/write-batches/{batch_id}/revert")
def revert_authorized_file_write(directory_id: int, batch_id: int, payload: dict[str, bool] | None = None, db: Session = Depends(get_db)):
    batch = db.get(FileWriteBatch, batch_id)
    if not batch or batch.directory_id != directory_id:
        raise HTTPException(status_code=404, detail="写入批次不存在")
    if batch.status == "reverted":
        return {"reverted": True, "batch_id": batch.id, "status": batch.status}
    if not bool((payload or {}).get("confirmed")):
        return {"executed": False, "requires_confirmation": True, "batch_id": batch.id, "path": batch.relative_path, "status": batch.status}
    directory = db.get(AuthorizedDirectory, directory_id)
    if not directory:
        raise HTTPException(status_code=404, detail="授权目录不存在")
    root = Path(directory.path).resolve(strict=True)
    candidate = (root / batch.relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径超出授权目录") from exc
    current_sha = _sha256_file(candidate) if candidate.exists() and candidate.is_file() else None
    if current_sha != batch.after_sha256:
        raise HTTPException(status_code=409, detail="写入后的文件已被修改，无法自动撤销")
    if batch.before_exists:
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(batch.before_content or "", encoding="utf-8")
    elif candidate.exists():
        candidate.unlink()
    batch.status = "reverted"
    batch.reverted_at = utcnow()
    db.add(AuditLog(entity_type="file_write", entity_id=batch.id, action="revert", before_data={"sha256": batch.after_sha256}, after_data={"sha256": batch.before_sha256, "exists": batch.before_exists}))
    db.commit()
    return {"executed": True, "reverted": True, "batch_id": batch.id, "status": batch.status}


@router.post("/authorized-directories/{directory_id}/cloud-analysis")
def cloud_analyze_authorized_file(directory_id: int, payload: DirectoryCloudAnalysis, db: Session = Depends(get_db)):
    item = _get_active(db, directory_id)
    if not item.cloud_transfer:
        raise HTTPException(status_code=403, detail="该授权目录未开启云端发送权限")
    if not payload.confirmed:
        from .model_routing import estimate_tokens
        candidate = _get_authorized_file(item, payload.path, require_supported=True)
        size = candidate.stat().st_size if candidate.exists() else 0
        return {"executed": False, "requires_confirmation": True, "path": payload.path, "size_bytes": size, "estimated_tokens": estimate_tokens(str(payload.prompt)) + estimate_tokens("文件正文") + min(size, CLOUD_ANALYSIS_CONTENT_LIMIT) // 3, "provider": "zhiapi", "model": settings.cloud_model_name, "content_limit": CLOUD_ANALYSIS_CONTENT_LIMIT, "warning": "确认后仅发送脱敏且按上限裁剪的文件正文，不发送原始绝对路径"}
    candidate = _get_authorized_file(item, payload.path, require_supported=True)
    if candidate.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过云端分析大小限制")
    content = _extract_cloud_content(candidate)
    outbound_prompt, sent_content_length = _prepare_cloud_analysis_prompt(payload.prompt, content)
    result = model_router.run_task("file_cloud_analysis", outbound_prompt, confirmed=True)
    return {"executed": True, "success": result.success, "provider": result.provider, "model_name": result.model_name, "response": result.text, "error": result.error, "route_reason": result.route_reason, "sent_content_length": sent_content_length, "content_limit": CLOUD_ANALYSIS_CONTENT_LIMIT}


def _suggest_web_topics(item: WebResource) -> list[str]:
    candidates = [item.title]
    content = _read_web_content(item)
    if content:
        candidates.extend(re.findall(r"(?m)^#{1,3}\s+(.+)$", content)[:8])
    result: list[str] = []
    for candidate in candidates:
        name = _clean_topic_name(candidate)
        if name and name.casefold() not in {existing.casefold() for existing in result}:
            result.append(name)
    return result[:8]


def _web_resource_response(item: WebResource) -> dict[str, Any]:
    return {
        "resource_id": item.id,
        "url": item.url,
        "final_url": item.final_url,
        "title": item.title,
        "sha256": item.sha256,
        "size": item.size,
        "mime_type": item.mime_type,
        "content_status": item.content_status,
        "content_length": len(_read_web_content(item)),
        "confirmed": item.confirmed_at is not None,
    }


@router.post("/imports/web")
def create_web_import(payload: WebImportRequest, db: Session = Depends(get_db)):
    fetched = _fetch_web_page(payload.url)
    raw = fetched["raw"]
    content = fetched["content"]
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    resource = WebResource(
        url=fetched["url"],
        final_url=fetched["final_url"],
        title=fetched["title"],
        sha256=raw_sha256,
        size=len(raw),
        mime_type=fetched["mime_type"],
        content_status=fetched["content_status"],
    )
    db.add(resource)
    db.flush()
    raw_relative = _storage_relative("web_raw", resource.id, resource.id, ".html")
    content_relative = _storage_relative("web_content", resource.id, resource.id, ".txt")
    index_relative = _storage_relative("web_index", resource.id, resource.id, ".json")
    resource.raw_file_path = raw_relative
    resource.content_file_path = content_relative
    resource.index_file_path = index_relative
    _write_bytes(_storage_path(raw_relative), raw)
    resource.content_sha256 = _write_bytes(_storage_path(content_relative), content.encode("utf-8"))
    resource.index_sha256 = _write_json(_storage_path(index_relative), {
        "resource_id": resource.id,
        "url": resource.url,
        "final_url": resource.final_url,
        "sha256": resource.sha256,
        "content_sha256": resource.content_sha256,
        "content_status": resource.content_status,
        "content_file_path": resource.content_file_path,
    })
    resource.index_status = "valid"
    db.commit()
    return {**_web_resource_response(resource), "requires_confirmation": True, "warning": "确认后才会创建知识主题和来源笔记；原始网页与解析正文已保存在本地。"}


@router.get("/imports/web")
def list_web_imports(limit: int = 50, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(WebResource).order_by(WebResource.created_at.desc(), WebResource.id.desc()).limit(max(1, min(limit, 200)))))
    return [_web_resource_response(item) for item in rows]


@router.post("/imports/web/{resource_id}/confirm")
def confirm_web_import(resource_id: int, payload: WebImportConfirmRequest, db: Session = Depends(get_db)):
    resource = db.get(WebResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="网页资料不存在")
    content = _read_web_content(resource)
    topics = _suggest_web_topics(resource)
    preview = [{
        "resource_id": resource.id,
        "source_path": resource.final_url,
        "title": resource.title,
        "suggested_topics": topics,
        "will_create_note": bool(content),
        "already_confirmed": resource.confirmed_at is not None,
    }]
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": True, "preview": preview}
    if resource.confirmed_at is not None:
        return {"executed": True, "reused": True, "resource_id": resource.id, "created_topics": 0, "created_notes": 0, "status": "confirmed"}

    topic_rows: list[KnowledgeTopic] = []
    created_topics = 0
    batch_entries: list[dict[str, Any]] = []
    for topic_name in topics:
        topic, created = _get_or_create_topic(db, topic_name, resource.final_url)
        created_topics += int(created)
        topic_rows.append(topic)
        if created:
            batch_entries.append({"entity_type": "knowledge_topic", "entity_id": topic.id, "before": None, "after": {"id": topic.id, "name": topic.name, "domain": topic.domain, "definition": topic.definition, "tags": topic.tags or [], "evidence": topic.evidence or []}, "created": True})
    note = None
    created_notes = 0
    if content:
        title = _clean_topic_name(resource.title) or resource.final_url
        note = db.scalar(select(Note).where(Note.source_path == resource.final_url, Note.title == title))
        if note is None:
            note = Note(title=title, content=content, summary=f"从网页导入：{resource.final_url}", tags=["imported", "web"], folder="Imported", source_path=resource.final_url, visibility="private", ai_review_status="indexed", linked_topic_ids=[topic.id for topic in topic_rows], status="draft")
            db.add(note)
            db.flush()
            created_notes = 1
            batch_entries.append({"entity_type": "note", "entity_id": note.id, "before": None, "after": {"id": note.id, "title": note.title, "content": note.content, "summary": note.summary, "tags": note.tags or [], "folder": note.folder, "source_path": note.source_path, "visibility": note.visibility, "ai_review_status": note.ai_review_status, "linked_topic_ids": note.linked_topic_ids or [], "status": note.status}, "created": True})
    resource.confirmed_at = utcnow()
    batch = AgentChangeBatch(operation="web_import_confirm", status="executed", changes=[{"resource_id": resource.id}], before_data=[{"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("before")} for entry in batch_entries], after_data=[{"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("after"), "created": True} for entry in batch_entries])
    db.add(batch)
    db.flush()
    db.add(AuditLog(entity_type="web_import", entity_id=resource.id, action="confirm", before_data=None, after_data={"batch_id": batch.id, "created_topics": created_topics, "created_notes": created_notes}))
    db.commit()
    return {"executed": True, "reused": False, "resource_id": resource.id, "batch_id": batch.id, "created_topics": created_topics, "created_notes": created_notes, "topic_ids": [topic.id for topic in topic_rows], "note_ids": [note.id] if note else [], "status": "confirmed"}


@router.delete("/imports/web/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_web_import(resource_id: int, db: Session = Depends(get_db)):
    resource = db.get(WebResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="网页资料不存在")
    db.delete(resource)
    db.commit()


@router.get("/imports/search")
def search_imported_content(q: str, db: Session = Depends(get_db)):
    needle = q.strip().casefold()
    if not needle:
        return {"matches": []}
    matches: list[dict[str, Any]] = []
    for item in db.scalars(select(ImportedFile).order_by(ImportedFile.id.desc())):
        content = _read_imported_content(item)
        if needle in content.casefold():
            matches.append({"import_id": item.import_id, "indexed_file_id": item.id, "relative_path": item.relative_path, "sha256": item.sha256, "content_status": item.content_status, "snippet": content[:500]})
    for item in db.scalars(select(WebResource).order_by(WebResource.id.desc())):
        content = _read_web_content(item)
        if needle in content.casefold():
            matches.append({"import_id": None, "indexed_file_id": None, "web_resource_id": item.id, "relative_path": item.title or item.final_url, "sha256": item.sha256, "content_status": item.content_status, "snippet": content[:500]})
    return {"matches": matches}


@router.get("/imports/{import_id}/files")
def list_imported_files(import_id: int, db: Session = Depends(get_db)):
    if not db.get(FileImport, import_id):
        raise HTTPException(status_code=404, detail="导入不存在")
    return [{"id": item.id, "import_id": item.import_id, "relative_path": item.relative_path, "sha256": item.sha256, "size": item.size, "mime_type": item.mime_type,         "content_status": item.content_status, "content_file_path": item.content_file_path, "index_status": item.index_status, "imported_at": item.imported_at} for item in db.scalars(select(ImportedFile).where(ImportedFile.import_id == import_id).order_by(ImportedFile.relative_path))]


def _clean_topic_name(value: str) -> str:
    value = re.sub(r"[`*_\[\]{}]", "", value).strip(" .-_")
    return re.sub(r"\s+", " ", value)[:160]


def _suggest_topics(item: ImportedFile) -> list[str]:
    candidates = [part.strip() for part in re.split(r"[\n,#，、]", Path(item.relative_path).stem) if part.strip()]
    content = _read_imported_content(item)
    if content:
        candidates.extend(re.findall(r"(?m)^#{1,3}\s+(.+)$", content)[:8])
    result: list[str] = []
    for candidate in candidates:
        name = _clean_topic_name(candidate)
        if name and name.casefold() not in {item.casefold() for item in result}:
            result.append(name)
    return result[:8]


def _deterministic_profile_draft(relative_paths: list[str]) -> dict[str, Any]:
    technology_by_extension = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".java": "Java",
        ".sql": "SQL", ".gd": "GDScript", ".cpp": "C++", ".c": "C",
    }
    skills = sorted({technology_by_extension[Path(relative_path).suffix.lower()] for relative_path in relative_paths if Path(relative_path).suffix.lower() in technology_by_extension})
    return {
        "confirmed_skills": [],
        "unverified_skills": skills,
        "weak_capabilities": [],
        "learning_preferences": [],
        "target_job_directions": [],
    }


@router.post("/imports/{import_id}/profile-draft")
def profile_draft(import_id: int, db: Session = Depends(get_db)):
    record = db.get(FileImport, import_id)
    if not record:
        raise HTTPException(status_code=404, detail="导入不存在")
    imported = list(db.scalars(select(ImportedFile).where(ImportedFile.import_id == import_id).order_by(ImportedFile.relative_path)))
    if not imported:
        raise HTTPException(status_code=422, detail="该导入记录没有可分析文件")
    relative_paths = [item.relative_path for item in imported]
    evidence = [{"relative_path": item.relative_path, "sha256": item.sha256} for item in imported[:80]]
    excerpts = []
    for item in imported[:30]:
        content = _read_imported_content(item)
        if content:
            excerpts.append(f"文件：{item.relative_path}\n{content[:1800]}")
    prompt = (
        "请为个人学习工作站生成画像草稿 JSON。只能从资料证据提出候选，不要断言用户已经掌握。"
        "字段必须包含 confirmed_skills、unverified_skills、weak_capabilities、learning_preferences、target_job_directions，均为字符串数组。"
        "confirmed_skills 默认谨慎为空；无法从资料判断的字段返回空数组。\n\n" + "\n\n".join(excerpts)
    )
    result = model_router.run_structured("file_index", prompt, {"confirmed_skills", "unverified_skills", "weak_capabilities", "learning_preferences", "target_job_directions"})
    if result.success and result.data:
        draft = {key: [str(value) for value in result.data.get(key, []) if str(value).strip()] for key in ("confirmed_skills", "unverified_skills", "weak_capabilities", "learning_preferences", "target_job_directions")}
        generation_mode = "local_model"
        provider = result.provider
        model_name = result.model_name
        confidence = result.confidence
    else:
        draft = _deterministic_profile_draft(relative_paths)
        generation_mode = "deterministic_fallback"
        provider = "deterministic"
        model_name = "rule_based"
        confidence = 0.2
    return {
        "executed": False,
        "requires_confirmation": True,
        "profile_draft": draft,
        "evidence": evidence,
        "generation_mode": generation_mode,
        "provider": provider,
        "model_name": model_name,
        "confidence": confidence,
        "warning": "这是基于已授权资料生成的候选画像，不会自动写入；请修改并确认后再保存为用户事实。",
    }


def _existing_analysis(db: Session, imported_file_id: int) -> FileAnalysis | None:
    return db.scalar(select(FileAnalysis).where(FileAnalysis.imported_file_id == imported_file_id, FileAnalysis.confirmed.is_(True)).order_by(FileAnalysis.id.desc()))


def _get_or_create_topic(db: Session, name: str, source_path: str) -> tuple[KnowledgeTopic, bool]:
    topic = db.scalar(select(KnowledgeTopic).where(KnowledgeTopic.name == name))
    if topic:
        evidence = list(topic.evidence or [])
        if not any(item.get("source_path") == source_path for item in evidence if isinstance(item, dict)):
            evidence.append({"source_type": "imported_file", "source_path": source_path})
            topic.evidence = evidence[-50:]
        return topic, False
    topic = KnowledgeTopic(name=name, domain="导入资料", definition=f"来自导入文件：{source_path}", tags=["imported"], evidence=[{"source_type": "imported_file", "source_path": source_path}])
    db.add(topic)
    db.flush()
    return topic, True


@router.post("/imports/{import_id}/confirm")
def confirm_import(import_id: int, payload: dict[str, Any], db: Session = Depends(get_db)):
    record = db.get(FileImport, import_id)
    if not record:
        raise HTTPException(status_code=404, detail="导入不存在")
    selected_paths = set(payload.get("relative_paths") or [])
    imported = [item for item in db.scalars(select(ImportedFile).where(ImportedFile.import_id == import_id).order_by(ImportedFile.relative_path)) if not selected_paths or item.relative_path in selected_paths]
    generate_tasks = bool(payload.get("generate_tasks"))
    generate_reviews = bool(payload.get("generate_reviews"))
    generate_cards = bool(payload.get("generate_cards"))
    if selected_paths and any(path not in {item.relative_path for item in imported} for path in selected_paths):
        raise HTTPException(status_code=400, detail="选择的文件不属于该导入记录")
    preview_items = []
    for item in imported:
        topics = _suggest_topics(item)
        preview_items.append({"imported_file_id": item.id, "relative_path": item.relative_path, "source_path": item.relative_path, "suggested_topics": topics, "will_create_note": bool(_read_imported_content(item)), "already_confirmed": _existing_analysis(db, item.id) is not None})
    if not payload.get("confirmed"):
        return {"executed": False, "requires_confirmation": True, "files": len(imported), "preview": preview_items}

    created_topics = 0
    created_notes = 0
    created_tasks = 0
    created_reviews = 0
    confirmed_files = 0
    reused_files = 0
    topic_ids: list[int] = []
    note_ids: list[int] = []
    task_ids: list[int] = []
    review_ids: list[int] = []
    card_ids: list[int] = []
    batch_entries: list[dict[str, Any]] = []
    file_analysis_ids: list[int] = []
    for item in imported:
        analysis = _existing_analysis(db, item.id)
        if analysis:
            reused_files += 1
            continue
        topics = _suggest_topics(item)
        topic_rows: list[KnowledgeTopic] = []
        for topic_name in topics:
            topic, created = _get_or_create_topic(db, topic_name, item.relative_path)
            created_topics += int(created)
            if created:
                batch_entries.append({"entity_type": "knowledge_topic", "entity_id": topic.id, "before": None, "after": {"id": topic.id, "name": topic.name, "domain": topic.domain, "definition": topic.definition, "self_level": topic.self_level, "verified_level": topic.verified_level, "tags": topic.tags or [], "prerequisites": topic.prerequisites or [], "evidence": topic.evidence or []}, "created": True})
            topic_rows.append(topic)
            topic_ids.append(topic.id)
        note = None
        item_content = _read_imported_content(item)
        if item_content:
            title = _clean_topic_name(Path(item.relative_path).stem) or Path(item.relative_path).name
            # Source path plus title is the stable idempotency key for imported notes.
            existing_note = db.scalar(select(Note).where(Note.source_path == item.relative_path, Note.title == title))
            if existing_note:
                note = existing_note
            else:
                note = Note(title=title, content=item_content, summary=f"从文件导入：{item.relative_path}", tags=["imported"], folder="Imported", source_path=item.relative_path, visibility="private", ai_review_status="indexed", linked_topic_ids=[topic.id for topic in topic_rows], status="draft")
                db.add(note)
                db.flush()
                created_notes += 1
                batch_entries.append({"entity_type": "note", "entity_id": note.id, "before": None, "after": {"id": note.id, "title": note.title, "content": note.content, "summary": note.summary, "tags": note.tags or [], "folder": note.folder, "source_path": note.source_path, "visibility": note.visibility, "ai_review_status": note.ai_review_status, "linked_topic_ids": note.linked_topic_ids or [], "linked_task_ids": note.linked_task_ids or [], "linked_project_ids": note.linked_project_ids or [], "status": note.status}, "created": True})
            if note and topic_rows:
                note.linked_topic_ids = sorted(set((note.linked_topic_ids or []) + [topic.id for topic in topic_rows]))
                note_ids.append(note.id)
        item_task_ids: list[int] = []
        item_review_ids: list[int] = []
        if generate_tasks and topic_rows:
            for topic in topic_rows:
                existing_task = db.scalar(select(StudyTask).where(StudyTask.source == "import", StudyTask.title == f"整理并实践：{topic.name}", StudyTask.topic_id == topic.id))
                if existing_task:
                    item_task_ids.append(existing_task.id)
                else:
                    task = StudyTask(title=f"整理并实践：{topic.name}", description=f"基于导入资料 {item.relative_path}，用自己的话解释并完成一个最小实践。", priority=3, estimated_minutes=30, status="not_started", acceptance_criteria="写出解释、示例或可验证的实践结果。", source="import", topic_id=topic.id)
                    db.add(task)
                    db.flush()
                    item_task_ids.append(task.id)
                    task_ids.append(task.id)
                    created_tasks += 1
                    batch_entries.append({"entity_type": "task", "entity_id": task.id, "before": None, "after": {"id": task.id, "title": task.title, "description": task.description, "stage_id": task.stage_id, "priority": task.priority, "estimated_minutes": task.estimated_minutes, "actual_minutes": task.actual_minutes, "status": task.status, "acceptance_criteria": task.acceptance_criteria, "due_date": task.due_date.isoformat() if task.due_date else None, "source": task.source, "project_id": task.project_id, "topic_id": task.topic_id, "week_key": task.week_key, "task_type": task.task_type, "expected_outcome": task.expected_outcome, "agent_feedback": task.agent_feedback, "completed_at": None, "last_verified_at": None, "next_review_date": None}, "created": True})
        if generate_cards and note:
            existing_cards = list(db.scalars(select(ReviewCard).where(ReviewCard.source_note_id == note.id)))
            if not existing_cards:
                paragraph = next((part.strip() for part in re.split(r"\n{2,}", note.content or "") if part.strip()), note.summary or note.title)
                card = ReviewCard(front=f"请解释《{note.title}》的核心要点。", back=paragraph[:10000], hint="先说定义，再说一个例子。", source_note_id=note.id)
                db.add(card)
                db.flush()
                card_ids.append(card.id)
                batch_entries.append({"entity_type": "review_card", "entity_id": card.id, "before": None, "after": {"id": card.id, "front": card.front, "back": card.back, "hint": card.hint, "card_type": card.card_type, "topic_id": card.topic_id, "source_note_id": card.source_note_id, "status": card.status, "error_type": card.error_type, "error_count": card.error_count, "last_error_note": card.last_error_note, "due_date": card.due_date.isoformat(), "interval_days": card.interval_days, "ease_factor": card.ease_factor, "repetitions": card.repetitions, "last_quality": card.last_quality, "created_at": card.created_at.isoformat(), "updated_at": card.updated_at.isoformat()}, "created": True})
        if generate_reviews and topic_rows:
            log = db.scalar(select(DailyLog).where(DailyLog.raw_text == f"导入学习资料：{item.relative_path}"))
            if log is None:
                log = DailyLog(raw_text=f"导入学习资料：{item.relative_path}", extracted_topics=[topic.name for topic in topic_rows], topic_ids=[topic.id for topic in topic_rows], note_ids=[note.id] if note else [], structured_status="confirmed")
                db.add(log)
                db.flush()
                batch_entries.append({"entity_type": "daily_log", "entity_id": log.id, "before": None, "after": {"id": log.id, "log_date": log.log_date.isoformat(), "raw_text": log.raw_text, "extracted_topics": log.extracted_topics or [], "extracted_duration": log.extracted_duration, "extracted_outputs": log.extracted_outputs or [], "understood_content": log.understood_content or [], "unresolved_questions": log.unresolved_questions or [], "self_assessment": log.self_assessment, "project_id": log.project_id, "topic_ids": log.topic_ids or [], "note_ids": log.note_ids or [], "structured_status": log.structured_status, "ai_extracted": log.ai_extracted or {}, "confirmed_fields": log.confirmed_fields or [], "field_sources": log.field_sources or []}, "created": True})
            for topic in topic_rows:
                existing_review = db.scalar(select(DailyLogReview).where(DailyLogReview.daily_log_id == log.id, DailyLogReview.topic_id == topic.id))
                if existing_review:
                    item_review_ids.append(existing_review.id)
                else:
                    review = DailyLogReview(daily_log_id=log.id, review_date=date.today(), note=f"复习导入主题：{topic.name}", topic_id=topic.id)
                    db.add(review)
                    db.flush()
                    item_review_ids.append(review.id)
                    review_ids.append(review.id)
                    created_reviews += 1
        result = {"suggested_topics": topics, "topic_ids": [topic.id for topic in topic_rows], "note_id": note.id if note else None, "task_ids": item_task_ids, "review_ids": item_review_ids, "relative_path": item.relative_path, "sha256": item.sha256}
        db.flush()
        analysis = FileAnalysis(imported_file_id=item.id, provider="local_index", model_name="none", status="confirmed", result={}, confirmed=True, confirmed_at=utcnow())
        db.add(analysis)
        db.flush()
        file_analysis_ids.append(analysis.id)
        result_relative = _storage_relative("analysis", record.id, analysis.id, ".json")
        analysis.result_file_path = result_relative
        analysis.result_sha256 = _write_json(_storage_path(result_relative), result)
        db.flush()
        confirmed_files += 1
    db.flush()
    # Keep a lightweight capability trail without fabricating a profile when no capability has been assessed yet.
    for topic_id in sorted(set(topic_ids)):
        profile = db.scalar(select(CapabilityProfile).where(CapabilityProfile.name == "导入资料整理"))
        if profile:
            existing = db.scalar(select(CapabilityEvidence).where(CapabilityEvidence.capability_id == profile.id, CapabilityEvidence.source_type == "import", CapabilityEvidence.source_id == topic_id))
            if not existing:
                db.add(CapabilityEvidence(capability_id=profile.id, source_type="import", source_id=topic_id, score=0.25, note="导入资料形成知识主题证据"))
    db.flush()
    batch = None
    if batch_entries or file_analysis_ids:
        batch = AgentChangeBatch(operation="import_confirm", status="executed", changes=[{"import_id": record.id, "file_analysis_ids": file_analysis_ids}], before_data=[{"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("before")} for entry in batch_entries], after_data=[{"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("after"), "created": True} for entry in batch_entries])
        db.add(batch)
        db.flush()
        db.add(AuditLog(entity_type="import", entity_id=record.id, action="confirm", before_data=None, after_data={"batch_id": batch.id, "file_analysis_ids": file_analysis_ids, "created_topics": created_topics, "created_notes": created_notes, "created_tasks": created_tasks, "created_reviews": created_reviews, "created_cards": len(card_ids)}))
    db.commit()
    return {"executed": True, "batch_id": batch.id if batch else None, "confirmed_files": confirmed_files, "reused_files": reused_files, "created_topics": created_topics, "created_notes": created_notes, "created_tasks": created_tasks, "created_reviews": created_reviews, "created_cards": len(card_ids), "topic_ids": sorted(set(topic_ids)), "note_ids": sorted(set(note_ids)), "task_ids": sorted(set(task_ids)), "review_ids": sorted(set(review_ids)), "card_ids": sorted(set(card_ids)), "status": "confirmed"}

@router.post("/imports/scan")
def unauthorized_scan(payload: dict[str, str], db: Session = Depends(get_db)):
    raise HTTPException(status_code=403, detail="必须先授权目录")

@router.get("/imports/integrity")
def imports_integrity(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(ImportedFile).order_by(ImportedFile.id)))
    reports = [_check_file_integrity(db, item) for item in rows]
    for item, report in zip(rows, reports):
        item.index_status = report["status"]
        item.last_verified_at = utcnow()
    web_rows = list(db.scalars(select(WebResource).order_by(WebResource.id)))
    web_reports = [_check_web_integrity(item) for item in web_rows]
    known_paths = {path for item in rows for path in (item.raw_file_path, item.content_file_path, item.index_file_path) if path}
    known_paths.update(path for item in web_rows for path in (item.raw_file_path, item.content_file_path, item.index_file_path) if path)
    known_analysis = {analysis.result_file_path for analysis in db.scalars(select(FileAnalysis)) if analysis.result_file_path}
    storage_root = _storage_root()
    orphan_files: list[str] = []
    for path in storage_root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(data_dir()).as_posix()
            if relative not in known_paths and relative not in known_analysis:
                orphan_files.append(relative)
    counts = {key: sum(report["status"] == key for report in reports) for key in ("healthy", "missing", "stale")}
    analysis_reports: list[dict[str, Any]] = []
    for analysis in db.scalars(select(FileAnalysis).order_by(FileAnalysis.id)):
        path = _storage_path(analysis.result_file_path) if analysis.result_file_path else None
        exists = path is not None and path.exists()
        digest = _sha256_file(path) if exists else None
        analysis_reports.append({"analysis_id": analysis.id, "imported_file_id": analysis.imported_file_id, "status": "healthy" if exists and (not analysis.result_sha256 or digest == analysis.result_sha256) else ("missing" if not exists else "stale"), "result_exists": exists, "result_hash_matches": bool(exists and (not analysis.result_sha256 or digest == analysis.result_sha256))})
    db.commit()
    return {"total": len(reports), "counts": counts, "files": reports, "web_resources": web_reports, "analyses": analysis_reports, "orphan_files": sorted(orphan_files)}


@router.get("/imports/{import_id}")
def get_import(import_id: int, db: Session = Depends(get_db)):
    record = db.get(FileImport, import_id)
    if not record: raise HTTPException(status_code=404, detail="导入不存在")
    return {"import_id": record.id, "files_scanned": record.files_scanned, "files": record.files, "excluded": record.excluded, "indexed_files": [{"id": item.id, "relative_path": item.relative_path, "sha256": item.sha256, "content_status": item.content_status, "content_file_path": item.content_file_path, "index_file_path": item.index_file_path, "index_status": item.index_status} for item in db.scalars(select(ImportedFile).where(ImportedFile.import_id == record.id).order_by(ImportedFile.relative_path))]}

@router.delete("/imports/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_import(import_id: int, db: Session = Depends(get_db)):
    record = db.get(FileImport, import_id)
    if not record: raise HTTPException(status_code=404, detail="导入不存在")
    db.delete(record); db.commit()
