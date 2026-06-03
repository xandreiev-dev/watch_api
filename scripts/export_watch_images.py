import argparse
import os
import sys
from typing import Any


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from watch_api.db import get_connection
import watch_api.services.watch_card_service as watch_card_service


def is_gsmarena_row(row: dict[str, Any]) -> bool:
    source_text = " ".join(
        str(row.get(field) or "")
        for field in ("source_host", "source_url", "image_url")
    )
    return "gsmarena" in source_text.casefold()


def fetch_rows(limit: int | None) -> list[dict[str, Any]]:
    sql = """
        SELECT id, source_host, source_url, image_url, image_data
        FROM g_watch_variant
        WHERE image_data IS NOT NULL
        ORDER BY id ASC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())


def update_image_urls(updates: list[tuple[str, int]]) -> int:
    if not updates:
        return 0
    sql = """
        UPDATE g_watch_variant
        SET image_url = %s
        WHERE id = %s
    """
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.executemany(sql, updates)
            return cursor.rowcount


def needs_image_url_update(row: dict[str, Any], local_url: str) -> bool:
    return str(row.get("image_url") or "").strip() != local_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Export watch image_data blobs to local static files.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of DB rows to scan.")
    parser.add_argument(
        "--url-prefix",
        default=watch_card_service.IMAGE_URL_PREFIX,
        help="Public URL prefix for generated files, for example /watch-images.",
    )
    parser.add_argument(
        "--skip-gsmarena",
        action="store_true",
        help="Leave GSMArena rows external. By default every available image_data row is exported.",
    )
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update g_watch_variant.image_url to the generated local URL.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without updating the database.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print only the final summary.")
    args = parser.parse_args()

    watch_card_service.IMAGE_URL_PREFIX = args.url_prefix.rstrip("/")

    exported = 0
    skipped_gsmarena = 0
    empty = 0
    failed = 0
    unchanged = 0
    db_updates = 0
    pending_db_updates = 0
    update_rows: list[tuple[str, int]] = []

    for row in fetch_rows(args.limit):
        if is_gsmarena_row(row) and args.skip_gsmarena:
            skipped_gsmarena += 1
            continue

        url = watch_card_service.save_variant_image_file(row)
        if url:
            exported += 1
            should_update = args.update_db and needs_image_url_update(row, url)
            if should_update and args.dry_run:
                pending_db_updates += 1
            elif should_update:
                update_rows.append((url, row["id"]))
            elif args.update_db:
                unchanged += 1

            if not args.quiet:
                suffix = ""
                if should_update and args.dry_run:
                    suffix = " DB_UPDATE_DRY_RUN"
                elif should_update:
                    suffix = " DB_UPDATED"
                elif args.update_db:
                    suffix = " DB_UNCHANGED"
                print(f"OK variant_id={row['id']} -> {url}{suffix}")
        elif row.get("image_data"):
            failed += 1
            print(f"FAILED variant_id={row['id']}", file=sys.stderr)
        else:
            empty += 1

    if args.update_db and not args.dry_run:
        db_updates = update_image_urls(update_rows)

    print(
        "\nDone: "
        f"exported={exported}, "
        f"skipped_gsmarena={skipped_gsmarena}, "
        f"empty={empty}, "
        f"failed={failed}, "
        f"db_updates={db_updates}, "
        f"pending_db_updates={pending_db_updates}, "
        f"unchanged={unchanged}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
