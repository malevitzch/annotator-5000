from pathlib import Path
from random import choice


class GSBackend:
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
                inside      INTEGER,
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
            CREATE TABLE IF NOT EXISTS users (
            user        VARCHAR(32),
            PRIMARY KEY (user)
            )
            """
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
        return imgs

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
        import sqlite3

        self.images_path = images_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._ensure_tables_exist()

        self.imgs = self.image_list()

    def new_annotation(self, image, label, user):
        # The annotation has the following structure:
        # - Edge of the world - does the photo capture the edge of the splat?
        # - Visible gaussians - does the image differ significantly from reality due to gaussians being too visible?
        # - Inside - does the camera appear to be inside something (a blurry mess)
        # - Unreal - the image does not resemble a photo in any way (usually paired with "visible gaussians", but stronger)
        image_set, image_id = image
        data = (image_set, image_id, user, *[label[i] for i in range(4)])
        self.conn.execute("INSERT INTO labels VALUES(?, ?, ?, ?, ?, ?, ?)", data)

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
