# Sistem Pemesanan Makanan — Cathering Bunda Hadmi

Aplikasi web demo berbasis Flask + SQLite yang mengikuti SKPL Kelompok 3.

## Fitur
### Pelanggan
- Melihat katalog, kategori, pencarian, detail, harga, dan ketersediaan menu.
- Menambahkan makanan ke keranjang, mengubah jumlah, menghapus item, dan menambahkan catatan penyesuaian.
- Checkout dengan nama, nomor telepon, alamat, dan tanggal pengantaran.
- Melihat ringkasan pesanan, melacak status menggunakan kode pesanan + nomor telepon, dan melihat riwayat menggunakan nomor telepon.

### Admin
- Login admin.
- Dashboard ringkasan.
- CRUD menu, harga, kategori, dan ketersediaan.
- Melihat pesanan, konfirmasi, dan mengubah status.
- Mengubah status pembayaran secara manual.
- Rekap penjualan per bulan.
- Pencatatan stok bahan masak.

## Menjalankan aplikasi
### Windows
1. Ekstrak ZIP.
2. Pastikan Python 3.10+ terpasang dan opsi **Add Python to PATH** aktif.
3. Klik dua kali `run.bat`.
4. Tunggu instalasi Flask selesai.
5. Buka `http://127.0.0.1:5000`.

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```

Atau manual:
```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Database SQLite dan data contoh dibuat otomatis pada saat pertama kali aplikasi dijalankan.

## Akun demo admin
- URL: `http://127.0.0.1:5000/admin/login`
- Username: `admin`
- Password: `admin123`

Ganti kredensial dan `SECRET_KEY` sebelum digunakan di lingkungan publik. Akun demo menggunakan password sederhana agar mudah diuji; belum cocok untuk deployment produksi.

## Catatan kesesuaian SKPL
- Pelanggan tidak wajib membuat akun. Pencarian riwayat dan pelacakan menggunakan nomor telepon serta kode pesanan.
- Pembayaran daring belum terhubung ke penyedia/payment gateway karena penyedia dan alurnya belum ditentukan dalam SKPL. Pilihan metode pembayaran dan statusnya disediakan sebagai simulasi/manual admin.
- Biaya pengantaran saat ini Rp0 karena aturan biaya belum ditentukan.
- Pengurangan stok bahan otomatis belum diterapkan; stok dicatat dan diperbarui manual oleh admin, sesuai hal yang masih perlu dikonfirmasi kepada klien.
- Data menu awal adalah data contoh dan dapat diganti dari dashboard admin.

## Struktur folder
```
bunda_hadmi/
├── app.py
├── requirements.txt
├── run.bat
├── run.sh
├── README.md
├── instance/             # database dibuat otomatis
├── static/
│   ├── css/style.css
│   └── js/main.js
└── templates/
    ├── base.html
    ├── index.html
    ├── menu_detail.html
    ├── cart.html
    ├── checkout.html
    ├── order_success.html
    ├── track.html
    ├── history.html
    ├── 404.html
    └── admin/
```


## Pembaruan fitur (November 2026)

- Akun awal `admin` otomatis menjadi **Super Admin** saat migrasi database.
- Super Admin dapat membuat dan menghapus akun Admin melalui menu **Kelola akun Admin**.
- Admin dapat mengelola menu, stok, dan pesanan, tetapi tidak dapat membuka laporan keuangan.
- Pelanggan dapat membatalkan pesanan hanya saat status masih **Menunggu Konfirmasi** melalui halaman lacak.
- Admin dan Super Admin dapat membatalkan pesanan yang belum selesai/berstatus akhir dengan mengisi alasan.
- Riwayat pembatalan menyimpan pelaku, alasan, dan waktu.
- Migrasi menambahkan kolom database secara bertahap; tabel dan pesanan lama tidak dihapus.

**Akun awal:** `admin` / `admin123`. Segera ganti password sebelum sistem digunakan di luar komputer pengembangan. Jalankan dengan `python app.py`.
