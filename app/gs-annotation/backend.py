class GSBackend:
    def __init__(self, db_path):
        import sqlite3

        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

    def new_annotation(self, image, label, user):
        # The annotation has the following structure:
        # - Edge of the world - does the photo capture the edge of the splat?
        # - Visible gaussians - does the image differ significantly from reality due to gaussians being too visible?
        # - Inside - does the camera appear to be inside something (a blurry mess)
        # - Unreal - the image does not resemble a photo in any way (usually paired with "visible gaussians", but stronger)
        data = (image, user, *[label[i] for i in range(4)])
        self.conn.execute("INSERT INTO labels VALUES(?, ?, ?, ?, ?, ?)", data)
        self.conn.commit()
