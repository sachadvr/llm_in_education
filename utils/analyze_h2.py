#!/usr/bin/env python3
"""
Analyse des résultats de simulation H2 (moteur adaptatif).
Lit depuis la DB (tables h2_runs/h2_session_rows/...) — fallback CSV si DB indisponible.

Usage:
    python analyze_h2.py                        # dernier run en DB
    python analyze_h2.py --run h2_api           # run spécifique
    python analyze_h2.py --list                 # liste tous les runs en DB
    python analyze_h2.py --sessions             # détail corrections
    python analyze_h2.py --priorities           # tableau priorités adaptatives
    python analyze_h2.py --exercises            # exercices générés
    python analyze_h2.py --all                  # tout
    python analyze_h2.py --dir benchmark_outputs/h2_api/  # fallback CSV
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path


# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_list_runs(session):
    from sqlalchemy import text
    q = text("SELECT run_id, started_at, learners, phrases_per_learner, top_priority_match_rate, adaptive_loop_success_rate FROM h2_runs ORDER BY created_at DESC")
    return (await session.execute(q)).fetchall()


async def db_fetch_run(session, run_id: str):
    from sqlalchemy import text
    q = text("SELECT * FROM h2_runs WHERE run_id = :r")
    return (await session.execute(q, {"r": run_id})).fetchone()


async def db_fetch_sessions(session, run_id: str):
    from sqlalchemy import text
    q = text("SELECT * FROM h2_session_rows WHERE run_id = :r ORDER BY learner_id, session_id, sentence_idx")
    return (await session.execute(q, {"r": run_id})).fetchall()


async def db_fetch_priorities(session, run_id: str):
    from sqlalchemy import text
    q = text("SELECT * FROM h2_priority_rows WHERE run_id = :r ORDER BY learner_id, session_id, rank")
    return (await session.execute(q, {"r": run_id})).fetchall()


async def db_fetch_exercises(session, run_id: str):
    from sqlalchemy import text
    q = text("SELECT * FROM h2_exercise_rows WHERE run_id = :r ORDER BY learner_id, session_id")
    return (await session.execute(q, {"r": run_id})).fetchall()


# ── CSV fallback helpers ───────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_latest_dir(base: Path) -> Path:
    candidates = sorted(
        [d for d in base.iterdir() if d.is_dir() and "h2" in d.name],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        print(f"Aucun dossier h2* trouvé dans {base}")
        sys.exit(1)
    return candidates[0]


# ── Print functions ────────────────────────────────────────────────────────────

def print_global(g: dict, config: dict):
    print("\n" + "=" * 65)
    print("BENCHMARK H2 — MOTEUR ADAPTATIF")
    print("=" * 65)
    print(f"\nRun        : {config.get('run_id', 'N/A')}")
    print(f"Config     : {config.get('learners')} learners × {config.get('phrases_per_learner')} phrases | seed={config.get('seed')}")
    print(f"Started    : {config.get('started_at', 'N/A')}")
    if config.get("note"):
        print(f"Note       : {config['note']}")

    print("\n--- Métriques globales ---")
    print(f"  Learners simulés          : {g.get('total_learners') or config.get('learners') or 'N/A'}")
    print(f"  top_priority_match_rate   : {g.get('top_priority_match_rate', 0):.2%}  ← H2 critère principal")
    print(f"  priority_shift_rate       : {g.get('priority_shift_rate', 0):.2%}  ← moteur recalcule après correction")
    print(f"  adaptive_loop_success_rate: {g.get('adaptive_loop_success_rate', 0):.2%}  ← exercice ciblé généré")
    print(f"  failed_correction_rate    : {g.get('failed_correction_rate', 0):.2%}")
    print(f"  simulated_error_reduction : {g.get('simulated_error_reduction_rate', 0):.2%}")
    print(f"  avg_api_latency           : {g.get('average_api_latency_ms', 0):.0f} ms")

    tpm = g.get("top_priority_match_rate", 0)
    als = g.get("adaptive_loop_success_rate", 0)
    print("\n--- Verdict H2 ---")
    print(f"  top_priority_match ≥ 80% : {'✓' if tpm >= 0.8 else '✗'}  ({tpm:.0%})")
    print(f"  adaptive_loop_success=100%: {'✓' if als >= 1.0 else '✗'}  ({als:.0%})")
    print(f"  → H2 {'VALIDÉE' if tpm >= 0.8 and als >= 1.0 else 'NON VALIDÉE'}")


def print_by_family(by_family: dict):
    if not by_family:
        return
    print("\n--- Par famille d'erreur ---")
    print(f"  {'Famille':<14} {'n':>3} {'top_match':>10} {'shift':>7} {'loop_ok':>8} {'weight_decay':>13}")
    print("  " + "-" * 58)
    for family, m in sorted(by_family.items()):
        wd = m.get("avg_weight_decay_pct")
        wd_str = f"{wd:.1%}" if wd is not None else "N/A"
        print(
            f"  {family:<14} {m.get('n', 0):>3}"
            f"  {m.get('top_priority_match_rate', 0):>9.0%}"
            f"  {m.get('priority_shift_rate', 0):>6.0%}"
            f"  {m.get('adaptive_loop_success_rate', 0):>7.0%}"
            f"  {wd_str:>12}"
        )


def print_sessions(rows):
    if not rows:
        return
    print("\n--- Sessions (corrections) ---")
    print(f"  {'Learner':<32} {'#':>3} {'type_détecté':<16} {'dominant_avant':<16} {'latency_ms':>11}")
    print("  " + "-" * 82)
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else r
        print(
            f"  {d.get('learner_id',''):<32} {str(d.get('sentence_idx','?')):>3}"
            f"  {(d.get('predicted_error_type') or '?'):<16}"
            f"  {(d.get('dominant_error_before') or '?'):<16}"
            f"  {float(d.get('api_latency_ms') or 0):>10.0f}"
        )


def print_priorities(rows):
    if not rows:
        return
    print("\n--- Priorités adaptatives par learner/session ---")
    print(f"  {'Learner':<32} {'sess':>5} {'type':<14} {'count':>6} {'weight':>7} {'rank':>5}")
    print("  " + "-" * 74)
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else r
        print(
            f"  {d.get('learner_id',''):<32} {str(d.get('session_id','?')):>5}"
            f"  {d.get('error_type',''):<14} {str(d.get('count','?')):>6}"
            f"  {float(d.get('weight') or 0):>7.2f} {str(d.get('rank','?')):>5}"
        )


def print_exercises(rows):
    if not rows:
        return
    print("\n--- Exercices adaptatifs générés ---")
    print(f"  {'Learner':<32} {'sess':>5} {'target':<14} {'grade':>6} {'latency_ms':>11}")
    print("  " + "-" * 74)
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else r
        print(
            f"  {d.get('learner_id',''):<32} {str(d.get('session_id','?')):>5}"
            f"  {(d.get('target_error_type') or '?'):<14} {str(d.get('grade_result') or '?'):>6}"
            f"  {float(d.get('api_latency_ms') or 0):>10.0f}"
        )

    graded = [r for r in rows if (dict(r._mapping) if hasattr(r, "_mapping") else r).get("grade_result") not in (None, "")]
    if graded:
        correct = sum(1 for r in graded if str((dict(r._mapping) if hasattr(r, "_mapping") else r).get("grade_result", "")).lower() == "true")
        print(f"\n  Exercise grade accuracy: {correct}/{len(graded)} = {correct/len(graded):.0%}")


def print_runs_list(rows):
    print("\n" + "=" * 75)
    print("RUNS H2 EN BASE")
    print("=" * 75)
    print(f"  {'run_id':<25} {'started_at':<22} {'learners':>8} {'phr/l':>6} {'top_match':>10} {'loop_ok':>8}")
    print("  " + "-" * 75)
    for r in rows:
        d = dict(r._mapping)
        print(
            f"  {d.get('run_id',''):<25}"
            f"  {str(d.get('started_at',''))[:19]:<22}"
            f"  {str(d.get('learners') or '?'):>8}"
            f"  {str(d.get('phrases_per_learner') or '?'):>6}"
            f"  {float(d.get('top_priority_match_rate') or 0):>9.0%}"
            f"  {float(d.get('adaptive_loop_success_rate') or 0):>7.0%}"
        )


# ── DB mode ───────────────────────────────────────────────────────────────────

async def run_db(args):
    from backend.storage import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        if args.list:
            rows = await db_list_runs(session)
            if not rows:
                print("Aucun run H2 en base. Lance: python migrate_h2_to_db.py")
                return
            print_runs_list(rows)
            return

        # Resolve run_id
        if args.run:
            run_id = args.run
        else:
            rows = await db_list_runs(session)
            if not rows:
                print("Aucun run H2 en base. Lance: python migrate_h2_to_db.py")
                sys.exit(1)
            run_id = dict(rows[0]._mapping)["run_id"]

        run = await db_fetch_run(session, run_id)
        if not run:
            print(f"Run '{run_id}' introuvable en base.")
            sys.exit(1)

        d = dict(run._mapping)
        g = {
            "top_priority_match_rate": d.get("top_priority_match_rate", 0),
            "priority_shift_rate": d.get("priority_shift_rate", 0),
            "adaptive_loop_success_rate": d.get("adaptive_loop_success_rate", 0),
            "failed_correction_rate": d.get("failed_correction_rate", 0),
            "simulated_error_reduction_rate": d.get("simulated_error_reduction_rate", 0),
            "average_api_latency_ms": d.get("average_api_latency_ms", 0),
        }
        config = {
            "run_id": d.get("run_id"),
            "learners": d.get("learners"),
            "phrases_per_learner": d.get("phrases_per_learner"),
            "seed": d.get("seed"),
            "started_at": d.get("started_at"),
            "note": d.get("note"),
        }
        by_family = json.loads(d.get("by_family") or "{}")

        print_global(g, config)
        print_by_family(by_family)

        if args.all or args.sessions:
            rows = await db_fetch_sessions(session, run_id)
            print_sessions(rows)

        if args.all or args.priorities:
            rows = await db_fetch_priorities(session, run_id)
            print_priorities(rows)

        if args.all or args.exercises:
            rows = await db_fetch_exercises(session, run_id)
            print_exercises(rows)

    print()


# ── CSV fallback mode ─────────────────────────────────────────────────────────

def run_csv(out_dir: Path, args):
    summary_path = out_dir / "h2_api_global_summary.json"
    config_path = out_dir / "run_config.json"

    if not summary_path.exists():
        print(f"Fichier manquant : {summary_path}")
        sys.exit(1)

    summary = load_json(summary_path)
    run_config = load_json(config_path) if config_path.exists() else {}
    run_config["run_id"] = out_dir.name

    g = summary.get("global", {})
    by_family = summary.get("by_family", {})

    print_global(g, run_config)
    print_by_family(by_family)

    if args.all or args.sessions:
        rows = load_csv(out_dir / "h2_api_sessions.csv")
        print_sessions(rows)

    if args.all or args.priorities:
        rows = load_csv(out_dir / "h2_api_priorities.csv")
        print_priorities(rows)

    if args.all or args.exercises:
        rows = load_csv(out_dir / "h2_api_exercises.csv")
        print_exercises(rows)

    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyse benchmark H2")
    parser.add_argument("--run", metavar="RUN_ID", help="run_id spécifique (défaut: dernier)")
    parser.add_argument("--list", action="store_true", help="Lister tous les runs en DB")
    parser.add_argument("--sessions", action="store_true", help="Détail corrections")
    parser.add_argument("--priorities", action="store_true", help="Tableau priorités adaptatives")
    parser.add_argument("--exercises", action="store_true", help="Exercices générés")
    parser.add_argument("--all", "-a", action="store_true", help="Tout afficher")
    parser.add_argument("--dir", "-d", metavar="DIR", help="Fallback: lire depuis dossier CSV")
    args = parser.parse_args()

    if args.dir:
        run_csv(Path(args.dir), args)
        return

    try:
        asyncio.run(run_db(args))
    except Exception as e:
        print(f"DB indisponible ({e}), fallback CSV...")
        base = Path("benchmark_outputs")
        if base.exists():
            out_dir = find_latest_dir(base)
            run_csv(out_dir, args)
        else:
            print("Pas de DB ni de fichiers CSV disponibles.")
            sys.exit(1)


if __name__ == "__main__":
    main()
