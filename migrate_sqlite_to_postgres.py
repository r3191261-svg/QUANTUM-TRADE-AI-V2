"""Copy the bot's local SQLite records into the configured PostgreSQL database."""

import argparse
import sqlite3
from pathlib import Path

import bot


TABLES = (
    "users",
    "admins",
    "signals",
    "audit",
    "source_posts",
    "source_deliveries",
    "admin_actions",
    "news",
)
SERIAL_TABLES = ("signals", "audit", "news")


def migrate(source_path):
    if not bot.DATABASE_URL:
        raise RuntimeError("Set DATABASE_URL to the destination PostgreSQL database.")

    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    bot.init_db()
    copied = {}
    with sqlite3.connect(source_path) as source, bot.connect_db() as destination:
        for table in TABLES:
            columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
            if not columns:
                continue
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            if not rows:
                copied[table] = 0
                continue

            column_sql = ", ".join(f'"{column}"' for column in columns)
            values_sql = ", ".join("?" for _ in columns)
            insert = (
                f'INSERT INTO "{table}" ({column_sql}) VALUES ({values_sql}) '
                "ON CONFLICT DO NOTHING"
            )
            inserted = 0
            for row in rows:
                inserted += destination.execute(insert, row).rowcount
            copied[table] = inserted

        for table in SERIAL_TABLES:
            destination.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {table}"
            )

    return copied


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite_path", help="Path to the existing quantum.db file")
    args = parser.parse_args()
    for table, count in migrate(args.sqlite_path).items():
        print(f"{table}: imported {count} rows")
