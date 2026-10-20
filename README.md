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
2. Generate and store the administrator password hash with the toolbox. It will automatically 
   replace the value in `.env`:
   ```sh
   python3 toolbox.py admin_pwd
   ```
3. Ensure `images/` contains the image sets you want to annotate. The toolbox
   creates missing `images/` and `data/` mount directories if needed, but you should
   load your data into `images/`.
4. Build and start the services:

   ```sh
   python3 toolbox.py reload
   ```

### Toolbox commands

Run these from the project root:

```sh
python3 toolbox.py flask_secret
python3 toolbox.py admin_pwd
python3 toolbox.py stop
python3 toolbox.py reload
python3 toolbox.py discover-images
python3 toolbox.py export-csv --output annotations.csv
```

`run` discovers images automatically before starting, `discover-images`
is only useful to add new images without stopping the app. Discovery registers new
files under `images/` in SQLite, making them available for annotation.

The `export-csv` command output includes only images with three finalized annotations. Its
label columns are fractions of annotators who answered yes. Running it without the `--output`` flag
causes the data to be output to stdout (useful for scripts).

### Data, upgrades, and backups

- `images/` is mounted read-only into the app container. `.dockerignore` keeps
  image and database files out of the Docker build context.
- `data/annotations.sqlite3` is a host bind mount, so replacing the app
  container does not remove annotations or accounts. Caddy's certificate and
  configuration data are in named Docker volumes.
- To deploy code updates, pull the code and run the `reload` command.
- `python3 toolbox.py wipe-db` asks for an explicit `WIPE` confirmation, stops
  the app, removes the SQLite database, and
  restarts the services. This permanently erases annotations and labeler
  accounts; the configured administrator is recreated at startup.
