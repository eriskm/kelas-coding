"""Authority matrix — Owner Decision Q12 & Q13.

ADAPT dari authority Project A ke architecture Project B (dependency-based).
BUKAN permission string seperti Project A (Q12: "jangan copy permission string").

Sumber aturan:
- OD-014 / FIX-33: akun TEKNISI tidak boleh mengubah status closing.
- Project A `app.py:2079-2084`: role tanpa authority finance mempertahankan nilai
  angka lama (tidak ditolak, tidak ditimpa).
- Project A `app.py:2786`: pembayaran boleh admin / kasir (permission 'servis').
- Project A `app.py:2051-2551`: master sparepart boleh admin; hapus admin.
- Q13: PENGELOLA = pemilik/pengelola usaha, beneficiary 30% bagi hasil.
  Peran ini read-oriented (monitoring), aksesnya kurang lebih seperti Investor.

Detail granularitas role/dependency adalah implementation detail (ID-11):
role di Project B berupa free-text, sehingga role yang tidak dikenal bersifat
fail-closed untuk semua aksi tulis.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from routers.auth import get_authenticated_user

ROLE_SUPERADMIN = "SUPERADMIN"
ROLE_ADMIN = "ADMIN"
ROLE_KASIR = "KASIR"
ROLE_TEKNISI = "TEKNISI"
ROLE_PENGELOLA = "PENGELOLA"
ROLE_INVESTOR = "INVESTOR"
ROLE_ADMIN_SPAREPART = "ADMIN_SPAREPART"
ROLE_CUSTOM = "CUSTOM"

# Alias: Project B menyimpan role free-text, jadi dinormalkan di satu tempat.
#
# PENTING: `SUPERADMIN` dulu dipetakan ke `ADMIN`. Owner memisahkannya:
# Super Admin = akun Developer (kelola role, permission, konfigurasi, audit),
# sedangkan Admin = Manager Toko (operasional + Tutup Kas). Kalau masih alias,
# tidak ada bedanya sama sekali dan "jangan berikan role ini otomatis kepada
# Admin toko" tidak bisa ditegakkan.
ROLE_ALIASES = {
    "SUPERADMIN": ROLE_SUPERADMIN,
    "SUPER ADMIN": ROLE_SUPERADMIN,
    "SUPER_ADMIN": ROLE_SUPERADMIN,
    "DEV": ROLE_SUPERADMIN,
    "DEVELOPER": ROLE_SUPERADMIN,
    "ADMIN": ROLE_ADMIN,
    "MANAGER": ROLE_ADMIN,
    "KASIR": ROLE_KASIR,
    "CS": ROLE_KASIR,
    "TEKNISI": ROLE_TEKNISI,
    "TEKNIKER": ROLE_TEKNISI,
    "PENGELOLA": ROLE_PENGELOLA,
    "PEMILIK": ROLE_PENGELOLA,
    # INVESTOR dulunya dipetakan ke PENGELOLA. Itu berarti akun "Investor"
    # otomatis ikut boleh melihat Kas Aset + Master Kas -- sama dengan pengelola
    # toko. Owner meminta keduanya dipisah, jadi sekarang jadi role sendiri.
    "INVESTOR": ROLE_INVESTOR,
    "ADMIN SPAREPART": ROLE_ADMIN_SPAREPART,
    "ADMIN_SPAREPART": ROLE_ADMIN_SPAREPART,
    "ADM_SPAREPART": ROLE_ADMIN_SPAREPART,
    "SPAREPART_ADMIN": ROLE_ADMIN_SPAREPART,
    "CUSTOM": ROLE_CUSTOM,
}

#: Role tertinggi wewenang: punya akses ke SEMUA aksi, termasuk ROLE_CONFIG yang
#: tidak boleh dimiliki role lain. Dipakai matriks supaya tidak ada satu pun
#: baris yang lupa menambahkan SUPER ADMIN.
ROLE_SUPER = ROLE_SUPERADMIN

# Role yang hanya boleh melihat/monitoring (Q13).
# INVESTOR masuk sini: read-oriented seperti PENGELOLA, tapi TIDAK termasuk
# role yang boleh melihat posisi Kas BESAR (lihat `_lihat_aset` di router
# dashboard) -- itu masih khusus Admin & Pengelola sesuai SSOT-7 / v4 #11.
MONITORING_ROLES = frozenset({ROLE_PENGELOLA, ROLE_INVESTOR})

#: Aksi yang TIDAK ikut aturan "role read-oriented tidak boleh menulis".
#:
#: `can()` menolak semua role di MONITORING_ROLES sebelum sempat membaca matriks,
#: jadi menambahkan ROLE_PENGELOLA ke `AUTHORITY_MATRIX` saja TIDAK akan
#: berk efek. Owner menetapkan: "suntikan dana ke Kas Aset hanya boleh
#: Pengelola dan Admin" -- jadi PENGELOLA diberi pengecualian untuk aksi ini saja.
#:
#: Pengecualian ini hanya MENCABUT blanket read-only; matriks tetap yang
#: memutuskan. INVESTOR tidak masuk `allowed_roles(KAS_ASET_INJEKSI)`, jadi
#: dia tetap ditolak.

# Status "closing" di Project B. Warranty/claim/refund berada di domain terpisah (P2-09/P2-10).
# P2-15 / Owner Cash Model: CASH ikut menjadi status closing (event realisasi transaksi
# + serah-terima unit), sehingga hanya Admin/Kasir yang boleh mengubah status ke CASH.
CLOSING_STATUSES = frozenset({"CANCEL", "CASH"})

# Kolom angka keuangan pada service order (ADAPT dari app.py:2079-2084).
FINANCE_FIELDS = (
    "final_price",
    "part_cost",
    "modal_jasa",
    "modal_lainnya",
    "estimate",
    "payment",
    # Menandai unit sebagai "memang tanpa modal" menentukan apakah unit ikut
    # dihitung sebagai transaksi atau tidak -- jadi sama guarantorannya
    # dengan angka modal itu sendiri. Role tanpa authority finance tidak boleh
    # mengubahnya.
    "tanpa_modal",
)

#: Modal menentukan Laba Kotor, jadi tidak boleh disentuh Kasir meski boleh
#: mengubah harga. Dipisahkan supaya penjaganya bisa bedah per kelompok.
MODAL_FIELDS = (
    "part_cost",
    "modal_jasa",
    "modal_lainnya",
    "tanpa_modal",
)

#: Sisanya (harga, estimasi, payment) mengikuti `ORDER_UPDATE_FINANCE`.
FINANCE_FIELDS_LAINNYA = tuple(f for f in FINANCE_FIELDS if f not in MODAL_FIELDS)


class Action:
    ORDER_CREATE = "ORDER_CREATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    ORDER_UPDATE_FINANCE = "ORDER_UPDATE_FINANCE"
    ORDER_STATUS_CLOSING = "ORDER_STATUS_CLOSING"
    ORDER_HANDOVER = "ORDER_HANDOVER"
    ORDER_DELETE = "ORDER_DELETE"
    PAYMENT_CREATE = "PAYMENT_CREATE"
    PAYMENT_CANCEL = "PAYMENT_CANCEL"
    EXPENSE_WRITE = "EXPENSE_WRITE"
    EXPENSE_DEBT_WRITE = "EXPENSE_DEBT_WRITE"
    KAS_ENTRY_WRITE = "KAS_ENTRY_WRITE"
    KAS_CLOSE = "KAS_CLOSE"
    KAS_ASET_INJEKSI = "KAS_ASET_INJEKSI"
    REFUND_DP = "REFUND_DP"
    REFUND_GARANSI = "REFUND_GARANSI"
    FAILED_CANCEL = "FAILED_CANCEL"
    SPAREPART_WRITE = "SPAREPART_WRITE"
    SPAREPART_DELETE = "SPAREPART_DELETE"
    CLAIM_WRITE = "CLAIM_WRITE"
    USER_MANAGE = "USER_MANAGE"
    CUSTOMER_WRITE = "CUSTOMER_WRITE"
    CUSTOMER_DELETE = "CUSTOMER_DELETE"
    ROLE_CONFIG = "ROLE_CONFIG"
    AUDIT_READ = "AUDIT_READ"
    REPORT_FULL = "REPORT_FULL"
    REPORT_INVESTOR = "REPORT_INVESTOR"
    REPORT_SPAREPART = "REPORT_SPAREPART"
    ORDER_UPDATE_MODAL = "ORDER_UPDATE_MODAL"


AUTHORITY_MATRIX = {
    # -- unit servis --------------------------------------------------------
    Action.ORDER_CREATE: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    Action.ORDER_UPDATE: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    # Angka keuangan pada unit. TEKNISI tidak boleh sama sekali (ADAPT
    # app.py:2079-2084); ADMIN SPAREPART hanya boleh melihat kebutuhan
    # sparepart, bukan mengubah transaksi unit.
    Action.ORDER_UPDATE_FINANCE: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    # Harga/estimasi boleh diubah Kasir (itu bagian terima unit); MODAL TIDAK.
    # `MODAL_FIELDS` di `sanitize_finance_payload` memakai aksi ini.
    Action.ORDER_UPDATE_MODAL: {ROLE_SUPER, ROLE_ADMIN},
    # status closing: TEKNISI tidak boleh (OD-014 / FIX-33)
    Action.ORDER_STATUS_CLOSING: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    Action.ORDER_HANDOVER: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR, ROLE_TEKNISI},
    Action.ORDER_DELETE: {ROLE_SUPER, ROLE_ADMIN},
    # -- uang ---------------------------------------------------------------
    Action.PAYMENT_CREATE: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    Action.PAYMENT_CANCEL: {ROLE_SUPER, ROLE_ADMIN},
    # Beban. Kasir TIDAK boleh: tugasnya pembayaran & nota, bukan mencatat
    # beban (Owner: "tidak boleh mengubah ... konfigurasi keuangan").
    Action.EXPENSE_WRITE: {ROLE_SUPER, ROLE_ADMIN},
    # P2-11: Hutang Beban (Q8/Q18) - Admin; PENGELOLA read-oriented (Q13).
    Action.EXPENSE_DEBT_WRITE: {ROLE_SUPER, ROLE_ADMIN},
    Action.KAS_ENTRY_WRITE: {ROLE_SUPER, ROLE_ADMIN},
    # Tutup Kas hanya Admin (Owner: "Hanya Admin yang berwenang menjalankan
    # Tutup Kas sesuai aturan"). Kasir secara eksplisit tidak boleh.
    Action.KAS_CLOSE: {ROLE_SUPER, ROLE_ADMIN},
    Action.KAS_ASET_INJEKSI: {ROLE_SUPER, ROLE_ADMIN},
    Action.REFUND_DP: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    Action.REFUND_GARANSI: {ROLE_SUPER, ROLE_ADMIN},
    Action.FAILED_CANCEL: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    # -- inventaris & klaim -------------------------------------------------
    # Sparepart: khusus ADMIN SPAREPART. Kasir dan Teknisi dicabut dari sini
    # sesuai pembagian tugas; Teknisi hanya melihat kebutuhan sparepart.
    Action.SPAREPART_WRITE: {ROLE_SUPER, ROLE_ADMIN, ROLE_ADMIN_SPAREPART},
    # Hapus sparepart TIDAK ikut Admin Sparepart. Akses lama tidak berubah:
    # sebelumnya endpoint ini dijaga penjaga (Super Admin + Admin saja),
    # dan SPAREPART_WRITE tidak boleh dipakai untuk hapus karena role itu
    # punya SPAREPART_WRITE.
    Action.SPAREPART_DELETE: {ROLE_SUPER, ROLE_ADMIN},
    Action.CLAIM_WRITE: {ROLE_SUPER, ROLE_ADMIN},
    # -- akun & konfigurasi -------------------------------------------------
    Action.USER_MANAGE: {ROLE_SUPER},
    # Role, permission, konfigurasi teknis, dan audit log: Super Admin saja.
    # Admin (Manager Toko) managing operasional, TIDAK konfigurasi sistem.
    Action.ROLE_CONFIG: {ROLE_SUPER},
    Action.AUDIT_READ: {ROLE_SUPER, ROLE_ADMIN},
    # Data pelanggan. Sebelumnya router customers.py tidak punya penjaga role
    # sama sekali, jadi PENGELOLA dan INVESTOR pun bisa menambah, mengubah,
    # bahkan MENGHAPUS customer. Owner: "Role pengelola hanya bisa melihat
    # keseluruhan program, tidak ada wewenang untuk mengubah apapun."
    Action.CUSTOMER_WRITE: {ROLE_SUPER, ROLE_ADMIN, ROLE_KASIR},
    Action.CUSTOMER_DELETE: {ROLE_SUPER, ROLE_ADMIN},
    # -- laporan & data -----------------------------------------------------
    # Laporan detail + filter + unduh: PENGELOLA (pemilik).
    Action.REPORT_FULL: {ROLE_SUPER, ROLE_ADMIN, ROLE_PENGELOLA},
    # Laporan investasi: ringkas saja, TANPA data pribadi pelanggan.
    Action.REPORT_INVESTOR: {ROLE_SUPER, ROLE_ADMIN, ROLE_INVESTOR},
    Action.REPORT_SPAREPART: {ROLE_SUPER, ROLE_ADMIN, ROLE_ADMIN_SPAREPART},
}


#: Aksi BACA yang tetap boleh dipakai role monitoring (PENGELOLA/INVESTOR).
#: Dideklarasikan setelah `AUTHORITY_MATRIX` supaya nama aksinya sudah ada.
#:
#: PENGELOLA boleh melihat laporan detail + unduh. INVESTOR boleh laporan
#: investasi (dasar bagi hasil 30%). Keduanya tetap TIDAK boleh menulis apa pun.
#: `REPORT_SPAREPART` sengaja TIDAK ada di sini: Admin Sparepart bukan role
#: monitoring, jadi ia boleh lewat blanket yang sama tanpa pengecualian.
MONITORING_READ_ACTIONS = frozenset({
    Action.REPORT_FULL,
    Action.REPORT_INVESTOR,
})
# INVESTOR sengaja TIDAK muncul di satu pun set di atas: dia read-only
# (monitoring). Kalau suatu saat perlu hak menulis, harus diputuskan eksplisit
# -- bukan dengan diam-diam menambahkannya ke sini.
#
# Catatan untuk PENGELOLA: Owner menyatakan dia "hanya bisa melihat keseluruhan
# program, tidak ada wewenang untuk mengubah apapun". Itu ditegakkan oleh aturan
# `can()` di bawah -- selama PENGELOLA ada di `MONITORING_ROLES`, dia ditolak
# di SELURUH aksi, berapa pun isi matriksnya. Kalau suatu saat dia perlu menulis,
# aturan read-only itu yang harus diputuskan Owner lebih dulu.

DEFAULT_MESSAGES = {
    Action.ORDER_CREATE: "Hanya Admin/Kasir/Teknisi yang boleh menerima unit.",
    Action.ORDER_UPDATE: "Hanya Admin/Kasir/Teknisi yang boleh mengubah unit.",
    Action.ORDER_UPDATE_FINANCE: "Hanya Admin/Kasir yang boleh mengubah angka keuangan unit.",
    Action.ORDER_STATUS_CLOSING: "Akun ini tidak diizinkan mengubah status closing.",
    Action.ORDER_HANDOVER: "Hanya Admin/Kasir/Teknisi yang boleh mencatat pengambilan unit.",
    Action.ORDER_DELETE: "Hanya Admin yang boleh menghapus unit.",
    Action.PAYMENT_CREATE: "Hanya Admin/Kasir yang boleh mencatat pembayaran.",
    Action.PAYMENT_CANCEL: "Hanya Admin yang boleh membatalkan pembayaran.",
    Action.EXPENSE_WRITE: "Hanya Admin yang boleh mengelola beban.",
    Action.EXPENSE_DEBT_WRITE: "Hanya Admin yang boleh memproses atau melunasi Hutang Beban.",
    Action.KAS_ENTRY_WRITE: "Hanya Admin yang boleh menulis jurnal kas.",
    Action.KAS_CLOSE: "Hanya Admin yang boleh menutup periode kas.",
    Action.KAS_ASET_INJEKSI: "Hanya Admin yang boleh menambah dana Kas Aset.",
    Action.CUSTOMER_WRITE: "Hanya Admin/Kasir yang boleh menambah atau mengubah data pelanggan.",
    Action.CUSTOMER_DELETE: "Hanya Admin yang boleh menghapus data pelanggan.",
    Action.REFUND_DP: "Hanya Admin/Kasir yang boleh memproses refund DP.",
    Action.REFUND_GARANSI: "Refund klaim garansi adalah keputusan Admin.",
    Action.FAILED_CANCEL: "Hanya Admin/Kasir yang boleh membatalkan unit.",
    Action.SPAREPART_WRITE: "Hanya Super Admin/Admin/Admin Sparepart yang boleh mengelola sparepart.",
    Action.SPAREPART_DELETE: "Hanya Super Admin/Admin yang boleh menghapus sparepart.",
    Action.CLAIM_WRITE: "Hanya Admin/Kasir yang boleh mengelola klaim garansi.",
    Action.USER_MANAGE: "Hanya Admin yang boleh mengelola akun.",
}


def canonical_role(user) -> str:
    raw = (getattr(user, "role", "") or "").strip().upper()
    return ROLE_ALIASES.get(raw, ROLE_CUSTOM)


def is_monitoring(user) -> bool:
    """Role read-oriented (Q13): hanya melihat dan monitoring."""
    return canonical_role(user) in MONITORING_ROLES


def can(user, action: str) -> bool:
    allowed = AUTHORITY_MATRIX.get(action)
    if allowed is None:
        return False
    # Role read-oriented ditolak BLANKET-se-nya untuk setiap aksi yang tidak
    # ada di `MONITORING_READ_ACTIONS`. Jadi meskipun matriks keliru dan
    # mendaftarkan PENGELOLA untuk `KAS_CLOSE`, dia tetap ditolak.
    #
    # Pengecualian hanya untuk aksi BACA laporan. Spec Owner: Pengelola dan
    # Investor boleh "memfilter dan mengunduh laporan yang diizinkan". Itu
    # operasi baca, jadi tetap diizinkan tanpa mengubah sifat read-only mereka
    # terhadap transaksi.
    if is_monitoring(user) and action not in MONITORING_READ_ACTIONS:
        return False
    return canonical_role(user) in allowed


def allowed_roles(action: str) -> set:
    return set(AUTHORITY_MATRIX.get(action, set()))


def is_closing_status(status: str) -> bool:
    return (status or "").strip().upper() in CLOSING_STATUSES


def check(user, action: str, message: str = None) -> None:
    """Angkat 403 bila role tidak berwenang."""
    if not can(user, action):
        raise HTTPException(status_code=403, detail=message or DEFAULT_MESSAGES.get(
            action, "Aksi ini tidak diizinkan untuk akun Anda."))


def require_authority(action: str, message: str = None):
    """Dependency factory: `user = Depends(require_authority(Action.X))`."""

    def _dep(user=Depends(get_authenticated_user)):
        check(user, action, message)
        return user

    _dep.__name__ = "require_%s" % action.lower()
    return _dep


def require_any_authority(*actions: str, message: str = None):
    """Dependency factory: boleh bila punya SALAH SATU dari `actions`.

    Dipakai endpoint yang datanya sama tapi haknya berbeda per role, misalnya
    ekspor laporan: ManagedOLOLA boleh laporan bisnis, Investor boleh
    laporan investasinya. Endpoint tetap MENGEJAGANYA di backend, dan
    jenis laporan yang spesifik dicek lagi di dalam fungsi.
    """
    wanted = tuple(actions)

    def _dep(user=Depends(get_authenticated_user)):
        for aksi in wanted:
            if can(user, aksi):
                return user
        raise HTTPException(
            status_code=403,
            detail=message or ("Aksi ini tidak diizinkan untuk akun Anda."))
        return user

    _dep.__name__ = "require_any_%s" % "_or_".join(a.lower() for a in wanted)
    return _dep


def sanitize_finance_payload(user, payload: dict, current) -> tuple:
    """Role tanpa authority finance: pertahankan nilai lama (app.py:2079-2084).

    Owner memisahkan tiga kelompok angka keuangan pada unit:
      - harga / estimasi  -> Kasir boleh (itu bagian terima unit),
      - modal part/jasa/lain + tanpa_modal -> **hanya Admin**, karena modal
        menentukan Laba Kotor dan dengan begitu rumus laba. Kasir secara
        eksplisit "tidak boleh mengubah modal, rumus laba, pembagian hasil".
      - payment            -> seperti sebelumnya (masih lewat ORDER_UPDATE_FINANCE).

    Mengembalikan `(payload, daftar field yang diabaikan)`.
    """
    ignored = []
    kelompok = (
        (MODAL_FIELDS, Action.ORDER_UPDATE_MODAL),
        (FINANCE_FIELDS_LAINNYA, Action.ORDER_UPDATE_FINANCE),
    )
    for fields, aksi in kelompok:
        if can(user, aksi):
            continue
        for field in fields:
            if field in payload:
                payload[field] = getattr(current, field, None)
                ignored.append(field)
    return payload, ignored
