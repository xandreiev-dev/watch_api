import os
import posixpath
import sys
from urllib.parse import urlparse


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import paramiko

from watch_api.config import settings
from watch_api.db import get_connection


PUBLIC_PREFIX = "https://api.premikum.com/watch-images/"
REMOTE_DIR = "/var/www/pub/watch-images"


def fetch_image_rows() -> list[dict]:
    sql = """
        SELECT id, image_url
        FROM g_watch_variant
        WHERE image_data IS NOT NULL
          AND LENGTH(image_data) > 0
          AND image_url IS NOT NULL
          AND image_url <> ''
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            return list(cursor.fetchall())


def remote_filenames() -> set[str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        settings.ssh_host,
        port=settings.ssh_port,
        username=settings.ssh_user,
        password=settings.ssh_password,
        timeout=15,
    )
    try:
        with client.open_sftp() as sftp:
            return set(sftp.listdir(REMOTE_DIR))
    finally:
        client.close()


def filename_from_url(url: str) -> str:
    return posixpath.basename(urlparse(url).path)


def main() -> int:
    rows = fetch_image_rows()
    remote = remote_filenames()

    wrong_prefix = [row for row in rows if not str(row["image_url"]).startswith(PUBLIC_PREFIX)]
    missing_files = [
        (row["id"], filename_from_url(str(row["image_url"])))
        for row in rows
        if str(row["image_url"]).startswith(PUBLIC_PREFIX)
        and filename_from_url(str(row["image_url"])) not in remote
    ]

    print(f"db_image_rows={len(rows)}")
    print(f"remote_files={len(remote)}")
    print(f"wrong_prefix={len(wrong_prefix)}")
    print(f"missing_files={len(missing_files)}")
    if wrong_prefix:
        print("wrong_prefix_examples=", wrong_prefix[:10])
    if missing_files:
        print("missing_file_examples=", missing_files[:10])
    return 1 if wrong_prefix or missing_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
