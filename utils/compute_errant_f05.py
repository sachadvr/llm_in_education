#!/usr/bin/env python3
"""
compute_errant_f05.py — Backfill errant_f05 on benchmark_rows.

Usage:
    python3 compute_errant_f05.py [--batch-size 200] [--dry-run]
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("USE_OLLAMA", "false")

import asyncpg
import errant as errant_lib

BETA = 0.5


def _fbeta(tp: float, fp: float, fn: float, beta: float) -> float:
    denom = (1 + beta ** 2) * tp + beta ** 2 * fn + fp
    return ((1 + beta ** 2) * tp / denom) if denom else 0.0


def compute_errant_f05(nlp, src: str, hyp: str, ref: str) -> float:
    orig = nlp.parse(src)
    hyp_p = nlp.parse(hyp)
    ref_p = nlp.parse(ref)

    hyp_edits = {(e.o_start, e.o_end, e.c_str) for e in nlp.annotate(orig, hyp_p)}
    ref_edits  = {(e.o_start, e.o_end, e.c_str) for e in nlp.annotate(orig, ref_p)}

    if not hyp_edits and not ref_edits:
        return 1.0

    tp = len(hyp_edits & ref_edits)
    fp = len(hyp_edits - ref_edits)
    fn = len(ref_edits - hyp_edits)
    return round(_fbeta(tp, fp, fn, BETA), 4)


async def run(args: argparse.Namespace) -> None:
    print("Loading ERRANT (spaCy en)…")
    nlp = errant_lib.load("en")
    print("ERRANT ready.")

    db_url = args.db_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_url)

    total = await conn.fetchval(
        "SELECT COUNT(*) FROM benchmark_rows WHERE errant_f05 IS NULL"
    )
    print(f"Rows to process: {total}")

    updated = 0
    errors = 0

    while True:
        rows = await conn.fetch(
            """
            SELECT id, input_phrase, corrected, gold
            FROM benchmark_rows
            WHERE errant_f05 IS NULL
            ORDER BY id
            LIMIT $1
            """,
            args.batch_size,
        )
        if not rows:
            break

        updates = []
        for r in rows:
            try:
                score = compute_errant_f05(nlp, r["input_phrase"], r["corrected"], r["gold"])
                updates.append((score, r["id"]))
            except Exception as exc:
                print(f"  ERROR id={r['id']}: {exc}")
                errors += 1
                updates.append((None, r["id"]))

        if not args.dry_run and updates:
            await conn.executemany(
                "UPDATE benchmark_rows SET errant_f05 = $1 WHERE id = $2",
                updates,
            )

        updated += len(updates)
        print(f"  {updated}/{total} processed  (errors: {errors})")

    await conn.close()
    print(f"\nDone. updated={updated - errors}  errors={errors}  dry_run={args.dry_run}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db-url", type=str,
                    default=os.environ.get("DATABASE_URL",
                                           "postgresql://app:app@db:5432/app"))
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
