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
        CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, category TEXT DEFAULT 'General', amount REAL NOT NULL, expense_date TEXT NOT NULL, notes TEXT DEFAULT '', FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, supplier TEXT DEFAULT '', invoice_no TEXT DEFAULT '', total REAL NOT NULL, purchase_date TEXT NOT NULL, notes TEXT DEFAULT '', FOREIGN KEY(user_id) REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL, product_id INTEGER NOT NULL, qty REAL NOT NULL, cost_price REAL NOT NULL, FOREIGN KEY(purchase_id) REFERENCES purchases(id) ON DELETE CASCADE, FOREIGN KEY(product_id) REFERENCES products(id));
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL, amount REAL NOT NULL, method TEXT DEFAULT 'Cash', paid_at TEXT NOT NULL, notes TEXT DEFAULT '', FOREIGN KEY(bill_id) REFERENCES bills(id) ON DELETE CASCADE);
        """)
        cols={r["name"] for r in c.execute("PRAGMA table_info(bills)").fetchall()}
        for name, decl in [("gst_type","TEXT DEFAULT 'none'"),("cgst","REAL DEFAULT 0"),("sgst","REAL DEFAULT 0"),("igst","REAL DEFAULT 0"),("round_off","REAL DEFAULT 0")]:
            if name not in cols: c.execute("ALTER TABLE bills ADD COLUMN " + name + " " + decl)
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
        name=(d.get("name") or "").strip()
        price=float(d["price"]); stock=float(d.get("stock",0)); low=float(d.get("low_stock",5))
        if not name or price<0 or stock<0 or low<0: raise ValueError()
        with db() as c:
            c.execute("INSERT INTO products(user_id,name,sku,price,stock,low_stock) VALUES(?,?,?,?,?,?)",
            (session["uid"],name,d.get("sku",""),price,stock,low))
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
        payments=c.execute("SELECT amount,method,paid_at,notes FROM payments WHERE bill_id=? ORDER BY id",(bid,)).fetchall()
    return jsonify(bill=rowdict(b),items=[rowdict(x) for x in items],payments=[rowdict(x) for x in payments],settings=rowdict(s))

@app.post("/api/bills")
@auth
def create_bill():
    d=request.get_json(force=True); items=d.get("items",[])
    if not items: return jsonify(error="Add at least one item"),400
    uid=session["uid"]
    try:
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            clean=[]; subtotal=0
            for it in items:
                pid=int(it["product_id"]); qty=float(it["qty"])
                if qty<=0: raise ValueError()
                p=c.execute("SELECT * FROM products WHERE id=? AND user_id=?",(pid,uid)).fetchone()
                if not p or p["stock"]<qty: return jsonify(error=f"Insufficient stock for {p['name'] if p else 'product'}"),400
                amt=round(qty*float(p["price"]),2); subtotal+=amt
                clean.append((p,qty,amt))
            discount=max(0,float(d.get("discount",0))); rate=max(0,float(d.get("gst_rate",0)))
            if discount>subtotal: raise ValueError()
            taxable=round(subtotal-discount,2); gst_type=d.get("gst_type","none")
            if gst_type not in ("none","intra","inter"): raise ValueError()
            gst=round(taxable*rate/100,2) if gst_type!="none" else 0.0
            cgst=round(gst/2,2) if gst_type=="intra" else 0.0
            sgst=round(gst-cgst,2) if gst_type=="intra" else 0.0
            igst=gst if gst_type=="inter" else 0.0
            raw_total=taxable+gst; total=round(raw_total); round_off=round(total-raw_total,2)
            paid=float(d.get("paid",0))
            if paid<0 or paid>total: raise ValueError()
            if rate>100: raise ValueError()
            s=c.execute("SELECT bill_prefix FROM settings WHERE user_id=?",(uid,)).fetchone()
            count=c.execute("SELECT COUNT(*) n FROM bills WHERE user_id=?",(uid,)).fetchone()["n"]+1
            billno=f"{s['bill_prefix']}-{count:05d}"
            cur=c.execute("""INSERT INTO bills(user_id,bill_no,customer_name,customer_phone,subtotal,discount,gst_rate,gst_amount,total,paid,method,created_at,gst_type,cgst,sgst,igst,round_off)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(uid,billno,d.get("customer_name") or "Walk-in Customer",d.get("customer_phone",""),subtotal,discount,rate,gst,total,paid,d.get("method","Cash"),datetime.now().isoformat(timespec="seconds"),gst_type,cgst,sgst,igst,round_off))
            bid=cur.lastrowid
            if paid>0:
                c.execute("INSERT INTO payments(bill_id,amount,method,paid_at,notes) VALUES(?,?,?,?,?)",(bid,paid,d.get("method","Cash"),datetime.now().isoformat(timespec="seconds"),"Initial payment"))
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


@app.get("/api/customers")
@auth
def list_customers():
    with db() as c:
        rows=c.execute("SELECT id,name,phone FROM customers WHERE user_id=? ORDER BY name",(session["uid"],)).fetchall()
    return jsonify([rowdict(x) for x in rows])

