import pytest
from decimal import Decimal
from datetime import datetime
import models
import cash

def test_catat_modal_tidak_mencocokkan_entri_hantu_dengan_id_sama(db):
    """Memastikan catat_modal dan catat_modal_selisih menolak entri hantu yang memiliki
    ref_id sama tetapi no_servis berbeda (misal order lama terhapus).
    """
    # 1. Buat customer & user
    cust = models.Customer(name="Customer Test Ghost", phone="08123456789")
    db.add(cust)
    db.commit()
    
    # 2. Simulasikan adanya 'entri hantu' di database dengan ref_id = 9999
    # Entri ini milik order lama yang sudah dihapus bernama 'SV-GHOST-9999'
    ghost_part = models.KasEntry(
        layer=cash.LAYER_LACI,
        jenis="Keluar",
        kategori=cash.KATEGORI[cash.SUMBER_MODAL],
        nominal=Decimal("200000"),
        sumber=cash.SUMBER_MODAL,
        keterangan="Modal Part unit SV-GHOST-9999",
        ref_type="MODAL_PART",
        ref_id=9999,
        created_at=datetime(2026, 1, 1, 10, 0, 0)
    )
    db.add(ghost_part)
    db.commit()
    
    # 3. Sekarang buat order baru yang kebetulan memiliki ID = 9999 (atau no_servis beda)
    order = models.ServiceOrder(
        id=9999,
        no_servis="SV-REAL-2026-0001",
        customer_id=cust.id,
        device="Device Real",
        estimate=500000,
        final_price=500000,
        part_cost=100000,
        modal_jasa=50000,
        status="CASH"
    )
    db.add(order)
    db.commit()
    
    # 4. Panggil catat_modal
    # Karena ada proteksi no_servis, catat_modal TIDAK boleh menganggap ghost_part sebagai mutasi miliknya.
    # catat_modal HARUS mencatat Modal Part riil (100.000) dan Modal Jasa riil (50.000).
    res = cash.catat_modal(db, order, actor="Tester")
    db.commit()
    
    # Harus ada 2 mutasi baru: MODAL_PART (100k) dan MODAL_JASA (50k)
    part_entries = [m for m in res if m.get("ref_type") == "MODAL_PART"]
    jasa_entries = [m for m in res if m.get("ref_type") == "MODAL_JASA"]
    
    assert len(part_entries) == 1, "Modal part riil harus tetap dicatat keluar"
    assert part_entries[0]["nominal"] == Decimal("100000")
    assert "SV-REAL-2026-0001" in part_entries[0]["keterangan"]
    
    assert len(jasa_entries) == 1, "Modal jasa riil harus tetap dicatat keluar"
    assert jasa_entries[0]["nominal"] == Decimal("50000")
    assert "SV-REAL-2026-0001" in jasa_entries[0]["keterangan"]
    
    # 5. Panggil catat_modal_selisih
    # Karena modal sudah sesuai (100k part, 50k jasa), selisih harus 0 dan tidak boleh menghasilkan mutasi koreksi hantu
    selisih_res = cash.catat_modal_selisih(db, order, actor="Tester")
    db.commit()
    assert len(selisih_res) == 0, "Tidak boleh ada mutasi koreksi hantu"
    
    # Cleanup
    db.delete(order)
    db.delete(ghost_part)
    for m in res:
        db.query(models.KasEntry).filter(models.KasEntry.id == m["id"]).delete()
    db.delete(cust)
    db.commit()
