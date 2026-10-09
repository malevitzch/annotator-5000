from pathlib import Path


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

    def __init__(self, db_path, images_path):
        import sqlite3

        self.images_path = images_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

        self.imgs = self.image_list()
        for x in self.imgs:
            print(f"{x}")

    def new_annotation(self, image, label, user):
        # The annotation has the following structure:
        # - Edge of the world - does the photo capture the edge of the splat?
        # - Visible gaussians - does the image differ significantly from reality due to gaussians being too visible?
        # - Inside - does the camera appear to be inside something (a blurry mess)
        # - Unreal - the image does not resemble a photo in any way (usually paired with "visible gaussians", but stronger)
        data = (image, user, *[label[i] for i in range(4)])
        self.conn.execute("INSERT INTO labels VALUES(?, ?, ?, ?, ?, ?)", data)

        count = self.conn.execute(
            "SELECT COUNT(*) FROM labels WHERE image_id=?", (image,)
        ).fetchone()[0]

        if count == 3:
            self.conn.execute(
                """
              INSERT INTO finalized_labels
              SELECT *
              FROM labels
              WHERE image_id = ?
            """,
                (image,),
            )

            self.conn.execute(
                """
              DELETE FROM labels
              WHERE image_id = ?
            """,
                (image,),
            )
        self.conn.commit()
