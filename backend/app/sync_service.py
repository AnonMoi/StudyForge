"""Password-protected, portable sync bundles for the local-first workstation."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


SYNC_FORMAT = "learning-workstation-sync-v1"
KDF_ITERATIONS = 390_000
MIN_PASSPHRASE_LENGTH = 12


def _derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError(f"同步包口令至少需要 {MIN_PASSPHRASE_LENGTH} 个字符")
    if not 100_000 <= iterations <= 1_000_000:
        raise ValueError("同步包 KDF 参数无效")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def create_sync_bundle(backup: dict[str, Any], passphrase: str, summary: dict[str, int]) -> dict[str, Any]:
    salt = secrets.token_bytes(16)
    payload = json.dumps(backup, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = _derive_key(passphrase, salt)
    ciphertext = Fernet(key).encrypt(payload)
    return {
        "format": SYNC_FORMAT,
        "algorithm": "Fernet + PBKDF2-HMAC-SHA256",
        "kdf_iterations": KDF_ITERATIONS,
        "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
        "ciphertext": ciphertext.decode("ascii"),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "summary": summary,
    }


def decrypt_sync_bundle(bundle: dict[str, Any], passphrase: str) -> dict[str, Any]:
    if not isinstance(bundle, dict) or bundle.get("format") != SYNC_FORMAT:
        raise ValueError("同步包格式不受支持")
    try:
        salt = base64.urlsafe_b64decode(str(bundle["salt"]).encode("ascii"))
        ciphertext = str(bundle["ciphertext"]).encode("ascii")
        iterations = int(bundle.get("kdf_iterations", KDF_ITERATIONS))
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("同步包字段无效") from exc
    if len(salt) != 16:
        raise ValueError("同步包盐值无效")
    try:
        payload = Fernet(_derive_key(passphrase, salt, iterations)).decrypt(ciphertext)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError("同步包口令错误或内容已损坏") from exc
    expected_hash = str(bundle.get("payload_sha256", ""))
    if expected_hash and not secrets.compare_digest(hashlib.sha256(payload).hexdigest(), expected_hash):
        raise ValueError("同步包完整性校验失败")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("同步包内容不是有效 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("同步包数据必须是对象")
    return decoded


__all__ = ["MIN_PASSPHRASE_LENGTH", "SYNC_FORMAT", "create_sync_bundle", "decrypt_sync_bundle"]
