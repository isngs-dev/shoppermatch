"""One-off: copy every row from a local SQLite database into a Postgres
target (e.g. a Render/Railway managed database), replacing whatever is
already there.

This is NOT part of the running app — it's a manual tool for pushing real
local demo/test data (built up through actual usage) to a live deployment,
as an alternative to AUTO_SEED's generic synthetic dataset.

Usage:
    python -m app.scripts.migrate_local_to_postgres --target "postgresql://user:pass@host:port/db" [--source sqlite+aiosqlite:///./shoppermatch.db] [--yes]

Safety:
  - Refuses to run if the source database has zero users (almost certainly
    the wrong file, and this would otherwise silently wipe the target).
  - Without --yes, prints what it's about to do and stops for confirmation.
  - Wipes the target with TRUNCATE ... CASCADE (all tables, one statement,
    order-independent) before inserting — this is a full replace, not a
    merge.
  - Tables are inserted in Base.metadata.sorted_tables order (topologically
    sorted by FK dependency) so parent rows always land before the children
    that reference them — the same ordering bug this app hit once already
    (see the seed.py fix) doesn't get repeated here.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import defaultdict

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from ..database import Base
from .. import models  # noqa: F401  (registers all tables on Base.metadata)


def _normalize_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


async def _row_counts(engine) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            result = await conn.scalar(select(func.count()).select_from(table))
            counts[table.name] = result or 0
    return counts


async def migrate(source_url: str, target_url: str, assume_yes: bool) -> None:
    target_url = _normalize_postgres_url(target_url)

    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)

    source_counts = await _row_counts(source_engine)
    total_source_rows = sum(source_counts.values())

    if source_counts.get("users", 0) == 0:
        print(f"Source ({source_url}) has zero users — refusing to run "
              "(this would wipe the target with nothing to replace it).")
        sys.exit(1)

    print(f"Source:  {source_url}")
    print(f"Target:  {target_url.split('@')[-1]}  (host/db shown only, credentials hidden)")
    print("\nRows to copy (source):")
    for name, count in source_counts.items():
        if count:
            print(f"  {name:<28} {count}")
    print(f"\nTotal: {total_source_rows} rows across {len(source_counts)} tables.")
    print("\nThis will TRUNCATE every one of those tables on the TARGET first "
          "(full replace, not a merge) and then insert the rows above.")

    if not assume_yes:
        answer = input("\nType 'yes' to proceed: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return

    async with source_engine.connect() as src_conn:
        rows_by_table: dict[str, list[dict]] = {}
        for table in Base.metadata.sorted_tables:
            result = await src_conn.execute(select(table))
            rows_by_table[table.name] = [dict(row._mapping) for row in result.fetchall()]

    # Some legacy local rows predate a NOT-NULL column being added (e.g.
    # `updated_at` on a few models) — SQLite never enforced NOT NULL on
    # those retroactively, so they carry an explicit NULL. Postgres
    # correctly rejects that. Rather than insert a NULL, drop the key from
    # the row entirely wherever the target column is NOT NULL and has a
    # default — SQLAlchemy's Core insert() then applies the real column
    # default (same as a normal ORM insert would have), instead of us
    # guessing a value.
    for table in Base.metadata.sorted_tables:
        defaultable = {
            c.name for c in table.columns
            if not c.nullable and (c.default is not None or c.server_default is not None)
        }
        if not defaultable:
            continue
        for row in rows_by_table[table.name]:
            for col_name in defaultable:
                if row.get(col_name) is None:
                    del row[col_name]

    async with target_engine.begin() as tgt_conn:
        table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        await tgt_conn.execute(text(f"TRUNCATE TABLE {table_names} CASCADE"))

        CHUNK = 500
        for table in Base.metadata.sorted_tables:
            rows = rows_by_table[table.name]
            total = len(rows)
            if not total:
                continue

            # executemany requires every row in one batch to share the same
            # parameter set (same keys) — dropping None defaultable keys
            # per-row above can make rows in the same table disagree on
            # which keys are present. Group rows by their exact key set so
            # each group can still go through as one fast batched insert
            # instead of a network round trip per row; only rows that
            # genuinely differ in shape pay for a separate batch.
            groups: dict[frozenset, list[dict]] = defaultdict(list)
            for row in rows:
                groups[frozenset(row.keys())].append(row)

            start = time.monotonic()
            done = 0
            for group_rows in groups.values():
                for i in range(0, len(group_rows), CHUNK):
                    chunk = group_rows[i : i + CHUNK]
                    await tgt_conn.execute(table.insert(), chunk)
                    done += len(chunk)
                    print(f"  {table.name}: {done}/{total}", end="\r", flush=True)
            elapsed = time.monotonic() - start
            print(f"  inserted {total:>5} into {table.name:<28} ({elapsed:.1f}s)")

    target_counts = await _row_counts(target_engine)
    mismatches = {
        name: (source_counts[name], target_counts[name])
        for name in source_counts
        if source_counts[name] != target_counts[name]
    }
    if mismatches:
        print("\nWARNING — row count mismatches after migration:")
        for name, (src, tgt) in mismatches.items():
            print(f"  {name}: source={src} target={tgt}")
        sys.exit(1)

    print("\nDone — target row counts match source for every table.")

    await source_engine.dispose()
    await target_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="sqlite+aiosqlite:///./shoppermatch.db")
    parser.add_argument("--target", required=True, help="Postgres connection string")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.target, args.yes))


if __name__ == "__main__":
    main()
