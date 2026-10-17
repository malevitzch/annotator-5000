# annotator-5000

Software to coordinate image annotation.

## Production deployment on a Linux VPS

This Compose setup runs the Flask app under Gunicorn behind Caddy. Caddy
obtains and renews HTTPS certificates automatically. The app port is private to
the Compose network; only Caddy publishes ports 80 and 443.

### Requirements

- A Linux VPS with Docker Engine and the Docker Compose plugin.
- A DNS name whose A/AAAA records point to the VPS. Remove any incorrect AAAA
  record; certificate issuance requires the name to reach this server.
- Inbound TCP ports 80 and 443 (and optionally UDP 443 for HTTP/3). Restrict
  SSH to trusted sources and use the provider or host firewall.

The included image data is kept outside the container. Put images under
`images/`, with one directory per image set:

```text
images/
  set-a/
    image-001.jpg
  set-b/
    image-002.jpg
```

### Configure and start

From the project root on the VPS:

1. Copy `.env.example` to `.env`. Set `DOMAIN` to the DNS name and choose an
   `ADMIN_USERNAME`. Restrict `.env` to the deployment user (`chmod 600 .env`),
   then generate the Flask secret with `python3 toolbox.py flask_secret`.
2. Generate and store the administrator password hash with the toolbox. It
   prompts without echoing the password and updates `.env`:

   ```sh
   python3 toolbox.py admin_pwd
   ```

3. Ensure the image directory is populated and make the persistent database
   directory writable by the container's unprivileged UID:

   ```sh
   mkdir -p data
   sudo chown -R 10001:10001 data
   ```

4. Build and start the services:

   ```sh
   python3 toolbox.py build
   python3 toolbox.py run
   docker compose logs -f
   ```

Once DNS has propagated and Caddy has obtained a certificate, open
`https://your.domain.example` and sign in with the configured administrator
account. The admin page can create labeler accounts and set or reset their
passwords. Labeler passwords must be at least 12 characters.

### Toolbox commands

Run these from the project root:

```sh
python3 toolbox.py flask_secret
python3 toolbox.py admin_pwd
python3 toolbox.py discover-images
python3 toolbox.py export-csv --output annotations.csv
```

`run` discovers images automatically before starting; use `discover-images`
after adding files while the app is already running. Discovery registers new
files under `images/` in SQLite, making them available for annotation.

The CSV export includes only images with three finalized annotations. Its
label columns are fractions of annotators who answered yes (for example, two
yes votes produce approximately `0.6666666666666666`). Use
`python3 toolbox.py export-csv` to write CSV to standard output instead.

### Data, upgrades, and backups

- `images/` is mounted read-only into the app container. `.dockerignore` keeps
  image and database files out of the Docker build context.
- `data/annotations.sqlite3` is a host bind mount, so replacing the app
  container does not remove annotations or accounts. Caddy's certificate and
  configuration data are in named Docker volumes.
- The app runs as UID 10001, has a read-only container filesystem, and waits
  for SQLite locks for up to 30 seconds. Compose health-checks the app and
  rotates container logs.
- SQLite is suitable for a small, single-instance deployment. Do not run
  multiple app replicas against this database. Consider a database server and
  shared image storage only if traffic or concurrency makes the single-VPS
  design insufficient.
- Back up both the SQLite database and `images/` to storage outside the VPS.
  For a consistent live database backup, use SQLite's backup command rather
  than copying the database file directly. For example, with the `sqlite3`
  CLI installed on the host:

  ```sh
  mkdir -p backups
  sqlite3 data/annotations.sqlite3 ".backup 'backups/annotations.sqlite3'"
  tar -czf backups/images.tar.gz images
  ```

  Copy these backups off the VPS and periodically verify that they can be
  restored. Keep enough disk space for the image sets and backup files.
- To deploy code updates, pull or transfer the updated source and run
  `python3 toolbox.py build` followed by `python3 toolbox.py run`. Back up the
  database before upgrades. `docker compose down` leaves the database and
  named volumes in place; avoid `docker compose down -v` unless intentionally
  removing Caddy's stored data.
- `python3 toolbox.py wipe-db` asks for an explicit `WIPE` confirmation, stops
  the app, removes the SQLite database (including journal sidecars), and
  restarts the services. This permanently erases annotations and labeler
  accounts; the configured administrator is recreated at startup.

### Existing databases

Initialization never drops the `users` table. Existing user rows are retained;
when upgrading the original username-only schema, the app adds nullable
`password_hash` and defaulted `is_admin` columns. Legacy users have no stored
password hash, so an administrator must set a password for each account in the
account-management page. The configured administrator's hash remains managed
through `.env`. Back up an existing database before deploying the new version.
