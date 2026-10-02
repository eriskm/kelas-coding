import sqlite3
import os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
DB_PATH = 'keuangan_praktek.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Tabel servis
    cur.execute('''
        CREATE TABLE IF NOT EXISTS servis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_user TEXT,
            device TEXT,
            harga_jual INTEGER DEFAULT 0,
            modal_part INTEGER DEFAULT 0,
            modal_jasa INTEGER DEFAULT 0,
            lain_lain INTEGER DEFAULT 0,
            laba_kotor INTEGER DEFAULT 0,
            status TEXT,
            teknisi TEXT
        )
    ''')
    # Tabel beban
    cur.execute('''
        CREATE TABLE IF NOT EXISTS beban (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kategori TEXT,
            nama_beban TEXT,
            nilai INTEGER DEFAULT 0
        )
    ''')
    # Tabel transaksi_tambahan
    cur.execute('''
        CREATE TABLE IF NOT EXISTS transaksi_tambahan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tanggal TEXT,
            uraian TEXT,
            jenis TEXT,
            nominal INTEGER DEFAULT 0
        )
    ''')
    # Tabel master_kas
    cur.execute('''
        CREATE TABLE IF NOT EXISTS master_kas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kas_kecil_laci INTEGER DEFAULT 0,
            kas_aset_pengelola INTEGER DEFAULT 0
        )
    ''')
    # Tabel arsip_servis
    cur.execute('''
        CREATE TABLE IF NOT EXISTS arsip_servis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_user TEXT,
            device TEXT,
            harga_jual INTEGER,
            laba_kotor INTEGER,
            status_final TEXT,
            tgl_arsip TEXT
        )
    ''')
    conn.commit()

@app.route('/update_servis/<int:id>', methods=['POST'])
def update_servis(id):
    """
    LOGIKA PERHITUNGAN LABA & UPDATE SERVIS
    Kloning dari Boss SF: Laba dihitung hanya jika status Cash.
    """
    data = request.json
    status = data.get('status')
    
    harga_jual = data.get('harga_jual', 0)
    modal_part = data.get('modal_part', 0)
    modal_jasa = data.get('modal_jasa', 0)
    lain_lain = data.get('lain_lain', 0)
    
    # 1. Hitung Laba
    if status == 'Cash':
        laba_final = harga_jual - modal_part - modal_jasa - lain_lain
    elif status == 'Selesai Klaim':
        harga_jual = 0
        laba_final = 0
    else:
        laba_final = 0

    conn = get_db()
    conn.execute('''
        UPDATE servis SET
            status = ?,
            harga_jual = ?,
            modal_part = ?,
            modal_jasa = ?,
            lain_lain = ?,
            laba_kotor = ?
        WHERE id = ?
    ''', (status, harga_jual, modal_part, modal_jasa, lain_lain, laba_final, id))
    conn.commit()
    
    return jsonify({"message": "Data berhasil diupdate", "laba_kotor": laba_final, "status": status})


@app.route('/milestone', methods=['GET'])
def milestone():
    """
    LOGIKA DASHBOARD & MILESTONE
    Menghitung pencapaian target Gaji & Operasional.
    """
    conn = get_db()
    
    # Laba Servis
    row_servis = conn.execute('''
        SELECT SUM(laba_kotor) as tot 
        FROM servis 
        WHERE status = 'Cash' 
        AND (modal_part > 0 OR modal_jasa > 0 OR lain_lain > 0)
    ''').fetchone()
    laba_servis = row_servis['tot'] or 0
    
    # Laba Tambahan
    row_tambahan = conn.execute('''
        SELECT SUM(CASE WHEN jenis = 'Masuk' THEN nominal ELSE -nominal END) as tot
        FROM transaksi_tambahan
        WHERE uraian != 'MODAL KAS KECIL (LACI)'
    ''').fetchone()
    laba_tambahan = row_tambahan['tot'] or 0
    
    laba_kotor = laba_servis + laba_tambahan
    
    # Total Beban
    row_gaji = conn.execute("SELECT SUM(nilai) as tot FROM beban WHERE LOWER(kategori) = 'gaji'").fetchone()
    gaji = row_gaji['tot'] or 0
    
    row_ops = conn.execute("SELECT SUM(nilai) as tot FROM beban WHERE LOWER(kategori) = 'operasional'").fetchone()
    ops = row_ops['tot'] or 0
    
    total_beban = gaji + ops
    laba_bersih = laba_kotor - total_beban
    
    # Penentuan Status Milestone
    if laba_kotor >= total_beban:
        status_text = "CTH! (LABA BERSIH)" if laba_kotor > total_beban else "CTO! (OPERASIONAL AMAN)"
    elif laba_kotor >= gaji:
        status_text = "CTS! (GAJI AMAN)"
    else:
        status_text = "OTW TARGET GAJI"
        
    return jsonify({
        "laba_kotor": laba_kotor,
        "gaji": gaji,
        "operasional": ops,
        "total_beban": total_beban,
        "laba_bersih": laba_bersih,
        "status_target": status_text
    })


@app.route('/tutup_buku', methods=['POST'])
def tutup_buku():
    """
    LOGIKA EKSEKUSI DB / TUTUP BUKU
    Pengarsipan unit yang closing, reset kas tambahan, split aset pengelola vs uang fisik laci.
    """
    data = request.json
    uang_fisik = data.get('uang_fisik', 0)
    total_saldo = data.get('total_saldo', 0)
    
    if uang_fisik > total_saldo:
        return jsonify({"error": "Uang fisik tidak boleh melebihi total saldo"}), 400
        
    kas_aset_baru = total_saldo - uang_fisik
    tgl_hari_ini = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db()
    
    # 1. Pindah Arsip
    data_servis = conn.execute("SELECT * FROM servis").fetchall()
    counter_arsip = 0
    for row in data_servis:
        stts = str(row['status']).strip().lower()
        if stts in ['cash', 'cancel', 'selesai klaim', 'garansi void', 'refund']:
            conn.execute('''
                INSERT INTO arsip_servis (nama_user, device, harga_jual, laba_kotor, status_final, tgl_arsip)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (row['nama_user'], row['device'], row['harga_jual'], row['laba_kotor'], stts.upper(), tgl_hari_ini))
            # Hapus dari tabel aktif
            conn.execute("DELETE FROM servis WHERE id = ?", (row['id'],))
            counter_arsip += 1
            
    # 2. Update Master Kas
    conn.execute('''
        INSERT INTO master_kas (kas_kecil_laci, kas_aset_pengelola)
        VALUES (?, ?)
    ''', (uang_fisik, kas_aset_baru))
    
    # 3. Reset Papan Tulis Tambahan
    conn.execute("DELETE FROM transaksi_tambahan")
    conn.execute('''
        INSERT INTO transaksi_tambahan (tanggal, uraian, jenis, nominal)
        VALUES (?, 'MODAL KAS KECIL (LACI)', 'Masuk', ?)
    ''', (tgl_hari_ini, uang_fisik))
    
    conn.commit()
    
    return jsonify({
        "message": "Tutup buku sukses",
        "jumlah_arsip": counter_arsip,
        "modal_laci_besok": uang_fisik,
        "aset_pengelola": kas_aset_baru
    })

if __name__ == '__main__':
    # Inisialisasi database sebelum aplikasi jalan
    init_db()
    print("[OK] Database dan sistem keuangan siap!")
    app.run(port=5000, debug=True)
