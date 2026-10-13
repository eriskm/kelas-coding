"""Auto-prune backup otomatis (backend/main.py::_prune_backups).

Backup otomatis dibuat tiap start aplikasi. Tanpa prune, folder project penuh
ratusan file. Prune hanya boleh menyentuh pola 'backup-servisku-*'; backup
bernama milik Owner (pre*, checkpoint*, archive*, lokal*) tidak boleh hilang.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import main  # noqa: E402


TERLINDUNGI = [
    "backup-preMigrasi-FM7-20261013-172841.db",
    "checkpoint-aman-tutupkas-20261013-174226.db",
    "checkpoint-ALUR-OK-20261012-154200.db",
    "archive-servisku-B-uat-p215-20261007-132643.db",
    "backup-lokal-preclean-20261008-170819.db",
]


def _buat(path, mtime):
    with open(path, "w") as f:
        f.write("x")
    os.utime(path, (mtime, mtime))


def test_prune_sisakan_10_terbaru():
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(25):
            _buat(os.path.join(tmp, "backup-servisku-20261001-%06d.db" % i), 1_700_000_000 + i)
        main._prune_backups(tmp, keep=10)
        auto = [n for n in os.listdir(tmp) if n.startswith("backup-servisku-")]
        assert len(auto) == 10
        # yang tersisa harus yang terbaru
        assert "backup-servisku-20261001-000024.db" in auto
        assert "backup-servisku-20261001-000000.db" not in auto


def test_prune_tidak_hapus_backup_bernama():
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(25):
            _buat(os.path.join(tmp, "backup-servisku-20261001-%06d.db" % i), 1_700_000_000 + i)
        for name in TERLINDUNGI:
            _buat(os.path.join(tmp, name), 1_690_000_000)  # lebih tua dari auto-backup
        main._prune_backups(tmp, keep=10)
        for name in TERLINDUNGI:
            assert os.path.exists(os.path.join(tmp, name)), name + " tidak boleh dihapus"


def test_prune_abaikan_file_bukan_database():
    with tempfile.TemporaryDirectory() as tmp:
        junk = os.path.join(tmp, "backup-servisku-catatan.txt")
        _buat(junk, 1_700_000_000)
        for i in range(15):
            _buat(os.path.join(tmp, "backup-servisku-20261001-%06d.db" % i), 1_700_000_000 + i)
        main._prune_backups(tmp, keep=10)
        assert os.path.exists(junk)


def test_prune_tidak_error_saat_folder_kosong():
    with tempfile.TemporaryDirectory() as tmp:
        main._prune_backups(tmp, keep=10)  # tidak boleh melempar exception
        assert os.listdir(tmp) == []
