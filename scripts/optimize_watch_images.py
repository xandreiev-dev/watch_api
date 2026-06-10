import argparse
import os
import posixpath
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import paramiko
from PIL import Image, ImageOps

from watch_api.config import settings
from watch_api.db import get_connection


PUBLIC_PREFIX = "https://api.premikum.com/watch-images/"
REMOTE_DIR = "/var/www/pub/watch-images"
DEFAULT_MAX_BYTES = 200 * 1024
DEFAULT_MAX_DIMENSION = 1000


@dataclass
class OptimizedImage:
    variant_id: int
    old_url: str
    new_url: str
    old_bytes: int
    new_bytes: int
    width: int
    height: int
    quality: int
    data: bytes


def fetch_large_rows(max_bytes: int, limit: int | None) -> list[dict]:
    sql = """
        SELECT id, image_url, image_data, LENGTH(image_data) AS image_bytes
        FROM g_watch_variant
        WHERE image_data IS NOT NULL
          AND LENGTH(image_data) > %s
          AND image_url IS NOT NULL
          AND image_url <> ''
        ORDER BY LENGTH(image_data) DESC, id ASC
    """
    params: list[int] = [max_bytes]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())


def flatten_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        background = Image.new("RGB", image.size, "white")
        background.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
        return background
    return image.convert("RGB")


def image_url_for_jpeg(old_url: str, variant_id: int) -> str:
    parsed = urlparse(old_url)
    filename = posixpath.basename(parsed.path)
    stem = Path(filename).stem if filename else f"variant-{variant_id}"
    return f"{PUBLIC_PREFIX}{stem}.jpg"


def optimize_image(row: dict, max_bytes: int, max_dimension: int, min_quality: int) -> OptimizedImage:
    variant_id = int(row["id"])
    old_url = str(row["image_url"])
    source = Image.open(BytesIO(row["image_data"]))
    image = flatten_image(source)

    dimension = max_dimension
    best_data: bytes | None = None
    best_quality = 0
    best_size = image.size

    while dimension >= 360:
        candidate = image.copy()
        candidate.thumbnail((dimension, dimension), Image.LANCZOS)
        for quality in range(86, min_quality - 1, -4):
            buffer = BytesIO()
            candidate.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            data = buffer.getvalue()
            if best_data is None or len(data) < len(best_data):
                best_data = data
                best_quality = quality
                best_size = candidate.size
            if len(data) <= max_bytes:
                return OptimizedImage(
                    variant_id=variant_id,
                    old_url=old_url,
                    new_url=image_url_for_jpeg(old_url, variant_id),
                    old_bytes=int(row["image_bytes"]),
                    new_bytes=len(data),
                    width=candidate.width,
                    height=candidate.height,
                    quality=quality,
                    data=data,
                )
        dimension = int(dimension * 0.85)

    assert best_data is not None
    return OptimizedImage(
        variant_id=variant_id,
        old_url=old_url,
        new_url=image_url_for_jpeg(old_url, variant_id),
        old_bytes=int(row["image_bytes"]),
        new_bytes=len(best_data),
        width=best_size[0],
        height=best_size[1],
        quality=best_quality,
        data=best_data,
    )


def update_database(images: list[OptimizedImage]) -> None:
    sql = """
        UPDATE g_watch_variant
        SET image_data = %s,
            image_url = %s,
            updated_at = NOW()
        WHERE id = %s
    """
    updates = [(image.data, image.new_url, image.variant_id) for image in images]
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(sql, updates)
        connection.commit()


def upload_images(images: list[OptimizedImage], remote_dir: str) -> None:
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
            for image in images:
                filename = posixpath.basename(urlparse(image.new_url).path)
                remote_path = posixpath.join(remote_dir, filename)
                with sftp.open(remote_path, "wb") as remote_file:
                    remote_file.write(image.data)
    finally:
        client.close()


def print_summary(images: list[OptimizedImage]) -> None:
    old_total = sum(image.old_bytes for image in images)
    new_total = sum(image.new_bytes for image in images)
    for image in images:
        print(
            f"variant_id={image.variant_id} "
            f"{image.old_bytes // 1024}KB -> {image.new_bytes // 1024}KB "
            f"{image.width}x{image.height} q={image.quality} "
            f"{image.new_url}"
        )
    print(
        "Done: "
        f"count={len(images)}, "
        f"old_total={old_total // 1024}KB, "
        f"new_total={new_total // 1024}KB"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compress large watch image_data rows and publish them.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Optimize rows larger than this.")
    parser.add_argument("--max-dimension", type=int, default=DEFAULT_MAX_DIMENSION, help="Largest output side in px.")
    parser.add_argument("--min-quality", type=int, default=66, help="Lowest JPEG quality to try before resizing more.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max rows to process.")
    parser.add_argument("--remote-dir", default=REMOTE_DIR, help="Remote directory for published images.")
    parser.add_argument("--apply", action="store_true", help="Update DB and upload files. Without this, dry-run only.")
    args = parser.parse_args()

    rows = fetch_large_rows(args.max_bytes, args.limit)
    images = [optimize_image(row, args.max_bytes, args.max_dimension, args.min_quality) for row in rows]
    print_summary(images)

    oversized = [image for image in images if image.new_bytes > args.max_bytes]
    if oversized:
        print(f"Warning: {len(oversized)} images are still larger than {args.max_bytes // 1024}KB.")

    if not args.apply:
        print("Dry run only. Add --apply to update the database and upload files.")
        return 0 if not oversized else 1

    update_database(images)
    upload_images(images, args.remote_dir)
    print("Applied: database updated and files uploaded.")
    return 0 if not oversized else 1


if __name__ == "__main__":
    raise SystemExit(main())
