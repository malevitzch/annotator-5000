#!/usr/bin/env python3
"""Small command-line helpers for the Docker Compose deployment."""

import argparse
import base64
import getpass
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
COMPOSE = ["docker", "compose"]


def require_env_file():
    if not ENV_FILE.is_file():
        raise RuntimeError(".env is missing; copy .env.example to .env first.")


def run_compose(args, *, env=None, **kwargs):
    return subprocess.run(
        [*COMPOSE, *args],
        cwd=ROOT,
        env=env,
        check=True,
        **kwargs,
    )


def ensure_app_image(env=None):
    image_check = subprocess.run(
        ["docker", "image", "inspect", "annotator-5000:local"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if image_check.returncode != 0:
        run_compose(["build", "annotator"], env=env)


def ensure_mount_directories():
    images_dir = ROOT / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if data_dir.stat().st_uid != 10001:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0:0",
                "--volume",
                f"{data_dir.resolve()}:/data",
                "--entrypoint",
                "chown",
                "annotator-5000:local",
                "-R",
                "10001:10001",
                "/data",
            ],
            cwd=ROOT,
            check=True,
        )


def generate_admin_hash(password):
    env = os.environ.copy()
    env["FLASK_SECRET_KEY"] = "toolbox-hash-only"
    env["ADMIN_PASSWORD_HASH"] = "toolbox-hash-only"
    if not env.get("DOMAIN"):
        env["DOMAIN"] = "localhost"

    script = (
        "import sys; "
        "from werkzeug.security import generate_password_hash; "
        "password = sys.stdin.readline().rstrip('\\n'); "
        "print('ADMIN_HASH=' + generate_password_hash(password))"
    )
    ensure_app_image(env)

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--entrypoint",
            "python",
            "annotator-5000:local",
            "-c",
            script,
        ],
        cwd=ROOT,
        env=env,
        input=password + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("ADMIN_HASH="):
            return line.removeprefix("ADMIN_HASH=")
    raise RuntimeError("The container did not return a password hash.")


def set_env_value(name, value):
    content = ENV_FILE.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    matches = [index for index, line in enumerate(lines) if pattern.match(line)]
    if len(matches) > 1:
        raise RuntimeError(f".env contains more than one {name} entry.")

    newline = "\r\n" if "\r\n" in content else "\n"
    replacement = f"{name}='{value}'{newline}"
    if matches:
        lines[matches[0]] = replacement
    else:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.append(replacement)

    descriptor, temporary_path = tempfile.mkstemp(prefix=".env.", dir=ROOT)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.writelines(lines)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, ENV_FILE)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise


