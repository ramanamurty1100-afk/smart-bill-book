# Smart Bill Book

A simple online billing and stock application for a small Indian shop. Built with Flask, SQLite, HTML, CSS and JavaScript.

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run `python -m venv .venv`
4. Activate it, then run `pip install -r requirements.txt`
5. Run `python app.py`
6. Open http://localhost:5000

Demo login: `demo` / `demo1234`

Create your own shop account using the login screen. The demo account is shared sample data; change the demo password or create your own account before real use.

## Deploy online (Render)
1. Create a GitHub repository and upload these project files.
2. Create a free web service on Render and connect the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Set environment variable `SECRET_KEY` to a long random secret.
6. IMPORTANT: SQLite on an ephemeral free web host may reset on redeploy/restart. For reliable permanent online storage, configure a persistent disk for `DATABASE_PATH` or migrate to a managed PostgreSQL database. Check the host's current free-tier and persistent-storage terms before relying on it.

## Notes
- Currency is INR (₹).
- Payments are recorded manually; no payment gateway is connected.
- GST is an optional percentage entered per bill; verify tax settings with your accountant.
- Stock is deducted when a bill is saved.
- This starter is intended for a small shop. Before production use, add HTTPS, backups, stronger account recovery, CSRF protection, rate limiting, audit logs, and persistent managed database storage.
