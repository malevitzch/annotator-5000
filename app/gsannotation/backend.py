import sqlite3
from pathlib import Path
from random import choice

from werkzeug.security import check_password_hash


class GSBackend:
    def close(self):
        self.conn.close()

    def configure_admin(self, username, password_hash):
        self.conn.execute(
            "UPDATE users SET is_admin = 0 WHERE is_admin = 1 AND user <> ?",
            (username,),
        )
        self.conn.execute(
            """
            INSERT INTO users (user, password_hash, is_admin)
            VALUES (?, ?, 1)
            ON CONFLICT(user) DO UPDATE SET
                password_hash = excluded.password_hash,
                is_admin = 1
            """,
            (username, password_hash),
        )
        self.conn.commit()

    def healthcheck(self):
        self.conn.execute("SELECT 1").fetchone()

    def authenticate(self, username, password):
        account = self.conn.execute(
            "SELECT password_hash FROM users WHERE user = ?", (username,)
        ).fetchone()
        if not account:
            return False
        try:
            return check_password_hash(account[0], password)
        except (AttributeError, IndexError, TypeError, ValueError):
            return False

    def user_exists(self, username):
        return (
            self.conn.execute(
                "SELECT 1 FROM users WHERE user = ?", (username,)
            ).fetchone()
            is not None
        )

    def is_admin(self, username):
        account = self.conn.execute(
            "SELECT is_admin FROM users WHERE user = ?", (username,)
        ).fetchone()
        return None if account is None else bool(account[0])

    def leaderboard(self):
        return self.conn.execute(
            """
            SELECT users.user, COUNT(annotations.user) AS annotation_count
            FROM users
            LEFT JOIN (
                SELECT user FROM labels
                UNION ALL
                SELECT user FROM finalized_labels
            ) AS annotations ON annotations.user = users.user
            GROUP BY users.user
            ORDER BY annotation_count DESC, users.user COLLATE NOCASE ASC
            LIMIT 10
            """
        ).fetchall()

    def create_user(self, username, password_hash):
        try:
            self.conn.execute(
                "INSERT INTO users (user, password_hash, is_admin) VALUES (?, ?, 0)",
                (username, password_hash),
            )
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False
        self.conn.commit()
        return True

    def users(self):
        return self.conn.execute(
            "SELECT user, is_admin, password_hash IS NOT NULL FROM users ORDER BY user"
        ).fetchall()

    def set_password(self, username, password_hash):
        result = self.conn.execute(
            "UPDATE users SET password_hash = ? WHERE user = ?",
            (password_hash, username),
        )
        if not result.rowcount:
            return False
        self.conn.commit()
        return True

    def _ensure_tables_exist(self):

        for table in ["labels", "finalized_labels"]:
            self.conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {table} (
                image_set   VARCHAR(32),
                image_id    VARCHAR(32),
                user        VARCHAR(32),
                edge        INTEGER,
                visgauss    INTEGER,
                blur        INTEGER,
                unreal      INTEGER,
                PRIMARY KEY (image_set, image_id, user)
                )
            """
            )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS images (
            image_set   VARCHAR(32),
            image_id    VARCHAR(32),
            PRIMARY KEY (image_set, image_id)
            )
            """
        )

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        users_schema = self.conn.execute(
            "SELECT value FROM schema_metadata WHERE key = 'users_schema'"
        ).fetchone()
        if users_schema is not None and users_schema[0] != "1":
            raise RuntimeError(f"Unsupported users schema version: {users_schema[0]}")

        users_table = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        if users_table is None:
            self.conn.execute(
                """
                CREATE TABLE users (
                    user          VARCHAR(32) PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    is_admin      INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        else:
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(users)")}
            if "user" not in columns:
                raise RuntimeError("Existing users table has no 'user' column.")
            if "password_hash" not in columns:
                self.conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
            if "is_admin" not in columns:
                self.conn.execute(
                    "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
                )

        if users_schema is None:
            self.conn.execute(
                "INSERT INTO schema_metadata (key, value) VALUES ('users_schema', '1')"
            )

        self.conn.commit()

    def image_list(self):
        dir = Path(self.images_path)
        imgs = []
        for child in dir.iterdir():
            if child.is_dir():
                img_set = child.stem
                for img in child.iterdir():
                    if img.is_file():
                        imgs.append((str(img_set), str(img.name)))
        return sorted(imgs)

    def discover_images(self):
        available_images = self.image_list()
        known_images = set(
            self.conn.execute("SELECT image_set, image_id FROM images").fetchall()
        )
        new_images = [image for image in available_images if image not in known_images]
        self.conn.executemany(
            "INSERT OR IGNORE INTO images (image_set, image_id) VALUES (?, ?)",
            new_images,
        )
        self.conn.commit()
        self.imgs = available_images
        return new_images

    def progress(self):
        active_images = set(self.imgs)
        completed = sum(
            (image_set, image_id) in active_images
            for image_set, image_id in self.conn.execute(
                """
                SELECT image_set, image_id FROM labels
                UNION ALL
                SELECT image_set, image_id FROM finalized_labels
                """
            )
        )
        return {"completed": completed, "required": len(active_images) * 3}

    def eligible_images(self, user):
        labeled_by_image = {}
        rows = self.conn.execute("SELECT image_set, image_id, user FROM labels")
        for image_set, image_id, labeled_user in rows:
            labeled_by_image.setdefault((image_set, image_id), set()).add(labeled_user)

        finalized_images = set(
            self.conn.execute(
                "SELECT image_set, image_id FROM finalized_labels"
            ).fetchall()
        )
        return [
            image
            for image in self.imgs
            if image not in finalized_images
            and len(labeled_by_image.get(image, set())) < 3
            and user not in labeled_by_image.get(image, set())
        ]

    def random_image(self, user):
        eligible = self.eligible_images(user)
        return choice(eligible) if eligible else None

    def __init__(self, db_path, images_path):
        self.images_path = images_path
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.cursor = self.conn.cursor()
        self._ensure_tables_exist()

        known_images = set(
            self.conn.execute("SELECT image_set, image_id FROM images").fetchall()
        )
        self.imgs = [image for image in self.image_list() if image in known_images]

    def new_annotation(self, image, label, user):
        # The annotation has the following structure:
        # - Edge of the world - does the photo capture the edge of the splat?
        # - Visible gaussians - does the image differ significantly from reality due to gaussians being too visible?
        # - Blur - is there unrealistic blur visible in the image?
        # - Unreal - do you fail to imagine what the image was supposed to picture?
        image_set, image_id = image
        data = (image_set, image_id, user, *[label[i] for i in range(4)])
        try:
            self.conn.execute("INSERT INTO labels VALUES(?, ?, ?, ?, ?, ?, ?)", data)
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

        count = self.conn.execute(
            """
            SELECT COUNT(DISTINCT user)
            FROM labels
            WHERE image_set = ? AND image_id = ?
            """,
            (image_set, image_id),
        ).fetchone()[0]

        if count == 3:
            self.conn.execute(
                """
              INSERT INTO finalized_labels
              SELECT *
              FROM labels
              WHERE image_set = ? AND image_id = ?
            """,
                (image_set, image_id),
            )

            self.conn.execute(
                """
              DELETE FROM labels
              WHERE image_set = ? AND image_id = ?
            """,
                (image_set, image_id),
            )
        self.conn.commit()
        return True
