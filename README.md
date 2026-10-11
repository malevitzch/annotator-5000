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

Copy `.env.example` to `.env`. Set a private, random `FLASK_SECRET_KEY` and
choose an `ADMIN_USERNAME`. The admin password is stored as a Werkzeug hash,
not as plaintext. With the image built, generate a hash interactively:

```sh
docker compose run --rm --no-deps --entrypoint python annotator -c 'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("Admin password: ")))'
```

Paste the output into `.env` as `ADMIN_PASSWORD_HASH`, surrounded by single
quotes (Werkzeug hashes contain `$` characters). Keep `.env` private; it is
ignored by Git.

Start the app from the project root:

```sh
docker compose up --build
```

Open <http://localhost:5000> and sign in with the configured admin account.
The admin page can create labeler accounts; passwords are hashed before they
are stored in SQLite. Labeler passwords must be at least 12 characters.

Compose mounts host `images/` read-only at `/app/images` and stores SQLite at
`data/annotations.sqlite3` on the host (mounted at `/data/annotations.sqlite3`
in the container). The database file is directly available for inspection or
backup. Stopping the app with `docker compose down` leaves it in place.

The first auth-schema initialization discards the old `users` table contents;
existing annotation tables are left intact. No legacy user rows are migrated.