@app.post("/api/customers")
@auth
def add_customer():
    d=request.get_json(force=True); name=(d.get("name") or "").strip()
    if not name: return jsonify(error="Customer name is required"),400
    with db() as c:
        cur=c.execute("INSERT INTO customers(user_id,name,phone) VALUES(?,?,?)",(session["uid"],name,d.get("phone","").strip()))
    return jsonify(ok=True,id=cur.lastrowid)

@app.get("/api/expenses")
@auth
def list_expenses():
    with db() as c:
        rows=c.execute("SELECT * FROM expenses WHERE user_id=? ORDER BY expense_date DESC,id DESC LIMIT 500",(session["uid"],)).fetchall()
    return jsonify([rowdict(x) for x in rows])

@app.post("/api/expenses")
@auth
def add_expense():
    d=request.get_json(force=True)
    try:
        amount=float(d.get("amount",0)); title=(d.get("title") or "").strip()
        if amount<=0 or not title: raise ValueError()
        with db() as c:
            cur=c.execute("INSERT INTO expenses(user_id,title,category,amount,expense_date,notes) VALUES(?,?,?,?,?,?)",(session["uid"],(d.get("title") or "").strip(),d.get("category","General"),amount,d.get("expense_date") or date.today().isoformat(),d.get("notes","")))
        return jsonify(ok=True,id=cur.lastrowid)
    except (ValueError,TypeError): return jsonify(error="Enter a valid expense amount"),400

@app.get("/api/purchases")
@auth
def list_purchases():
    with db() as c:
        rows=c.execute("SELECT * FROM purchases WHERE user_id=? ORDER BY purchase_date DESC,id DESC LIMIT 200",(session["uid"],)).fetchall()
    return jsonify([rowdict(x) for x in rows])

@app.post("/api/purchases")
@auth
def add_purchase():
    d=request.get_json(force=True); items=d.get("items",[])
    if not items: return jsonify(error="Add at least one purchase item"),400
    try:
        total=0; clean=[]
        with db() as c:
            for it in items:
                pid=int(it["product_id"]); qty=float(it["qty"]); cost=float(it["cost_price"])
                if qty<=0 or cost<0: raise ValueError()
                p=c.execute("SELECT id FROM products WHERE id=? AND user_id=?",(pid,session["uid"])).fetchone()
                if not p: raise ValueError()
                total+=qty*cost; clean.append((pid,qty,cost))
            cur=c.execute("INSERT INTO purchases(user_id,supplier,invoice_no,total,purchase_date,notes) VALUES(?,?,?,?,?,?)",(session["uid"],d.get("supplier",""),d.get("invoice_no",""),round(total,2),d.get("purchase_date") or date.today().isoformat(),d.get("notes","")))
            for pid,qty,cost in clean:
                c.execute("INSERT INTO purchase_items(purchase_id,product_id,qty,cost_price) VALUES(?,?,?,?)",(cur.lastrowid,pid,qty,cost))
                c.execute("UPDATE products SET stock=stock+? WHERE id=? AND user_id=?",(qty,pid,session["uid"]))
        return jsonify(ok=True,id=cur.lastrowid,total=round(total,2))
    except (ValueError,KeyError,TypeError): return jsonify(error="Invalid purchase details"),400

@app.post("/api/bills/<int:bid>/payments")
@auth
def add_bill_payment(bid):
    d=request.get_json(force=True)
    try:
        amount=float(d.get("amount",0))
        if amount<=0: raise ValueError()
        with db() as c:
            b=c.execute("SELECT * FROM bills WHERE id=? AND user_id=?",(bid,session["uid"])).fetchone()
            if not b: return jsonify(error="Bill not found"),404
            due=round(float(b["total"])-float(b["paid"]),2)
            if amount>due: return jsonify(error="Payment exceeds outstanding balance"),400
            c.execute("INSERT INTO payments(bill_id,amount,method,paid_at,notes) VALUES(?,?,?,?,?)",(bid,amount,d.get("method","Cash"),datetime.now().isoformat(timespec="seconds"),d.get("notes","")))
            c.execute("UPDATE bills SET paid=paid+? WHERE id=?",(amount,bid))
        return jsonify(ok=True,remaining=round(due-amount,2))
    except (ValueError,TypeError): return jsonify(error="Enter a valid payment amount"),400

@app.get("/api/reports")
@auth
def reports():
    uid=session["uid"]
    with db() as c:
        sales=c.execute("SELECT COALESCE(SUM(total),0) total,COALESCE(SUM(paid),0) received,COUNT(*) bills FROM bills WHERE user_id=?",(uid,)).fetchone()
        expenses=c.execute("SELECT COALESCE(SUM(amount),0) total FROM expenses WHERE user_id=?",(uid,)).fetchone()
        stock=c.execute("SELECT COUNT(*) products,COALESCE(SUM(stock*price),0) value FROM products WHERE user_id=?",(uid,)).fetchone()
        monthly=c.execute("SELECT substr(created_at,1,7) month,ROUND(SUM(total),2) sales,COUNT(*) bills FROM bills WHERE user_id=? GROUP BY substr(created_at,1,7) ORDER BY month DESC LIMIT 12",(uid,)).fetchall()
    return jsonify(sales=rowdict(sales),expenses=float(expenses["total"]),stock=rowdict(stock),monthly=[rowdict(x) for x in monthly],estimated_net=round(float(sales["total"])-float(expenses["total"]),2))


init_db()
if __name__ == "__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
