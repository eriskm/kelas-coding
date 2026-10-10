# -*- coding: utf-8 -*-
"""P2-14 — Idempotency key untuk endpoint money/closing (roadmap P2-14 (a)).

Tujuan: retry (double-click /ulang request) dengan `Idempotency-Key` yang sama
TIDAK menggandakan efek uang. Response pertama disimpan dan dikembalikan ulang.

Perilaku:
- tanpa key → endpoint berjalan seperti biasa (kompatibilitas penuh);
- key baru  → jalankan aksi, simpan `response`;
- key sama + request sama  → kembalikan response tersimpan (`replayed=True`), tanpa efek;
- key sama + request berbeda → **409** (salah pakai key);
- key sama masih IN_PROGRESS  → **409** (request sebelumnya belum selesai).

Catatan transaksi: record ditulis pada transaksi yang SAMA dengan aksi money, jadi
`commit()` sekali di endpoint membuat aksi + idempotency record atomik; kegagalan
→ `rollback()` menghapus keduanya (tidak ada efek setengah jadi, roadmap P2-14 (b)).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy.orm import Session

STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_COMPLETED = "COMPLETED"

HEADER = "Idempotency-Key"


class IdempotencyConflict(Exception):
    """Key sama dipakai dengan request berbeda, atau masih diproses."""

    def __init__(self, message, code: str = "IDEMPOTENCY_CONFLICT"):
        self.code = code
        super().__init__(message)


def hash_request(payload) -> str:
    """Hash stabil dari payload request (urutan key dinormalisasi)."""
    try:
        blob = json.dumps(payload, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = str(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _get(db: Session, scope: str, key: str):
    from models import IdempotencyRecord
    return (db.query(IdempotencyRecord)
            .filter(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key)
            .order_by(IdempotencyRecord.id.desc()).first())


def jalankan(db: Session, scope: str, key: str, payload, aksi, actor: str = None):
    """Jalankan `aksi()` dengan proteksi idempotency key.

    `aksi` adalah fungsi tanpa argumen yang mengembalikan dict/obj yang akan
    disimpan sebagai response. TIDAK melakukan commit (transaction di endpoint).
    """
    if not key:
        return {"replayed": False, "result": aksi(), "key": None}

    row = _get(db, scope, key)
    req_hash = hash_request(payload)

    if row is not None:
        if row.request_hash != req_hash:
            raise IdempotencyConflict(
                "Idempotency-Key sudah dipakai untuk request berbeda", code="KEY_REUSE")
        if row.status == STATUS_IN_PROGRESS:
            raise IdempotencyConflict(
                "Permintaan dengan Idempotency-Key ini sedang diproses", code="IN_PROGRESS")
        try:
            stored = json.loads(row.response_json) if row.response_json else None
        except Exception:  # noqa: BLE001
            stored = None
        return {"replayed": True, "result": stored, "key": key,
                "created_at": row.created_at}

    from models import IdempotencyRecord
    record = IdempotencyRecord(scope=scope, key=key, request_hash=req_hash,
                               status=STATUS_IN_PROGRESS, actor=actor)
    db.add(record)
    db.flush()

    result = aksi()
    record.status = STATUS_COMPLETED
    try:
        record.response_json = json.dumps(result, default=str)
    except Exception:  # noqa: BLE001
        record.response_json = None
    db.flush()
    return {"replayed": False, "result": result, "key": key,
            "created_at": record.created_at or datetime.now()}