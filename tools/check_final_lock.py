"""Regression check FINAL LOCK (stdlib only: sqlite3 + urllib + json).

Cara pakai (di Windows, setelah server jalan via jalankan.bat):
    python tools\\check_final_lock.py --db servisku.db --base http://127.0.0.1:8000

Fase 1 (offline, file DB): skema + data legacy + histori.
Fase 2 (live API): lifecycle penuh pada order TEST, lalu dibersihkan.
Keluar kode 0 bila semua PASS, 1 bila ada FAIL.
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request

CANON = ["DITERIMA", "ANALISA", "DIAGNOSA", "KONFIRMASI", "MENUNGGU SPAREPART",
         "PERBAIKAN", "SELESAI", "GAGAL", "BATAL"]
LEGACY = ["RECEIVED", "ANALISA", "DIAGNOSIS", "KONFIRMASI", "WAIT PART", "WAITING_PART",
          "REPAIR", "DONE", "CASH", "FAILED", "FILED", "CANCEL", "READY", "COMPLETED",
          "QC", "WAITING_APPROVAL", "REPARASI"]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" — " + str(detail) if detail else ""))


def phase_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(service_orders)").fetchall()}
    for c in ("unit_status", "taken_at", "lunas_date", "lunas_at"):
        check("kolom service_orders." + c, c in cols)
    for c in ("status_history", "payments"):
        t = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (c,)).fetchone()
        check("tabel " + c, bool(t))
    pcols = {r[1] for r in cur.execute("PRAGMA table_info(payments)").fetchall()}
    check("kolom payments.kind", "kind" in pcols)
    sts = [r[0] for r in cur.execute("SELECT DISTINCT status FROM service_orders").fetchall()]
    bad = [s for s in sts if s not in CANON]
    check("nol status legacy aktif", not bad, bad or "ok")
    n_ord = cur.execute("SELECT COUNT(*) FROM service_orders").fetchone()[0]
    n_nohist = cur.execute(
        "SELECT COUNT(*) FROM service_orders o WHERE NOT EXISTS "
        "(SELECT 1 FROM status_history h WHERE h.service_order_id=o.id)").fetchone()[0]
    check("semua order punya history", n_nohist == 0, "%d/%d tanpa history" % (n_nohist, n_ord))
    n_pay_nokind = 0
    try:
        n_pay_nokind = cur.execute("SELECT COUNT(*) FROM payments WHERE kind IS NULL").fetchone()[0]
    except sqlite3.OperationalError:
        pass
    check("payments berkind semua", n_pay_nokind == 0)
    con.close()


def api(base, method, path, token=None, body=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"detail": str(e)}


def phase_api(base, tok):
    st, _ = api(base, "GET", "/api/auth/me", tok)
    check("sesi token valid", st == 200, st)
    if st != 200:
        return

    st, o = api(base, "POST", "/api/orders/receive", tok,
                {"customer_name": "REGTEST", "customer_phone": "089999000111",
                 "device": "REGTEST Device", "damagetype": "REGTEST"})
    check("receive → DITERIMA", st == 201 and o.get("status") == "DITERIMA", st)
    if st != 201:
        return
    oid = o["id"]

    st, _ = api(base, "PUT", "/api/orders/%d" % oid, tok, {"status": "SELESAI"})
    check("lompat DITERIMA→SELESAI ditolak", st == 400, st)
    st, _ = api(base, "PUT", "/api/orders/%d" % oid, tok, {"status": "GAGAL"})
    check("GAGAL tanpa catatan ditolak", st == 400, st)
    for s, extra in (("ANALISA", {}),
                     ("DIAGNOSA", {}),
                     ("KONFIRMASI", {"repair_plan": "REGTEST plan", "estimate": 500000}),
                     ("PERBAIKAN", {"technician": "Budi"}),
                     ("SELESAI", {})):
        st, o = api(base, "PUT", "/api/orders/%d" % oid, tok, dict({"status": s}, **extra))
        check("transisi → %s" % s, st == 200 and o.get("status") == s, st)

    st, _ = api(base, "POST", "/api/payments", tok,
                {"service_order_id": oid, "kind": "DP", "amount": 100000})
    check("bayar DP 100rb", st == 201, st)
    st, p = api(base, "POST", "/api/payments", tok,
                {"service_order_id": oid, "kind": "PELUNASAN", "amount": 500000})
    check("overpay ditolak", st == 400, st)
    st, p = api(base, "POST", "/api/payments", tok,
                {"service_order_id": oid, "kind": "PELUNASAN", "amount": 400000})
    check("pelunasan → LUNAS", st == 201 and p.get("payment_status") == "LUNAS",
          "%s %s" % (st, (p.get("payment_status") if isinstance(p, dict) else p)))

    st, h = api(base, "POST", "/api/orders/%d/handover" % oid, tok, {})
    check("handover → DIAMBIL", st == 200 and h.get("unit_status") == "DIAMBIL", st)
    st, hs = api(base, "GET", "/api/orders/%d/history" % oid, tok)
    check("history tercatat (≥6)", st == 200 and isinstance(hs, list) and len(hs) >= 6,
          "%s baris=%s" % (st, len(hs) if isinstance(hs, list) else hs))
    st, g = api(base, "GET", "/api/claims/warranty-summary", tok)
    ok_g = st == 200 and any((i.get("service_order_id") == oid) for i in (g.get("items") or []))
    check("masuk warranty-summary", ok_g, st)
    st, k = api(base, "GET", "/api/kas/riwayat?period=all", tok)
    pay_ids = {x.get("id") for x in (p.get("items") or [])} if isinstance(p, dict) else set()
    ok_k = (st == 200 and any(i.get("source") == "order" and i.get("ref_id") in pay_ids
                              for i in (k.get("items") or [])))
    check("pembayaran masuk kas", ok_k, st)
    st, _ = api(base, "DELETE", "/api/orders/%d" % oid, tok)
    check("bersihkan order TEST", st == 200, st)


def phase_paths(base, tok):
    """Regression khusus 4 initial path Servis Baru."""
    base_payload = {"customer_name": "REGTEST-PATH", "customer_phone": "089999000222",
                    "device": "REGTEST Path Device", "damagetype": "REGTEST"}
    ids = []

    def recv(extra):
        p = dict(base_payload)
        p.update(extra)
        return api(base, "POST", "/api/orders/receive", tok, p)

    def hist_len(oid):
        st, hs = api(base, "GET", "/api/orders/%d/history" % oid, tok)
        return (st, len(hs) if isinstance(hs, list) else hs)

    # 1. TITIP → DITERIMA, chain 1
    st, o = recv({"initial_path": "TITIP"})
    check("path TITIP → DITERIMA", st == 201 and o.get("status") == "DITERIMA", st)
    if st == 201:
        ids.append(o["id"])
        sth, n = hist_len(o["id"])
        check("path TITIP chain=1", sth == 200 and n == 1, n)

    # 2. PERBAIKAN tanpa teknisi → 400; lengkap → PERBAIKAN chain 5
    st, _ = recv({"initial_path": "PERBAIKAN", "repair_plan": "REGTEST",
                  "estimate": 500000})
    check("path PERBAIKAN tanpa teknisi ditolak", st == 400, st)
    st, o = recv({"initial_path": "PERBAIKAN", "repair_plan": "REGTEST",
                  "estimate": 500000, "technician": "Budi"})
    check("path PERBAIKAN → PERBAIKAN", st == 201 and o.get("status") == "PERBAIKAN", st)
    if st == 201:
        ids.append(o["id"])
        sth, n = hist_len(o["id"])
        check("path PERBAIKAN chain=5", sth == 200 and n == 5, n)

    # 3. SPAREPART lengkap → MENUNGGU SPAREPART chain 5
    st, o = recv({"initial_path": "SPAREPART", "repair_plan": "REGTEST",
                  "estimate": 300000, "technician": "Andi"})
    check("path SPAREPART → MENUNGGU SPAREPART",
          st == 201 and o.get("status") == "MENUNGGU SPAREPART", st)
    if st == 201:
        ids.append(o["id"])
        sth, n = hist_len(o["id"])
        check("path SPAREPART chain=5", sth == 200 and n == 5, n)

    # 4. TUNGGU tanpa final (null) → 400; final=0 boleh → SELESAI chain 6
    st, _ = recv({"initial_path": "TUNGGU", "repair_plan": "REGTEST",
                  "technician": "Budi"})
    check("path TUNGGU tanpa final ditolak", st == 400, st)
    st, o = recv({"initial_path": "TUNGGU", "repair_plan": "REGTEST",
                  "technician": "Budi", "final_price": 0})
    check("path TUNGGU final=0 → SELESAI", st == 201 and o.get("status") == "SELESAI", st)
    if st == 201:
        ids.append(o["id"])
        sth, n = hist_len(o["id"])
        check("path TUNGGU chain=6", sth == 200 and n == 6, n)

    # 5. Tanpa initial_path → tetap DITERIMA (legacy)
    st, o = recv({})
    check("tanpa path → DITERIMA", st == 201 and o.get("status") == "DITERIMA", st)
    if st == 201:
        ids.append(o["id"])

    for oid in ids:
        st, _ = api(base, "DELETE", "/api/orders/%d" % oid, tok)
        check("bersihkan order path %d" % oid, st == 200, st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="servisku.db")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--skip-api", action="store_true")
    a = ap.parse_args()
    print("== FASE 1: DB " + a.db + " ==")
    try:
        phase_db(a.db)
    except Exception as e:
        check("buka DB", False, e)
    if not a.skip_api:
        print("== FASE 2: API " + a.base + " ==")
        st, me = api(a.base, "POST", "/api/auth/login", None,
                     {"username": "superadmin", "passcode": "Admin4100"})
        check("login superadmin", st == 200, st)
        tok = (me.get("token") or me.get("access_token")) if st == 200 else None
        check("token diterima", bool(tok))
        if tok:
            phase_api(a.base, tok)
            print("== FASE 3: INITIAL PATH ==")
            phase_paths(a.base, tok)
    fails = [n for n, ok, _ in results if not ok]
    print("== %d/%d PASS ==" % (len(results) - len(fails), len(results)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
