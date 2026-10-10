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

from app.gsannotation.backend import GSBackend

ROOT_DIR = Path(__file__).resolve().parent.parent
LABELS = (
    ("edge", "The image captures the edge of the splat."),
    ("visgauss", "Visible gaussians make the image differ significantly from reality."),
    ("inside", "The camera appears to be inside something, creating a blurry mess."),
    ("unreal", "The image does not resemble a photo in any way."),
)


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me"),
        IMAGE_ROOT=os.environ.get("ANNOTATOR_IMAGES", str(ROOT_DIR / "images")),
        DATABASE_PATH=os.environ.get(
            "ANNOTATOR_DB", str(ROOT_DIR / "instance" / "annotations.sqlite3")
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)

    def get_backend():
        if "backend" not in g:
            image_root = Path(app.config["IMAGE_ROOT"]).expanduser().resolve()
            if not image_root.is_dir():
                raise RuntimeError(
                    f"Image directory does not exist: {image_root}. "
                    "Set ANNOTATOR_IMAGES to the directory containing image sets."
                )

            database_path = Path(app.config["DATABASE_PATH"]).expanduser().resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            g.backend = GSBackend(str(database_path), str(image_root))
        return g.backend

    @app.teardown_appcontext
    def close_backend(_error=None):
        backend = g.pop("backend", None)
        if backend is not None:
            backend.conn.close()

    @app.get("/")
    def index():
        if session.get("username"):
            return redirect(url_for("label_image"))
        return render_template("login.html")

    @app.post("/login")
    def login():
        username = request.form.get("username", "").strip()
        if not username or len(username) > 32:
            flash("Enter a name between 1 and 32 characters.", "error")
            return redirect(url_for("index"))

        session.clear()
        session["username"] = username
        return redirect(url_for("label_image"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.get("/label")
    def label_image():
        username = session.get("username")
        if not username:
            return redirect(url_for("index"))

        backend = get_backend()
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
            return render_template("done.html", username=username)

        session["current_image"] = list(current_image)
        return render_template(
            "label.html",
            username=username,
            image=current_image,
            labels=LABELS,
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


app = create_app()
