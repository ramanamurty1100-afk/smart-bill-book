import os, sqlite3, secrets
from datetime import datetime, date
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")
DB = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "billbook.db"))

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY, shop_name TEXT DEFAULT 'My Shop', address TEXT DEFAULT '', phone TEXT DEFAULT '', gstin TEXT DEFAULT '', footer TEXT DEFAULT 'Thank you! Visit again.', bill_prefix TEXT DEFAULT 'INV');
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, sku TEXT DEFAULT '', price REAL NOT NULL, stock REAL NOT NULL DEFAULT 0, low_stock REAL NOT NULL DEFAULT 5, FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, phone TEXT DEFAULT '', FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS bills(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, bill_no TEXT NOT NULL, customer_name TEXT DEFAULT 'Walk-in Customer', customer_phone TEXT DEFAULT '', subtotal REAL NOT NULL, discount REAL DEFAULT 0, gst_rate REAL DEFAULT 0, gst_amount REAL DEFAULT 0, total REAL NOT NULL, paid REAL DEFAULT 0, method TEXT DEFAULT 'Cash', created_at TEXT NOT NULL, UNIQUE(user_id,bill_no), FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS bill_items(id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL, product_id INTEGER, name TEXT NOT NULL, qty REAL NOT NULL, price REAL NOT NULL, amount REAL NOT NULL, FOREIGN KEY(bill_id) REFERENCES bills(id) ON DELETE CASCADE);
        """)
        if not c.execute("SELECT id FROM users LIMIT 1").fetchone():
            uid = c.execute("INSERT INTO users(username,password) VALUES(?,?)", ("demo", generate_password_hash("demo1234"))).lastrowid
            c.execute("INSERT INTO settings(user_id,shop_name) VALUES(?,?)", (uid,"Demo Kirana Store"))
            c.executemany("INSERT INTO products(user_id,name,sku,price,stock) VALUES(?,?,?,?,?)", [
                (uid,"Rice 1 kg","RICE1",65,80),(uid,"Sugar 1 kg","SUGAR1",48,50),(uid,"Cooking Oil 1 L","OIL1",145,30),(uid,"Milk 500 ml","MILK500",30,40)
            ])

def auth(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("uid"): return jsonify(error="Please log in"), 401
        return fn(*a, **kw)
    return wrapper

def rowdict(r): return dict(r) if r else None

@app.get("/")
def home(): return send_from_directory("static", "index.html")

@app.post("/api/login")
def login():
    d=request.get_json(force=True); u=(d.get("username") or "").strip()
    with db() as c: r=c.execute("SELECT * FROM users WHERE username=?",(u,)).fetchone()
    if not r or not check_password_hash(r["password"], d.get("password","")): return jsonify(error="Invalid username or password"),401
    session.clear(); session["uid"]=r["id"]
    return jsonify(ok=True,username=u)

@app.post("/api/register")
def register():
    d=request.get_json(force=True); u=(d.get("username") or "").strip(); p=d.get("password","")
    if len(u)<3 or len(p)<8: return jsonify(error="Username must be 3+ characters and password 8+ characters"),400
    try:
        with db() as c:
            uid=c.execute("INSERT INTO users(username,password) VALUES(?,?)",(u,generate_password_hash(p))).lastrowid
            c.execute("INSERT INTO settings(user_id,shop_name) VALUES(?,?)",(uid,"My Shop"))
        session.clear(); session["uid"]=uid
        return jsonify(ok=True)
    except sqlite3.IntegrityError: return jsonify(error="Username already exists"),409

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
@auth
def me():
    with db() as c:
        s=c.execute("SELECT * FROM settings WHERE user_id=?",(session["uid"],)).fetchone()
    return jsonify(username=True, settings=rowdict(s))

@app.put("/api/settings")
@auth
def settings():
    d=request.get_json(force=True)
    with db() as c:
        c.execute("""UPDATE settings SET shop_name=?,address=?,phone=?,gstin=?,footer=?,bill_prefix=? WHERE user_id=?""",
        (d.get("shop_name","My Shop"),d.get("address",""),d.get("phone",""),d.get("gstin",""),d.get("footer","Thank you!"),d.get("bill_prefix","INV"),session["uid"]))
    return jsonify(ok=True)

@app.get("/api/products")
@auth
def products():
    with db() as c: rows=c.execute("SELECT * FROM products WHERE user_id=? ORDER BY name",(session["uid"],)).fetchall()
    return jsonify([rowdict(x) for x in rows])

@app.post("/api/products")
@auth
def add_product():
    d=request.get_json(force=True)
    try:
        with db() as c:
            c.execute("INSERT INTO products(user_id,name,sku,price,stock,low_stock) VALUES(?,?,?,?,?,?)",
            (session["uid"],d["name"].strip(),d.get("sku",""),float(d["price"]),float(d.get("stock",0)),float(d.get("low_stock",5))))
        return jsonify(ok=True)
    except (ValueError,KeyError): return jsonify(error="Enter valid product details"),400

@app.delete("/api/products/<int:pid>")
@auth
def delete_product(pid):
    with db() as c: c.execute("DELETE FROM products WHERE id=? AND user_id=?",(pid,session["uid"]))
    return jsonify(ok=True)

@app.get("/api/bills")
@auth
def bills():
    q=request.args.get("q","%")
    with db() as c:
        rows=c.execute("""SELECT * FROM bills WHERE user_id=? AND (bill_no LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ?) ORDER BY id DESC LIMIT 200""",
        (session["uid"],f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    return jsonify([rowdict(x) for x in rows])

@app.get("/api/bills/<int:bid>")
@auth
def bill_detail(bid):
    with db() as c:
        b=c.execute("SELECT * FROM bills WHERE id=? AND user_id=?",(bid,session["uid"])).fetchone()
        if not b: return jsonify(error="Bill not found"),404
        items=c.execute("SELECT * FROM bill_items WHERE bill_id=?",(bid,)).fetchall()
        s=c.execute("SELECT * FROM settings WHERE user_id=?",(session["uid"],)).fetchone()
    return jsonify(bill=rowdict(b),items=[rowdict(x) for x in items],settings=rowdict(s))

@app.post("/api/bills")
@auth
def create_bill():
    d=request.get_json(force=True); items=d.get("items",[])
    if not items: return jsonify(error="Add at least one item"),400
    uid=session["uid"]
    try:
        with db() as c:
            clean=[]; subtotal=0
            for it in items:
                pid=int(it["product_id"]); qty=float(it["qty"])
                if qty<=0: raise ValueError()
                p=c.execute("SELECT * FROM products WHERE id=? AND user_id=?",(pid,uid)).fetchone()
                if not p or p["stock"]<qty: return jsonify(error=f"Insufficient stock for {p['name'] if p else 'product'}"),400
                amt=round(qty*float(p["price"]),2); subtotal+=amt
                clean.append((p,qty,amt))
            discount=max(0,float(d.get("discount",0))); rate=max(0,float(d.get("gst_rate",0)))
            taxable=max(0,subtotal-discount); gst=round(taxable*rate/100,2); total=round(taxable+gst,2)
            paid=min(max(0,float(d.get("paid",0))),total)
            s=c.execute("SELECT bill_prefix FROM settings WHERE user_id=?",(uid,)).fetchone()
            count=c.execute("SELECT COUNT(*) n FROM bills WHERE user_id=?",(uid,)).fetchone()["n"]+1
            billno=f"{s['bill_prefix']}-{count:05d}"
            cur=c.execute("""INSERT INTO bills(user_id,bill_no,customer_name,customer_phone,subtotal,discount,gst_rate,gst_amount,total,paid,method,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(uid,billno,d.get("customer_name") or "Walk-in Customer",d.get("customer_phone",""),subtotal,discount,rate,gst,total,paid,d.get("method","Cash"),datetime.now().isoformat(timespec="seconds")))
            bid=cur.lastrowid
            for p,qty,amt in clean:
                c.execute("INSERT INTO bill_items(bill_id,product_id,name,qty,price,amount) VALUES(?,?,?,?,?,?)",(bid,p["id"],p["name"],qty,p["price"],amt))
                c.execute("UPDATE products SET stock=stock-? WHERE id=?",(qty,p["id"]))
        return jsonify(ok=True,id=bid,bill_no=billno)
    except (ValueError,KeyError,TypeError): return jsonify(error="Invalid bill details"),400

@app.get("/api/summary")
@auth
def summary():
    today=date.today().isoformat()
    with db() as c:
        sales=c.execute("SELECT COALESCE(SUM(total),0) v,COUNT(*) n FROM bills WHERE user_id=? AND date(created_at)=?",(session["uid"],today)).fetchone()
        due=c.execute("SELECT COALESCE(SUM(total-paid),0) v FROM bills WHERE user_id=?",(session["uid"],)).fetchone()
        low=c.execute("SELECT COUNT(*) n FROM products WHERE user_id=? AND stock<=low_stock",(session["uid"],)).fetchone()
    return jsonify(sales=float(sales["v"]),count=sales["n"],due=float(due["v"]),low=low["n"])

init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