def restart_running_annotator():
    env = os.environ.copy()
    if not env.get("DOMAIN"):
        env["DOMAIN"] = "localhost"
    try:
        result = subprocess.run(
            [*COMPOSE, "ps", "--status", "running", "-q", "annotator"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        diagnostic = error.stderr or error.stdout
        print(
            "Password hash saved, but the running app could not be checked. "
            "Run `python3 toolbox.py run` to apply it.",
            file=sys.stderr,
        )
        if diagnostic:
            print(diagnostic, file=sys.stderr)
        return

    if result.stdout.strip():
        run_compose(["up", "-d", "--no-deps", "annotator"], env=env)
        print("Restarted the running app with the new administrator password.")
    else:
        print("Hash saved. Run `python3 toolbox.py run` to start the app.")


def admin_pwd(_args):
    require_env_file()
    password = getpass.getpass("New administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        raise RuntimeError("Passwords do not match.")
    if len(password) < 12:
        raise RuntimeError("Administrator passwords must be at least 12 characters.")

    password_hash = generate_admin_hash(password)
    set_env_value("ADMIN_PASSWORD_HASH", password_hash)
    print("Updated ADMIN_PASSWORD_HASH in .env; plaintext was not saved.")
    restart_running_annotator()


def flask_secret(_args):
    require_env_file()
    set_env_value("FLASK_SECRET_KEY", secrets.token_hex(32))
    print("Generated and saved a new FLASK_SECRET_KEY in .env.")


def discover_images_in_container():
    script = (
        "import json; "
        "from app.gsannotation.backend import GSBackend; "
        "backend = GSBackend('/data/annotations.sqlite3', '/app/images'); "
        "print('TOOLBOX_DISCOVERY=' + json.dumps(backend.discover_images())); "
        "backend.conn.close()"
    )
    result = run_compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "annotator",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("TOOLBOX_DISCOVERY="):
            return json.loads(line.removeprefix("TOOLBOX_DISCOVERY="))
    raise RuntimeError("The container did not return image discovery results.")


def discover_images(_args):
    require_env_file()
    ensure_app_image()
    ensure_mount_directories()
    new_images = discover_images_in_container()
    print(f"Discovered {len(new_images)} new image(s).")
    for image_set, image_id in new_images:
        print(f"  {image_set}/{image_id}")


def build(_args):
    require_env_file()
    run_compose(["build"])


def stop(_args):
    require_env_file()
    run_compose(["stop"])
    print("Services stopped gracefully; database and volumes were retained.")


def run(_args):
    require_env_file()
    ensure_app_image()
    ensure_mount_directories()
    new_images = discover_images_in_container()
    print(f"Registered {len(new_images)} new image(s).")
    run_compose(["up", "-d"])
    print("Services started. Check `docker compose ps` for status.")


def reload(_args):
    stop(_args)
    build(_args)
    run(_args)


def export_csv(args):
    require_env_file()
    ensure_app_image()
    ensure_mount_directories()
    script = (
        "import base64, csv, io, sqlite3\n"
        "connection = sqlite3.connect('file:/data/annotations.sqlite3?mode=ro', uri=True)\n"
        "output = io.StringIO(newline='')\n"
        "writer = csv.writer(output, lineterminator='\\n')\n"
        "writer.writerow(['set', 'id', 'edge_fraction', 'visgauss_fraction', 'blur_fraction', 'unreal_fraction'])\n"
        "writer.writerows(connection.execute('''SELECT image_set, image_id, AVG(edge), AVG(visgauss), AVG(blur), AVG(unreal) FROM finalized_labels GROUP BY image_set, image_id HAVING COUNT(DISTINCT user) = 3 ORDER BY image_set, image_id'''))\n"
        "print('TOOLBOX_CSV=' + base64.b64encode(output.getvalue().encode('utf-8')).decode('ascii'))\n"
        "connection.close()"
    )
    result = run_compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "annotator",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
    )
    encoded_csv = next(
        (
            line.removeprefix("TOOLBOX_CSV=")
            for line in result.stdout.splitlines()
            if line.startswith("TOOLBOX_CSV=")
        ),
        None,
    )
    if encoded_csv is None:
        raise RuntimeError("The container did not return CSV export data.")
    csv_data = base64.b64decode(encoded_csv).decode("utf-8")

    if args.output == "-":
        sys.stdout.write(csv_data)
    else:
        with open(args.output, "w", encoding="utf-8", newline="") as output:
            output.write(csv_data)
        print(f"Exported finalized annotations to {args.output}.", file=sys.stderr)


def wipe_db(_args):
    require_env_file()
    print("This permanently removes annotations and labeler accounts.")
    print("The configured administrator account will be recreated on startup.")
    if input("Type WIPE to continue: ") != "WIPE":
        print("Cancelled; the database was not changed.")
        return

    run_compose(["stop", "annotator"])
    delete_database = (
        "from pathlib import Path; "
        "database = Path('/data/annotations.sqlite3'); "
        "[Path(str(database) + suffix).unlink(missing_ok=True) "
        "for suffix in ('-wal', '-shm', '-journal', '')]"
    )
    run_compose(
        [
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "python",
            "annotator",
            "-c",
            delete_database,
        ]
    )
    discover_images_in_container()
    run_compose(["up", "-d"])
    print("Database wiped; Compose services restarted.")


def main():
    parser = argparse.ArgumentParser(
        description="Manage the annotator Compose deployment."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("admin-pwd", help="Set a new administrator password hash")
    subparsers.add_parser("flask-secret", help="Generate and save FLASK_SECRET_KEY")
    subparsers.add_parser("build", help="Build the application image")
    subparsers.add_parser("run", help="Discover images and start the services")
    subparsers.add_parser("stop", help="Gracefully stop the Compose services")
    subparsers.add_parser("reload", help="Gracefully stop, rebuild, and restart")
    subparsers.add_parser("discover-images", help="Register images found under images/")
    export_parser = subparsers.add_parser(
        "export-csv", help="Export finalized annotation fractions as CSV"
    )
    export_parser.add_argument(
        "--output",
        "-o",
        default="-",
        help="output path, or - for standard output (default: -)",
    )
    subparsers.add_parser(
        "wipe-db", help="Delete the SQLite database after confirmation"
    )
    args = parser.parse_args()

    commands = {
        "admin-pwd": admin_pwd,
        "flask-secret": flask_secret,
        "build": build,
        "run": run,
        "stop": stop,
        "reload": reload,
        "discover-images": discover_images,
        "export-csv": export_csv,
        "wipe-db": wipe_db,
    }
    try:
        commands[args.command](args)
    except subprocess.CalledProcessError as error:
        for output in (error.stderr, error.stdout):
            if output:
                print(
                    output, end="" if output.endswith("\n") else "\n", file=sys.stderr
                )
        print(f"Command failed with exit code {error.returncode}.", file=sys.stderr)
        return error.returncode
    except (OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
