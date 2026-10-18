import os
import sqlite3
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from app.gsannotation.backend import GSBackend

ROOT_DIR = Path(__file__).resolve().parent.parent
LABELS = (
    ("edge", "Edge of the splat"),
    ("visgauss", "Visible gaussians"),
    ("blur", "Unrealistic blur"),
    ("unreal", "Doesn't resemble a photo in any way"),
)


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY"),
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD_HASH=os.environ.get("ADMIN_PASSWORD_HASH"),
        IMAGE_ROOT=os.environ.get("ANNOTATOR_IMAGES", str(ROOT_DIR / "images")),
        DATABASE_PATH=os.environ.get(
            "ANNOTATOR_DB", str(ROOT_DIR / "instance" / "annotations.sqlite3")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=True,
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if config:
        app.config.update(config)

    if not app.config["SECRET_KEY"]:
        raise RuntimeError("Set FLASK_SECRET_KEY in the environment or app config.")

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    admin_username = str(app.config["ADMIN_USERNAME"]).strip()
    admin_password_hash = app.config["ADMIN_PASSWORD_HASH"]
    if not admin_username or len(admin_username) > 32 or not admin_password_hash:
        raise RuntimeError(
            "Set ADMIN_USERNAME and ADMIN_PASSWORD_HASH before starting the app."
        )
    try:
        check_password_hash(admin_password_hash, "validate-password-hash")
    except (AttributeError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError(
            "ADMIN_PASSWORD_HASH is not a valid Werkzeug hash."
        ) from error
    app.config["ADMIN_USERNAME"] = admin_username

    CSRFProtect(app)

    def get_backend():
        if "backend" not in g:
            image_root = Path(app.config["IMAGE_ROOT"]).expanduser().resolve()
            if not image_root.is_dir():
                raise RuntimeError(f"Image directory does not exist: {image_root}.")

            database_path = Path(app.config["DATABASE_PATH"]).expanduser().resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            backend = GSBackend(str(database_path), str(image_root))
            backend.conn.execute(
                "UPDATE users SET is_admin = 0 WHERE is_admin = 1 AND user <> ?",
                (app.config["ADMIN_USERNAME"],),
            )
            backend.conn.execute(
                """
                INSERT INTO users (user, password_hash, is_admin)
                VALUES (?, ?, 1)
                ON CONFLICT(user) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    is_admin = 1
                """,
                (app.config["ADMIN_USERNAME"], app.config["ADMIN_PASSWORD_HASH"]),
            )
            backend.conn.commit()
            g.backend = backend
        return g.backend

    @app.teardown_appcontext
    def close_backend(_error=None):
        backend = g.pop("backend", None)
        if backend is not None:
            backend.conn.close()

    @app.get("/healthz")
    def healthcheck():
        get_backend().conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/")
    def index():
        if session.get("username"):
            return redirect(url_for("label_image"))
        return render_template("login.html")

    @app.post("/login")
    def login():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        backend = get_backend()
        account = backend.conn.execute(
            "SELECT password_hash FROM users WHERE user = ?", (username,)
        ).fetchone()
        valid_password = False
        if account:
            try:
                valid_password = check_password_hash(account[0], password)
            except (AttributeError, IndexError, TypeError, ValueError):
                valid_password = False

        if not valid_password:
            flash("Invalid username or password.", "error")
            return redirect(url_for("index"))

        session.clear()
        session["username"] = username
        return redirect(url_for("label_image"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/tutorial")
    def tutorial():
        username = session.get("username")
        if not username:
            return redirect(url_for("index"))

        account = (
            get_backend()
            .conn.execute("SELECT 1 FROM users WHERE user = ?", (username,))
            .fetchone()
        )
        if not account:
            session.clear()
            return redirect(url_for("index"))

        return render_template("tutorial.html", username=username)

    def require_admin():
        username = session.get("username")
        if not username:
            return redirect(url_for("index"))

        backend = get_backend()
        account = backend.conn.execute(
            "SELECT is_admin FROM users WHERE user = ?", (username,)
        ).fetchone()
        if not account:
            session.clear()
            return redirect(url_for("index"))
        if not account[0]:
            abort(403)
        return None

    @app.route("/admin/accounts", methods=["GET", "POST"])
    def admin_accounts():
        response = require_admin()
        if response is not None:
            return response

        backend = get_backend()
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or len(username) > 32:
                flash("Usernames must be between 1 and 32 characters.", "error")
            elif username == app.config["ADMIN_USERNAME"]:
                flash(
                    "That username is reserved for the configured administrator.",
                    "error",
                )
            elif len(password) < 12:
                flash("Passwords must be at least 12 characters long.", "error")
            else:
                existing = backend.conn.execute(
                    "SELECT 1 FROM users WHERE user = ?", (username,)
                ).fetchone()
                if existing:
                    flash("That username already exists.", "error")
                else:
                    backend.conn.execute(
                        "INSERT INTO users (user, password_hash, is_admin) VALUES (?, ?, 0)",
                        (username, generate_password_hash(password)),
                    )
                    backend.conn.commit()
                    flash(f"Account created for {username}.", "success")
            return redirect(url_for("admin_accounts"))

        users = backend.conn.execute(
            "SELECT user, is_admin, password_hash IS NOT NULL FROM users ORDER BY user"
        ).fetchall()
        return render_template(
            "admin_accounts.html",
            users=users,
            configured_admin=app.config["ADMIN_USERNAME"],
            progress=backend.progress(),
        )

    @app.post("/admin/accounts/password")
    def reset_account_password():
        response = require_admin()
        if response is not None:
            return response

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(password) < 12:
            flash("Passwords must be at least 12 characters long.", "error")
        elif username == app.config["ADMIN_USERNAME"]:
            flash(
                "The configured administrator password is managed by the server.",
                "error",
            )
        else:
            backend = get_backend()
            result = backend.conn.execute(
                "UPDATE users SET password_hash = ? WHERE user = ?",
                (generate_password_hash(password), username),
            )
            if result.rowcount:
                backend.conn.commit()
                flash(f"Password updated for {username}.", "success")
            else:
                flash("That account does not exist.", "error")
        return redirect(url_for("admin_accounts"))

    @app.get("/label")
    def label_image():
        username = session.get("username")
        if not username:
            return redirect(url_for("index"))

        backend = get_backend()
        account = backend.conn.execute(
            "SELECT is_admin FROM users WHERE user = ?", (username,)
        ).fetchone()
        if not account:
            session.clear()
            return redirect(url_for("index"))

        progress = backend.progress()
        current_image = session.get("current_image")
        if current_image is not None:
            current_image = tuple(current_image)
            if current_image not in backend.eligible_images(username):
                session.pop("current_image", None)
                current_image = None

        if current_image is None:
            current_image = backend.random_image(username)

        if current_image is None:
            session.pop("current_image", None)
            return render_template(
                "done.html",
                username=username,
                is_admin=bool(account[0]),
                progress=progress,
            )

        session["current_image"] = list(current_image)
        return render_template(
            "label.html",
            username=username,
            image=current_image,
            labels=LABELS,
            is_admin=bool(account[0]),
            progress=progress,
        )

    @app.post("/label")
    def submit_label():
        username = session.get("username")
        current_image = session.get("current_image")
        if not username or not current_image:
            return redirect(url_for("index"))

        backend = get_backend()
        image = tuple(current_image)
        if image not in backend.eligible_images(username):
            session.pop("current_image", None)
            flash(
                "That image is no longer available. Please label another one.", "error"
            )
            return redirect(url_for("label_image"))

        values = [int(name in request.form) for name, _description in LABELS]
        try:
            backend.new_annotation(image, values, username)
        except sqlite3.IntegrityError:
            session.pop("current_image", None)
            flash("This image was already labeled by this user.", "error")
            return redirect(url_for("label_image"))

        session.pop("current_image", None)
        return redirect(url_for("label_image"))

    @app.get("/images/<image_set>/<image_id>")
    def image_file(image_set, image_id):
        if not session.get("username"):
            abort(404)

        backend = get_backend()
        if (image_set, image_id) not in backend.imgs:
            abort(404)

        image_root = Path(app.config["IMAGE_ROOT"]).expanduser().resolve()
        return send_from_directory(str(image_root / image_set), image_id)

    return app
