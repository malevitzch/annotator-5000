# annotator-5000
Software to coordinate image annotation

## Run with Docker Compose

Put images under `images/`, with one directory per image set:

```text
images/
  set-a/
    image-001.jpg
  set-b/
    image-002.jpg
```

Start the app from the project root:

```sh
docker compose up --build
```

Open <http://localhost:5000>. Compose mounts the host `images/` directory
read-only at `/app/images` and keeps the SQLite database in the persistent
`annotation-data` volume. Stop the app with `docker compose down`; remove its
database volume with `docker compose down --volumes`.

For anything beyond local development, set a private `FLASK_SECRET_KEY` in
the environment before starting Compose. The name prompt identifies labelers
but is not authentication.
