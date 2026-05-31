import argparse
import os
import sys
from typing import Any


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from watch_api.db import get_connection
from watch_api.services.watch_card_service import save_variant_image_file


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Export watch image_data blobs to local static files.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of DB rows to scan.")
    parser.add_argument(
        "--skip-gsmarena",
        action="store_true",
        help="Leave GSMArena rows external. By default every available image_data row is exported.",
    )
    parser.add_argument("--quiet", action="store_true", help="Print only the final summary.")
    args = parser.parse_args()

    exported = 0
    skipped_gsmarena = 0
    empty = 0
    failed = 0

    for row in fetch_rows(args.limit):
        if is_gsmarena_row(row) and args.skip_gsmarena:
            skipped_gsmarena += 1
            continue

        url = save_variant_image_file(row)
        if url:
            exported += 1
            if not args.quiet:
                print(f"OK variant_id={row['id']} -> {url}")
        elif row.get("image_data"):
            failed += 1
            print(f"FAILED variant_id={row['id']}", file=sys.stderr)
        else:
            empty += 1

    print(
        "\nDone: "
        f"exported={exported}, "
        f"skipped_gsmarena={skipped_gsmarena}, "
        f"empty={empty}, "
        f"failed={failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
