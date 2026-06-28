"""Migrate images from Postgres `images` table to Hydrus Network.

One-shot script. Requires DATABASE_URL, HYDRUS_URL, and HYDRUS_KEY in .env.
Verify with --dry-run first.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be done but don't upload")
    parser.add_argument("--drop", action="store_true",
                        help="DROP the images table after successful migration")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set")

    hydrus_url = os.environ.get("HYDRUS_URL")
    hydrus_key = os.environ.get("HYDRUS_KEY")
    if not hydrus_url or not hydrus_key:
        sys.exit("HYDRUS_URL and HYDRUS_KEY must be set")

    import psycopg
    from philippe._hydrus import HydrusClient

    hydrus = HydrusClient(hydrus_url, hydrus_key)
    conn = psycopg.connect(dsn, autocommit=True)

    with conn.cursor() as cur:
        cur.execute("SELECT hash, blob FROM images ORDER BY hash")
        rows = cur.fetchall()

    if not rows:
        print("No images to migrate.")
        return

    print(f"Migrating {len(rows)} images...")
    uploaded = 0
    skipped = 0
    for h, blob in rows:
        if args.dry_run:
            print(f"  [dry-run] would upload {h} ({len(bytes(blob))} bytes)")
            uploaded += 1
        else:
            try:
                result_hash = hydrus.upload(bytes(blob))
                print(f"  uploaded {h} → {result_hash}")
                uploaded += 1
            except Exception as e:
                print(f"  skipped {h}: {e}")
                skipped += 1

    print(f"Done: {uploaded} uploaded, {skipped} skipped.")

    if args.drop and not args.dry_run and skipped == 0:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS images")
        print("Dropped images table.")
    elif args.drop and skipped > 0:
        print("Not dropping: some images failed to migrate.")

    conn.close()


if __name__ == "__main__":
    main()
