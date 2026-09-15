import csv
import io
import os
import sqlite3
import json
import urllib.request
from datetime import datetime
from functools import wraps

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def notify_n8n(action, **payload):
    """Send optional automation events without breaking the core application."""
    webhook_url = os.environ.get("N8N_WEBHOOK_URL")
    if not webhook_url:
        return
    body = json.dumps({"action": action, **payload}).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-for-production"),
        DATABASE=os.path.join(app.instance_path, "events.db"),
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_error=None):
        connection = g.pop("db", None)
        if connection:
            connection.close()

    def init_db():
        schema = open(os.path.join(app.root_path, "schema.sql"), encoding="utf-8").read()
        db().executescript(schema)
        if not db().execute("SELECT id FROM users LIMIT 1").fetchone():
            db().executemany(
                "INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                [
                    ("Nowshera Admin", "admin@nowshera.test", generate_password_hash("Admin123!"), "admin"),
                    ("Demo Attendee", "attendee@nowshera.test", generate_password_hash("Attend123!"), "attendee"),
                ],
            )
            db().commit()

    with app.app_context():
        init_db()

    @app.context_processor
    def helpers():
        return {"current_user": getattr(g, "user", None), "today": datetime.now()}

    @app.before_request
    def load_user():
        g.user = db().execute("SELECT * FROM users WHERE id=?", (session.get("user_id", 0),)).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                flash("Please sign in to continue.", "error")
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("login"))
            if g.user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    def event_row(event_id):
        return db().execute("""
            SELECT e.*, COUNT(r.id) registrations, e.capacity-COUNT(r.id) places_left
            FROM events e LEFT JOIN registrations r ON r.event_id=e.id AND r.status='active'
            WHERE e.id=? GROUP BY e.id
        """, (event_id,)).fetchone()

    def validate_event(form, event_id=None):
        errors = []
        title, description = form.get("title", "").strip(), form.get("description", "").strip()
        location, event_date, event_time = form.get("location", "").strip(), form.get("event_date", ""), form.get("event_time", "")
        try:
            raw = form.get("capacity", "")
            capacity = int(raw)
            if str(capacity) != raw.strip() or capacity <= 0:
                raise ValueError
        except ValueError:
            capacity = 0
            errors.append("Capacity must be a positive whole number.")
        if not all([title, description, location, event_date, event_time]):
            errors.append("All event fields are required.")
        try:
            datetime.fromisoformat(f"{event_date}T{event_time}")
        except ValueError:
            errors.append("Enter a valid date and time.")
        if event_id:
            active = db().execute("SELECT COUNT(*) n FROM registrations WHERE event_id=? AND status='active'", (event_id,)).fetchone()["n"]
            if capacity < active:
                errors.append(f"Capacity cannot be below {active}, the current registration count.")
        return errors, (title, description, event_date, event_time, location, capacity)

    @app.route("/")
    def events():
        rows = db().execute("""
            SELECT e.*, COUNT(r.id) registrations, e.capacity-COUNT(r.id) places_left
            FROM events e LEFT JOIN registrations r ON r.event_id=e.id AND r.status='active'
            WHERE e.status='published' AND datetime(e.event_date || ' ' || e.event_time) > datetime('now','localtime')
            GROUP BY e.id ORDER BY e.event_date,e.event_time
        """).fetchall()
        return render_template("events.html", events=rows)

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if request.method == "POST":
            name, email, password = request.form.get("name", "").strip(), request.form.get("email", "").strip().lower(), request.form.get("password", "")
            if not name or "@" not in email or len(password) < 8:
                flash("Enter a name, valid email, and password of at least 8 characters.", "error")
            else:
                try:
                    db().execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,'attendee')", (name, email, generate_password_hash(password)))
                    db().commit()
                    flash("Account created. You can now sign in.", "success")
                    return redirect(url_for("login"))
                except sqlite3.IntegrityError:
                    flash("An account with that email already exists.", "error")
        return render_template("auth.html", mode="signup")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            user = db().execute("SELECT * FROM users WHERE email=?", (request.form.get("email", "").strip().lower(),)).fetchone()
            if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
                session.clear(); session["user_id"] = user["id"]
                return redirect(url_for("admin_dashboard") if user["role"] == "admin" else url_for("events"))
            flash("Incorrect email or password.", "error")
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    def logout():
        session.clear(); return redirect(url_for("events"))

    @app.route("/events/<int:event_id>")
    def event_detail(event_id):
        event = event_row(event_id)
        if not event or (g.user and g.user["role"] != "admin" and event["status"] != "published") or (not g.user and event["status"] != "published"):
            abort(404)
        registered = bool(g.user and db().execute("SELECT id FROM registrations WHERE event_id=? AND user_id=? AND status='active'", (event_id, g.user["id"])).fetchone())
        return render_template("event_detail.html", event=event, registered=registered)

    @app.post("/events/<int:event_id>/register")
    @login_required
    def register_event(event_id):
        if g.user["role"] != "attendee": abort(403)
        connection = db()
        connection.execute("BEGIN IMMEDIATE")
        event = event_row(event_id)
        now = datetime.now()
        if not event: message = "Event not found."
        elif event["status"] != "published": message = "Registration is closed for this event."
        elif datetime.fromisoformat(f"{event['event_date']}T{event['event_time']}") <= now: message = "Registration is closed because this event has passed."
        elif connection.execute("SELECT id FROM registrations WHERE event_id=? AND user_id=? AND status='active'", (event_id,g.user["id"])).fetchone(): message = "You are already registered for this event."
        elif event["places_left"] <= 0: message = "This event is full."
        else:
            connection.execute("INSERT INTO registrations(event_id,user_id,status) VALUES(?,?,'active')", (event_id,g.user["id"]))
            connection.commit()
            notify_n8n("registration_created", attendee_name=g.user["name"], attendee_email=g.user["email"], event_title=event["title"], event_date=event["event_date"], event_time=event["event_time"], location=event["location"])
            if event["places_left"] == 1:
                notify_n8n("event_full", admin_email="admin@nowshera.test", event_title=event["title"])
            flash("Your place is confirmed!", "success")
            return redirect(url_for("my_registrations"))
        connection.rollback(); flash(message, "error")
        return redirect(url_for("event_detail", event_id=event_id))

    @app.route("/my-registrations")
    @login_required
    def my_registrations():
        if g.user["role"] != "attendee": abort(403)
        rows = db().execute("""SELECT r.id registration_id,r.status,r.created_at,e.* FROM registrations r JOIN events e ON e.id=r.event_id WHERE r.user_id=? ORDER BY r.created_at DESC""", (g.user["id"],)).fetchall()
        return render_template("my_registrations.html", registrations=rows)

    @app.post("/registrations/<int:registration_id>/cancel")
    @login_required
    def cancel_registration(registration_id):
        registration = db().execute("""SELECT r.id,e.title,u.name,u.email FROM registrations r JOIN events e ON e.id=r.event_id JOIN users u ON u.id=r.user_id WHERE r.id=? AND r.user_id=? AND r.status='active'""", (registration_id,g.user["id"])).fetchone()
        result = db().execute("UPDATE registrations SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='active'", (registration_id,g.user["id"]))
        db().commit()
        if not result.rowcount: abort(404)
        notify_n8n("registration_cancelled", attendee_name=registration["name"], attendee_email=registration["email"], event_title=registration["title"])
        flash("Registration cancelled. The place is available again.", "success")
        return redirect(url_for("my_registrations"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        totals = db().execute("""SELECT (SELECT COUNT(*) FROM events) events,(SELECT COUNT(*) FROM registrations WHERE status='active') registrations,COALESCE((SELECT SUM(capacity) FROM events WHERE status='published'),0)-COALESCE((SELECT COUNT(*) FROM registrations r JOIN events e ON e.id=r.event_id WHERE r.status='active' AND e.status='published'),0) available""").fetchone()
        rows = db().execute("""SELECT e.*,COUNT(r.id) registrations FROM events e LEFT JOIN registrations r ON r.event_id=e.id AND r.status='active' GROUP BY e.id ORDER BY e.created_at DESC""").fetchall()
        return render_template("admin.html", totals=totals, events=rows)

    @app.route("/admin/events/new", methods=["GET", "POST"])
    @admin_required
    def new_event():
        if request.method == "POST":
            errors, values = validate_event(request.form)
            if not errors:
                db().execute("INSERT INTO events(title,description,event_date,event_time,location,capacity,status,created_by) VALUES(?,?,?,?,?,?,'draft',?)", (*values,g.user["id"]))
                db().commit(); flash("Event saved as draft.", "success"); return redirect(url_for("admin_dashboard"))
            for error in errors: flash(error, "error")
        return render_template("event_form.html", event=None)

    @app.route("/admin/events/<int:event_id>/edit", methods=["GET", "POST"])
    @admin_required
    def edit_event(event_id):
        event = event_row(event_id)
        if not event: abort(404)
        if request.method == "POST":
            errors, values = validate_event(request.form, event_id)
            if not errors:
                db().execute("UPDATE events SET title=?,description=?,event_date=?,event_time=?,location=?,capacity=? WHERE id=?", (*values,event_id))
                db().commit(); flash("Event updated.", "success"); return redirect(url_for("admin_dashboard"))
            for error in errors: flash(error, "error")
        return render_template("event_form.html", event=event)

    @app.post("/admin/events/<int:event_id>/status")
    @admin_required
    def change_status(event_id):
        status = request.form.get("status")
        if status not in {"draft","published","completed","cancelled"}: abort(400)
        db().execute("UPDATE events SET status=? WHERE id=?", (status,event_id)); db().commit()
        flash(f"Event marked {status}.", "success"); return redirect(url_for("admin_dashboard"))

    @app.route("/admin/events/<int:event_id>/attendees")
    @admin_required
    def attendees(event_id):
        event = event_row(event_id)
        if not event: abort(404)
        q = request.args.get("q", "").strip()
        rows = db().execute("""SELECT u.name,u.email,r.created_at FROM registrations r JOIN users u ON u.id=r.user_id WHERE r.event_id=? AND r.status='active' AND (u.name LIKE ? OR u.email LIKE ?) ORDER BY u.name""", (event_id,f"%{q}%",f"%{q}%")).fetchall()
        return render_template("attendees.html", event=event, attendees=rows, q=q)

    @app.route("/admin/events/<int:event_id>/attendees.csv")
    @admin_required
    def export_attendees(event_id):
        event = event_row(event_id)
        if not event: abort(404)
        rows = db().execute("""SELECT u.name,u.email,r.created_at FROM registrations r JOIN users u ON u.id=r.user_id WHERE r.event_id=? AND r.status='active' ORDER BY u.name""", (event_id,)).fetchall()
        output=io.StringIO(); writer=csv.writer(output); writer.writerow(["Name","Email","Registered at"]); writer.writerows(rows)
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition":f"attachment; filename=event-{event_id}-attendees.csv"})

    return app


app = create_app()
if __name__ == "__main__":
    app.run(debug=True)
