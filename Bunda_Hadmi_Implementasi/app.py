import os, sqlite3, uuid
from datetime import datetime, date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE = os.path.join(BASE_DIR, "instance", "bunda_hadmi.db")
os.makedirs(os.path.dirname(DATABASE), exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "ganti-secret-key-untuk-produksi")
app.config["DATABASE"] = DATABASE
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
PAYMENT_UPLOAD_DIR = os.path.join(BASE_DIR, "instance", "payment_uploads")
PAYMENT_IMAGE_TYPES = {
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".png": ("image/png",),
    ".webp": ("image/webp",),
}

STATUSES = ["Menunggu Konfirmasi", "Dikonfirmasi", "Diproses", "Siap Diantar", "Dalam Pengantaran", "Selesai", "Ditolak"]
CANCELLABLE_STATUSES = ["Menunggu Konfirmasi"]

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

def get_payment_settings():
    return get_db().execute("SELECT * FROM payment_settings WHERE id=1").fetchone()

def available_payment_methods(settings):
    methods = []
    if settings["bank_name"] and settings["bank_account"] and settings["bank_holder"]:
        methods.append("Transfer bank")
    if settings["qris_image"]:
        methods.append("QRIS")
    return methods

def save_payment_image(upload, prefix):
    extension = os.path.splitext(secure_filename(upload.filename or ""))[1].lower()
    allowed_mimes = PAYMENT_IMAGE_TYPES.get(extension)
    if not allowed_mimes or upload.mimetype not in allowed_mimes:
        raise ValueError("Unggah gambar JPG, PNG, atau WebP yang valid.")
    content = upload.read()
    upload.seek(0)
    valid_signature = (
        (extension in (".jpg", ".jpeg") and content.startswith(b"\xff\xd8\xff"))
        or (extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (extension == ".webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP")
    )
    if not valid_signature:
        raise ValueError("Isi file tidak sesuai dengan format gambar yang dipilih.")
    os.makedirs(PAYMENT_UPLOAD_DIR, exist_ok=True)
    filename = f"{prefix}-{uuid.uuid4().hex}{extension}"
    upload.save(os.path.join(PAYMENT_UPLOAD_DIR, filename))
    return filename

@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS admins (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS menu (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT,
      price INTEGER NOT NULL, category_id INTEGER, image TEXT, available INTEGER DEFAULT 1,
      FOREIGN KEY(category_id) REFERENCES categories(id)
    );
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
      customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL,
      delivery_date TEXT NOT NULL, notes TEXT, subtotal INTEGER NOT NULL,
      delivery_fee INTEGER DEFAULT 0, total INTEGER NOT NULL,
      status TEXT DEFAULT 'Menunggu Konfirmasi', payment_method TEXT DEFAULT 'Bayar saat konfirmasi',
      payment_status TEXT DEFAULT 'Belum dibayar', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS order_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, menu_id INTEGER,
      menu_name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price INTEGER NOT NULL,
      customization TEXT DEFAULT '', line_total INTEGER NOT NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY(menu_id) REFERENCES menu(id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS ingredients (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, quantity REAL DEFAULT 0,
      unit TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payment_settings (
      id INTEGER PRIMARY KEY CHECK (id=1), bank_name TEXT NOT NULL DEFAULT '',
      bank_account TEXT NOT NULL DEFAULT '', bank_holder TEXT NOT NULL DEFAULT '',
      qris_image TEXT NOT NULL DEFAULT ''
    );
    INSERT OR IGNORE INTO payment_settings(id) VALUES(1);
    """)
    # Migrasi aman: menambahkan kolom tanpa menghapus data lama.
    admin_columns = {row[1] for row in db.execute("PRAGMA table_info(admins)").fetchall()}
    if "role" not in admin_columns:
        db.execute("ALTER TABLE admins ADD COLUMN role TEXT NOT NULL DEFAULT 'super_admin'")
    order_columns = {row[1] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
    for column, definition in [
        ("cancelled_by", "TEXT"),
        ("cancellation_reason", "TEXT"),
        ("cancelled_at", "TEXT"),
        ("payment_proof", "TEXT"),
        ("payment_submitted_at", "TEXT"),
    ]:
        if column not in order_columns:
            db.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")

    admin = db.execute("SELECT id FROM admins WHERE username='admin'").fetchone()
    if not admin:
        # Demo credentials. Change before deployment.
        db.execute("INSERT INTO admins(username,password,role) VALUES(?,?,?)", ("admin", generate_password_hash("admin123"), "super_admin"))
    if db.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        db.executemany("INSERT INTO categories(name) VALUES(?)", [("Paket Nasi",), ("Lauk & Sayur",), ("Snack Box",), ("Minuman",)])
    if db.execute("SELECT COUNT(*) FROM menu").fetchone()[0] == 0:
        cats = {r[1]: r[0] for r in db.execute("SELECT id,name FROM categories")}
        samples = [
          ("Nasi Box Ayam Bakar", "Nasi putih, ayam bakar, sambal, lalapan, dan kerupuk.", 25000, cats["Paket Nasi"], "🍱", 1),
          ("Nasi Box Ayam Kremes", "Nasi putih dengan ayam kremes, sambal, dan lalapan.", 27000, cats["Paket Nasi"], "🍗", 1),
          ("Nasi Box Rendang", "Nasi putih, rendang sapi, tumis sayur, dan sambal.", 32000, cats["Paket Nasi"], "🍛", 1),
          ("Paket Nasi Liwet", "Nasi liwet gurih dengan lauk pilihan dan pelengkap.", 28000, cats["Paket Nasi"], "🍚", 1),
          ("Risoles Mayo", "Risoles isi smoked beef, telur, dan saus mayo.", 5000, cats["Snack Box"], "🥟", 1),
          ("Pastel Sayur", "Pastel renyah dengan isian sayuran.", 4000, cats["Snack Box"], "🥠", 1),
          ("Puding Cokelat", "Puding cokelat lembut dalam cup.", 6000, cats["Snack Box"], "🍮", 1),
          ("Es Teh Manis", "Teh segar dengan es batu.", 5000, cats["Minuman"], "🧋", 1),
        ]
        db.executemany("INSERT INTO menu(name,description,price,category_id,image,available) VALUES(?,?,?,?,?,?)", samples)
    if db.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0] == 0:
        db.executemany("INSERT INTO ingredients(name,quantity,unit,updated_at) VALUES(?,?,?,?)", [
          ("Beras", 25, "kg", datetime.now().isoformat(timespec="minutes")),
          ("Ayam", 12, "kg", datetime.now().isoformat(timespec="minutes")),
          ("Minyak goreng", 8, "liter", datetime.now().isoformat(timespec="minutes")),
        ])
    db.commit()
    db.close()

@app.template_filter("rupiah")
def rupiah(value):
    return "Rp{:,.0f}".format(value or 0).replace(",", ".")

@app.template_filter("menu_photo")
def menu_photo(item):
    image = item["image"] if "image" in item.keys() else ""
    if image and (image.startswith("https://") or image.startswith("/static/")):
        return image

    name = (item["name"] or "").lower()
    photo_by_name = [
        ("ayam bakar", "photo-1604908176997-125f25cc6f3d"),
        ("ayam kremes", "photo-1626082927389-6cd097cdc6ec"),
        ("rendang", "photo-1603894584373-5ac82b2ae398"),
        ("liwet", "photo-1512058564366-18510be2db19"),
        ("risoles", "photo-1601050690597-df0568f70950"),
        ("pastel", "photo-1601050690117-94f5f6fa8bd7"),
        ("puding", "photo-1488477181946-6428a0291777"),
        ("teh", "photo-1556679343-c7306c1976bc"),
    ]
    photo_id = next((photo for keyword, photo in photo_by_name if keyword in name), "photo-1504674900247-0877df9cc836")
    return f"https://images.unsplash.com/{photo_id}?auto=format&fit=crop&w=900&q=85"

@app.context_processor
def inject_globals():
    return {"cart_count": sum(int(x.get("quantity", 0)) for x in session.get("cart", {}).values()), "now_date": date.today().isoformat()}

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Silakan login sebagai admin terlebih dahulu.", "warning")
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

def super_admin_required(fn):
    @wraps(fn)
    @admin_required
    def wrapper(*args, **kwargs):
        if session.get("admin_role") != "super_admin":
            flash("Fitur ini hanya dapat diakses Super Admin.", "danger")
            return redirect(url_for("admin_dashboard"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def index():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    selected = request.args.get("category", type=int)
    q = request.args.get("q", "").strip()
    sql = """SELECT menu.*, categories.name AS category_name FROM menu
             LEFT JOIN categories ON categories.id=menu.category_id WHERE menu.available=1"""
    params = []
    if selected:
        sql += " AND category_id=?"; params.append(selected)
    if q:
        sql += " AND (menu.name LIKE ? OR menu.description LIKE ?)"; params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY menu.id DESC"
    menus = db.execute(sql, params).fetchall()
    return render_template("index.html", menus=menus, categories=categories, selected=selected, q=q)

@app.route("/menu/<int:menu_id>")
def menu_detail(menu_id):
    item = get_db().execute("""SELECT menu.*, categories.name AS category_name FROM menu
      LEFT JOIN categories ON categories.id=menu.category_id WHERE menu.id=? AND available=1""", (menu_id,)).fetchone()
    if not item:
        flash("Menu tidak ditemukan atau sedang tidak tersedia.", "warning")
        return redirect(url_for("index"))
    return render_template("menu_detail.html", item=item)

@app.post("/cart/add/<int:menu_id>")
def add_to_cart(menu_id):
    item = get_db().execute("SELECT * FROM menu WHERE id=? AND available=1", (menu_id,)).fetchone()
    if not item:
        flash("Menu tidak tersedia.", "danger"); return redirect(url_for("index"))
    qty = max(1, min(99, request.form.get("quantity", 1, type=int)))
    customization = request.form.get("customization", "").strip()[:250]
    cart = session.get("cart", {})
    key = str(menu_id)
    if key in cart and cart[key].get("customization", "") == customization:
        cart[key]["quantity"] += qty
    else:
        if key in cart:
            key = f"{menu_id}_{len(cart)}"
        cart[key] = {"menu_id": menu_id, "name": item["name"], "price": item["price"],
                     "quantity": qty, "image": item["image"], "customization": customization}
    session["cart"] = cart
    flash(f"{item['name']} ditambahkan ke keranjang.", "success")
    return redirect(request.referrer or url_for("index"))

@app.route("/keranjang")
def cart():
    return render_template("cart.html", cart=session.get("cart", {}))

@app.post("/cart/update")
def update_cart():
    cart_data = session.get("cart", {})
    for key in list(cart_data.keys()):
        qty = request.form.get(f"qty_{key}", type=int)
        if qty is None or qty <= 0:
            cart_data.pop(key, None)
        else:
            cart_data[key]["quantity"] = min(qty, 99)
    session["cart"] = cart_data
    flash("Keranjang berhasil diperbarui.", "success")
    return redirect(url_for("cart"))

@app.post("/cart/remove/<key>")
def remove_cart_item(key):
    cart_data = session.get("cart", {})
    cart_data.pop(key, None)
    session["cart"] = cart_data
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    cart_data = session.get("cart", {})
    if not cart_data:
        flash("Keranjang masih kosong.", "warning"); return redirect(url_for("index"))
    subtotal = sum(x["price"] * x["quantity"] for x in cart_data.values())
    payment_settings = get_payment_settings()
    payment_methods = available_payment_methods(payment_settings)
    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()
        delivery_date = request.form.get("delivery_date", "").strip()
        notes = request.form.get("notes", "").strip()
        payment_method = request.form.get("payment_method", "")
        errors = []
        if len(name) < 2: errors.append("Nama harus diisi minimal 2 karakter.")
        if len(phone) < 8: errors.append("Nomor telepon belum valid.")
        if len(address) < 8: errors.append("Alamat pengantaran harus diisi dengan lengkap.")
        try:
            parsed = date.fromisoformat(delivery_date)
            if parsed < date.today(): errors.append("Tanggal pengantaran tidak boleh di masa lalu.")
        except ValueError:
            errors.append("Tanggal pengantaran wajib dipilih.")
        if payment_method not in payment_methods:
            errors.append("Pilih metode pembayaran yang sudah dikonfigurasi oleh Admin.")
        if errors:
            for e in errors: flash(e, "danger")
            return render_template("checkout.html", cart=cart_data, subtotal=subtotal, form=request.form,
                                   payment_settings=payment_settings, payment_methods=payment_methods)
        db = get_db()
        ids = [x["menu_id"] for x in cart_data.values()]
        placeholders = ",".join("?" for _ in ids)
        available = db.execute(f"SELECT id,name,price FROM menu WHERE available=1 AND id IN ({placeholders})", ids).fetchall()
        available_ids = {r["id"] for r in available}
        if any(x["menu_id"] not in available_ids for x in cart_data.values()):
            flash("Ada menu yang sudah tidak tersedia. Periksa kembali keranjang.", "danger")
            return redirect(url_for("cart"))
        code = "BH" + datetime.now().strftime("%y%m%d%H%M%S") + str(os.urandom(2).hex()).upper()
        now = datetime.now().isoformat(timespec="minutes")
        cur = db.execute("""INSERT INTO orders(code,customer_name,phone,address,delivery_date,notes,subtotal,total,
          status,payment_method,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (code,name,phone,address,delivery_date,notes,subtotal,subtotal,"Menunggu Konfirmasi",payment_method,
           "Belum dibayar",now))
        order_id = cur.lastrowid
        for x in cart_data.values():
            db.execute("""INSERT INTO order_items(order_id,menu_id,menu_name,quantity,unit_price,customization,line_total)
              VALUES(?,?,?,?,?,?,?)""", (order_id,x["menu_id"],x["name"],x["quantity"],x["price"],
              x.get("customization",""),x["price"]*x["quantity"]))
        db.commit()
        session["cart"] = {}
        session["last_order_code"] = code
        return redirect(url_for("order_success", code=code))
    return render_template("checkout.html", cart=cart_data, subtotal=subtotal, form={},
                           payment_settings=payment_settings, payment_methods=payment_methods)

@app.route("/pesanan/berhasil/<code>")
def order_success(code):
    order = get_db().execute("SELECT * FROM orders WHERE code=?", (code,)).fetchone()
    if not order: return redirect(url_for("index"))
    return render_template("order_success.html", order=order, payment_settings=get_payment_settings())

@app.route("/lacak", methods=["GET", "POST"])
def track_order():
    order = None
    items = []
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        phone = request.form.get("phone", "").strip()
        order = get_db().execute("SELECT * FROM orders WHERE code=? AND phone=?", (code,phone)).fetchone()
        if order:
            items = get_db().execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
        else:
            flash("Pesanan tidak ditemukan. Periksa kode pesanan dan nomor telepon.", "danger")
    return render_template("track.html", order=order, items=items,
                           cancellable_statuses=CANCELLABLE_STATUSES,
                           payment_settings=get_payment_settings())

@app.post("/pesanan/bukti/<code>")
def submit_payment_proof(code):
    phone = request.form.get("phone", "").strip()
    order = get_db().execute("SELECT * FROM orders WHERE code=? AND phone=?", (code, phone)).fetchone()
    if not order:
        flash("Pesanan tidak ditemukan. Periksa kode pesanan dan nomor telepon.", "danger")
        return redirect(url_for("track_order"))
    items = get_db().execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
    if order["payment_method"] not in ("Transfer bank", "QRIS"):
        flash("Unggah bukti hanya tersedia untuk pembayaran transfer bank atau QRIS.", "warning")
    elif order["payment_status"] == "Lunas":
        flash("Pembayaran pesanan ini sudah diverifikasi lunas.", "warning")
    elif order["status"] in ("Dibatalkan", "Ditolak", "Selesai"):
        flash("Bukti pembayaran tidak dapat dikirim untuk pesanan berstatus akhir.", "warning")
    else:
        upload = request.files.get("payment_proof")
        if not upload or not upload.filename:
            flash("Pilih file bukti pembayaran terlebih dahulu.", "danger")
        else:
            try:
                filename = save_payment_image(upload, "proof")
            except ValueError as error:
                flash(str(error), "danger")
            else:
                db = get_db()
                result = db.execute("""UPDATE orders SET payment_proof=?, payment_submitted_at=?,
                                       payment_status='Menunggu verifikasi'
                                       WHERE id=? AND payment_status!='Lunas'
                                         AND status NOT IN ('Dibatalkan','Ditolak','Selesai')""",
                                    (filename, datetime.now().isoformat(timespec="minutes"), order["id"]))
                db.commit()
                order = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
                if result.rowcount == 1:
                    flash("Bukti pembayaran terkirim. Admin akan memeriksa pembayaranmu.", "success")
                else:
                    flash("Status pesanan berubah. Bukti pembayaran tidak dapat dikirim.", "warning")
    return render_template("track.html", order=order, items=items,
                           cancellable_statuses=CANCELLABLE_STATUSES,
                           payment_settings=get_payment_settings())

@app.get("/pembayaran/qris/<filename>")
def payment_qris_image(filename):
    settings = get_payment_settings()
    if filename != settings["qris_image"]:
        return "", 404
    return send_from_directory(PAYMENT_UPLOAD_DIR, filename)

@app.post("/pesanan/batal/<code>")
def customer_cancel_order(code):
    phone = request.form.get("phone", "").strip()
    reason = request.form.get("reason", "").strip()[:500] or "Dibatalkan oleh pelanggan"
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE code=? AND phone=?", (code, phone)).fetchone()
    if not order:
        flash("Pesanan tidak ditemukan. Periksa kode pesanan dan nomor telepon.", "danger")
        return redirect(url_for("track_order"))
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
    if order["status"] not in CANCELLABLE_STATUSES:
        flash(f"Pesanan berstatus {order['status']} tidak dapat dibatalkan pelanggan. "
              "Pembatalan hanya tersedia saat Menunggu Konfirmasi.", "warning")
        return render_template("track.html", order=order, items=items,
                               cancellable_statuses=CANCELLABLE_STATUSES,
                               payment_settings=get_payment_settings())
    result = db.execute("""UPDATE orders SET status='Dibatalkan', cancelled_by='Pelanggan',
                           cancellation_reason=?, cancelled_at=?
                           WHERE id=? AND status='Menunggu Konfirmasi'""",
                        (reason, datetime.now().isoformat(timespec="minutes"), order["id"]))
    if result.rowcount != 1:
        order = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
        flash(f"Pesanan berstatus {order['status']} tidak dapat dibatalkan pelanggan. "
              "Pembatalan hanya tersedia saat Menunggu Konfirmasi.", "warning")
        return render_template("track.html", order=order, items=items,
                               cancellable_statuses=CANCELLABLE_STATUSES,
                               payment_settings=get_payment_settings())
    db.commit()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order["id"],)).fetchone()
    flash("Pesanan berhasil dibatalkan.", "success")
    return render_template("track.html", order=order, items=items,
                           cancellable_statuses=CANCELLABLE_STATUSES,
                           payment_settings=get_payment_settings())

@app.route("/riwayat", methods=["GET", "POST"])
def order_history():
    orders = []
    phone = ""
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        if len(phone) >= 8:
            orders = get_db().execute("SELECT * FROM orders WHERE phone=? ORDER BY id DESC", (phone,)).fetchall()
        else: flash("Masukkan nomor telepon yang valid.", "warning")
    return render_template("history.html", orders=orders, phone=phone)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        admin = get_db().execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password"], password):
            session["admin_id"] = admin["id"]; session["admin_username"] = admin["username"]; session["admin_role"] = admin["role"]
            return redirect(url_for("admin_dashboard"))
        flash("Username atau password salah.", "danger")
    return render_template("admin/login.html")

@app.get("/admin/logout")
def admin_logout():
    session.pop("admin_id", None); session.pop("admin_username", None); session.pop("admin_role", None)
    flash("Anda telah keluar dari dashboard.", "success")
    return redirect(url_for("index"))

@app.get("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
      "today": db.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=date('now','localtime')").fetchone()[0],
      "pending": db.execute("SELECT COUNT(*) FROM orders WHERE status='Menunggu Konfirmasi'").fetchone()[0],
      "processing": db.execute("SELECT COUNT(*) FROM orders WHERE status IN ('Dikonfirmasi','Diproses','Siap Diantar','Dalam Pengantaran')").fetchone()[0],
    }
    if session.get("admin_role") == "super_admin":
        stats["revenue"] = db.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status='Selesai'").fetchone()[0]
    recent = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 7").fetchall()
    return render_template("admin/dashboard.html", stats=stats, recent=recent)

@app.route("/admin/menu", methods=["GET", "POST"])
@admin_required
def admin_menu():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name","").strip()
        desc = request.form.get("description","").strip()
        price = request.form.get("price",0,type=int)
        category_id = request.form.get("category_id",type=int)
        image = request.form.get("image", "").strip()[:500]
        available = 1 if request.form.get("available") else 0
        menu_id = request.form.get("menu_id",type=int)
        if len(name) < 2 or price < 1:
            flash("Nama menu dan harga wajib diisi dengan benar.", "danger")
        elif menu_id:
            db.execute("UPDATE menu SET name=?,description=?,price=?,category_id=?,image=?,available=? WHERE id=?",
                       (name,desc,price,category_id,image,available,menu_id))
            db.commit(); flash("Menu berhasil diperbarui.", "success")
        else:
            db.execute("INSERT INTO menu(name,description,price,category_id,image,available) VALUES(?,?,?,?,?,?)",
                       (name,desc,price,category_id,image,available))
            db.commit(); flash("Menu baru berhasil ditambahkan.", "success")
        return redirect(url_for("admin_menu"))
    menus = db.execute("""SELECT menu.*,categories.name category_name FROM menu LEFT JOIN categories
                         ON categories.id=menu.category_id ORDER BY menu.id DESC""").fetchall()
    categories = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    edit_id = request.args.get("edit",type=int)
    editing = db.execute("SELECT * FROM menu WHERE id=?", (edit_id,)).fetchone() if edit_id else None
    return render_template("admin/menu.html", menus=menus, categories=categories, editing=editing)

@app.post("/admin/menu/delete/<int:menu_id>")
@admin_required
def delete_menu(menu_id):
    db=get_db(); db.execute("DELETE FROM menu WHERE id=?", (menu_id,)); db.commit()
    flash("Menu berhasil dihapus.", "success"); return redirect(url_for("admin_menu"))

@app.route("/admin/pembayaran", methods=["GET", "POST"])
@admin_required
def admin_payment_settings():
    db = get_db()
    settings = get_payment_settings()
    if request.method == "POST":
        bank_name = request.form.get("bank_name", "").strip()[:80]
        bank_account = request.form.get("bank_account", "").strip()[:40]
        bank_holder = request.form.get("bank_holder", "").strip()[:100]
        qris_image = "" if request.form.get("remove_qris") else settings["qris_image"]
        upload = request.files.get("qris_image")
        if upload and upload.filename:
            try:
                qris_image = save_payment_image(upload, "qris")
            except ValueError as error:
                flash(str(error), "danger")
                return render_template("admin/payment_settings.html", settings=settings)
        db.execute("""UPDATE payment_settings
                      SET bank_name=?, bank_account=?, bank_holder=?, qris_image=?
                      WHERE id=1""", (bank_name, bank_account, bank_holder, qris_image))
        db.commit()
        flash("Informasi pembayaran berhasil disimpan.", "success")
        return redirect(url_for("admin_payment_settings"))
    return render_template("admin/payment_settings.html", settings=settings)

@app.get("/admin/bukti-pembayaran/<filename>")
@admin_required
def admin_payment_proof(filename):
    proof = get_db().execute(
        "SELECT 1 FROM orders WHERE payment_proof=?", (filename,)
    ).fetchone()
    if not proof:
        return "", 404
    return send_from_directory(PAYMENT_UPLOAD_DIR, filename)

@app.route("/admin/pesanan")
@admin_required
def admin_orders():
    status = request.args.get("status","")
    sql="SELECT * FROM orders"; params=[]
    if status in STATUSES: sql += " WHERE status=?"; params.append(status)
    sql += " ORDER BY id DESC"
    orders=get_db().execute(sql,params).fetchall()
    return render_template("admin/orders.html", orders=orders, statuses=STATUSES, selected=status)

@app.route("/admin/pesanan/<int:order_id>", methods=["GET","POST"])
@admin_required
def admin_order_detail(order_id):
    db=get_db()
    order=db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: flash("Pesanan tidak ditemukan.", "warning"); return redirect(url_for("admin_orders"))
    if request.method=="POST":
        status=request.form.get("status")
        payment_status=request.form.get("payment_status")
        if order["status"] in ["Selesai", "Dibatalkan", "Ditolak"]:
            flash("Pesanan dengan status akhir tidak dapat diubah lagi.", "warning")
        elif status not in STATUSES:
            flash("Status tidak valid.", "danger")
        else:
            db.execute("UPDATE orders SET status=?,payment_status=? WHERE id=?",
                       (status,payment_status if payment_status in ["Belum dibayar","Menunggu verifikasi","Lunas"] else order["payment_status"],order_id))
            db.commit(); flash("Status pesanan berhasil diperbarui.", "success")
        return redirect(url_for("admin_order_detail",order_id=order_id))
    items=db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    return render_template("admin/order_detail.html", order=order, items=items, statuses=STATUSES)

@app.post("/admin/pesanan/<int:order_id>/batal")
@admin_required
def admin_cancel_order(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        flash("Pesanan tidak ditemukan.", "warning")
        return redirect(url_for("admin_orders"))
    if order["status"] in ["Selesai", "Dibatalkan", "Ditolak"]:
        flash("Pesanan yang sudah selesai atau berstatus akhir tidak dapat dibatalkan lagi.", "warning")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    reason = request.form.get("reason", "").strip()
    if len(reason) < 3:
        flash("Alasan pembatalan wajib diisi minimal 3 karakter.", "danger")
        return redirect(url_for("admin_order_detail", order_id=order_id))
    actor = "Super Admin" if session.get("admin_role") == "super_admin" else "Admin"
    db.execute("""UPDATE orders SET status='Dibatalkan', cancelled_by=?, cancellation_reason=?,
                  cancelled_at=? WHERE id=?""",
               (f"{actor}: {session.get('admin_username')}", reason[:500],
                datetime.now().isoformat(timespec="minutes"), order_id))
    db.commit()
    flash("Pesanan berhasil dibatalkan.", "success")
    return redirect(url_for("admin_order_detail", order_id=order_id))

@app.route("/admin/laporan")
@super_admin_required
def admin_reports():
    db=get_db()
    month=request.args.get("month",datetime.now().strftime("%Y-%m"))
    orders=db.execute("SELECT * FROM orders WHERE substr(created_at,1,7)=? ORDER BY id DESC",(month,)).fetchall()
    revenue=sum(o["total"] for o in orders if o["status"]=="Selesai")
    completed=sum(1 for o in orders if o["status"]=="Selesai")
    return render_template("admin/reports.html",orders=orders,month=month,revenue=revenue,completed=completed)

@app.route("/admin/stok", methods=["GET","POST"])
@admin_required
def admin_inventory():
    db=get_db()
    if request.method=="POST":
        name=request.form.get("name","").strip()
        quantity=request.form.get("quantity",0,type=float)
        unit=request.form.get("unit","").strip()
        item_id=request.form.get("item_id",type=int)
        if not name or quantity < 0 or not unit:
            flash("Lengkapi nama, jumlah, dan satuan stok.", "danger")
        elif item_id:
            db.execute("UPDATE ingredients SET name=?,quantity=?,unit=?,updated_at=? WHERE id=?",
                       (name,quantity,unit,datetime.now().isoformat(timespec="minutes"),item_id))
            db.commit(); flash("Stok diperbarui.", "success")
        else:
            db.execute("INSERT INTO ingredients(name,quantity,unit,updated_at) VALUES(?,?,?,?)",
                       (name,quantity,unit,datetime.now().isoformat(timespec="minutes")))
            db.commit(); flash("Bahan berhasil ditambahkan.", "success")
        return redirect(url_for("admin_inventory"))
    items=db.execute("SELECT * FROM ingredients ORDER BY name").fetchall()
    edit_id=request.args.get("edit",type=int)
    editing=db.execute("SELECT * FROM ingredients WHERE id=?",(edit_id,)).fetchone() if edit_id else None
    return render_template("admin/inventory.html",items=items,editing=editing)

@app.post("/admin/stok/delete/<int:item_id>")
@admin_required
def delete_ingredient(item_id):
    db=get_db(); db.execute("DELETE FROM ingredients WHERE id=?",(item_id,)); db.commit()
    return redirect(url_for("admin_inventory"))

@app.route("/admin/akun", methods=["GET", "POST"])
@super_admin_required
def admin_accounts():
    db = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3 or len(password) < 8:
            flash("Username minimal 3 karakter dan password minimal 8 karakter.", "danger")
        else:
            try:
                db.execute("INSERT INTO admins(username,password,role) VALUES(?,?,?)",
                           (username, generate_password_hash(password), "admin"))
                db.commit()
                flash("Akun Admin berhasil dibuat.", "success")
            except sqlite3.IntegrityError:
                flash("Username sudah digunakan. Pilih username lain.", "danger")
        return redirect(url_for("admin_accounts"))
    accounts = db.execute("SELECT id,username,role FROM admins ORDER BY id").fetchall()
    return render_template("admin/accounts.html", accounts=accounts)

@app.post("/admin/akun/<int:admin_id>/hapus")
@super_admin_required
def delete_admin_account(admin_id):
    if admin_id == session.get("admin_id"):
        flash("Akun yang sedang digunakan tidak dapat dihapus.", "warning")
        return redirect(url_for("admin_accounts"))
    db = get_db()
    target = db.execute("SELECT id,role FROM admins WHERE id=?", (admin_id,)).fetchone()
    if not target:
        flash("Akun tidak ditemukan.", "warning")
    elif target["role"] == "super_admin":
        flash("Akun Super Admin tidak dapat dihapus dari halaman ini.", "warning")
    else:
        db.execute("DELETE FROM admins WHERE id=?", (admin_id,))
        db.commit()
        flash("Akun Admin berhasil dihapus.", "success")
    return redirect(url_for("admin_accounts"))

@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404

@app.errorhandler(413)
def upload_too_large(_):
    return "Ukuran file terlalu besar. Batas unggahan adalah 5 MB.", 413

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=5000)
