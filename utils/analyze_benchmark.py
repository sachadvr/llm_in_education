#!/usr/bin/env python3
"""
Analyse des résultats benchmark H1 depuis benchmark_rows.

Usage:
    python analyze_benchmark.py                  # résumé global
    python analyze_benchmark.py --by-type        # breakdown par error_type
    python analyze_benchmark.py --export results.csv
    python analyze_benchmark.py --runs           # historique des runs (table benchmarks)
"""

import argparse
import asyncio
import csv
import sys
from datetime import timedelta

from sqlalchemy import select, text


async def fetch_aggregated(session):
    q = text("""
        SELECT
            model_name,
            count(*)                                        AS n,
            round(avg(f05)::numeric, 4)                    AS avg_f05,
            round(avg(precision)::numeric, 4)              AS avg_p,
            round(avg(recall)::numeric, 4)                 AS avg_r,
            round(avg(exact_match::int)::numeric, 4)       AS exact_match,
            round(avg(span_f05)::numeric, 4)               AS avg_span_f05,
            round(avg(error_type_match::int)::numeric, 4)  AS type_acc,
            round(avg(feedback_present::int)::numeric, 4)  AS feedback_present,
            round(avg(feedback_type_match::int)::numeric, 4) AS feedback_type_match,
            round(avg(feedback_valid::int)::numeric, 4)    AS feedback_valid
        FROM benchmark_rows
        GROUP BY model_name
        ORDER BY model_name
    """)
    return (await session.execute(q)).fetchall()


async def fetch_by_error_type(session):
    q = text("""
        SELECT
            model_name,
            error_type_gold,
            count(*)                                        AS n,
            round(avg(f05)::numeric, 4)                    AS avg_f05,
            round(avg(exact_match::int)::numeric, 4)       AS exact_match,
            round(avg(error_type_match::int)::numeric, 4)  AS type_acc,
            round(avg(span_f05)::numeric, 4)               AS avg_span_f05
        FROM benchmark_rows
        GROUP BY model_name, error_type_gold
        ORDER BY error_type_gold, model_name
    """)
    return (await session.execute(q)).fetchall()


async def fetch_runs(session):
    q = text("""
        SELECT model_name, pipeline_version, dataset_size,
               errant_f05, errant_precision, errant_recall,
               exact_match_accuracy, error_type_accuracy,
               avg_span_f05, feedback_valid_rate, latency_avg_ms,
               created_at
        FROM benchmarks
        ORDER BY created_at DESC
        LIMIT 30
    """)
    return (await session.execute(q)).fetchall()


async def fetch_type_alignment(session, model_name: str = "pipeline_structuré"):
    q = text("""
        SELECT
            error_type_gold,
            count(*)                                       AS n,
            round(avg(error_type_match::int)::numeric, 4) AS alignment_rate
        FROM benchmark_rows
        WHERE model_name = :model
        GROUP BY error_type_gold
        ORDER BY n DESC
    """)
    return (await session.execute(q, {"model": model_name})).fetchall()


async def fetch_predicted_distribution(session, model_name: str = "pipeline_structuré"):
    q = text("""
        SELECT
            error_type_predicted,
            count(*) AS n,
            round(count(*) * 100.0 / sum(count(*)) OVER (), 2) AS pct
        FROM benchmark_rows
        WHERE model_name = :model
        GROUP BY error_type_predicted
        ORDER BY n DESC
    """)
    return (await session.execute(q, {"model": model_name})).fetchall()


async def fetch_errant_mean(session):
    """Average ERRANT metrics across runs in `benchmarks` (excludes failed runs with errant_f05=0)."""
    q = text("""
        SELECT model_name,
               count(*) FILTER (WHERE errant_f05 > 0) AS n_runs,
               AVG(errant_f05)        FILTER (WHERE errant_f05 > 0) AS errant_f05,
               STDDEV(errant_f05)     FILTER (WHERE errant_f05 > 0) AS errant_f05_std,
               AVG(errant_precision)  FILTER (WHERE errant_f05 > 0) AS errant_p,
               AVG(errant_recall)     FILTER (WHERE errant_f05 > 0) AS errant_r
        FROM benchmarks
        GROUP BY model_name
        ORDER BY model_name
    """)
    return (await session.execute(q)).fetchall()


async def fetch_all_rows(session):
    q = text("""
        SELECT model_name, input_phrase, corrected, gold,
               f05, exact_match, span_f05,
               error_type_gold, error_type_predicted, error_type_match,
               feedback_present, feedback_type_match, created_at
        FROM benchmark_rows
        ORDER BY model_name, created_at
    """)
    return (await session.execute(q)).fetchall()


async def fetch_h2_latest(session):
    q = text("""
        SELECT run_id, learners, top_priority_match_rate, adaptive_loop_success_rate,
               priority_shift_rate, failed_correction_rate, by_family, created_at
        FROM h2_runs
        ORDER BY created_at DESC
        LIMIT 1
    """)
    return (await session.execute(q)).first()


def print_markdown_tables(agg_rows, errant_rows, type_rows, dist_rows, h2_row):
    """Print all mémoire tables as markdown blocks for direct copy-paste."""
    configs = ["llm_brut", "pipeline_structuré", "pipeline+mémoire"]
    agg = {r.model_name: r for r in agg_rows}
    err = {r.model_name: r for r in errant_rows}

    print("\n" + "#" * 78)
    print("# TABLEAUX MARKDOWN POUR LE MÉMOIRE")
    print("#" * 78)

    # ---- Tableau 4.1 ----
    print("\n### Tableau 4.1 — Métriques agrégées sur le dataset complet\n")
    print("|Métrique|llm_brut|pipeline_structuré|pipeline+mémoire|Interprétation|")
    print("| ---| ---: | ---: | ---: | --- |")
    g = lambda c, a: float(getattr(agg.get(c), a) or 0)
    n = lambda c: int(getattr(agg.get(c), "n", 0) or 0)
    print(f"|Nombre d'exemples|{n('llm_brut')}|{n('pipeline_structuré')}|{n('pipeline+mémoire')}|exemples exploitables|")
    print(f"|F0,5 token-sequence|{g('llm_brut','avg_f05'):.4f}|{g('pipeline_structuré','avg_f05'):.4f}|{g('pipeline+mémoire','avg_f05'):.4f}|qualité proche de la baseline|")
    print(f"|Précision|{g('llm_brut','avg_p'):.4f}|{g('pipeline_structuré','avg_p'):.4f}|{g('pipeline+mémoire','avg_p'):.4f}|légère baisse|")
    print(f"|Rappel|{g('llm_brut','avg_r'):.4f}|{g('pipeline_structuré','avg_r'):.4f}|{g('pipeline+mémoire','avg_r'):.4f}|légère baisse|")
    print(f"|Exact match|{g('llm_brut','exact_match'):.4f}|{g('pipeline_structuré','exact_match'):.4f}|{g('pipeline+mémoire','exact_match'):.4f}|amélioration|")
    print(f"|Span F0,5|{g('llm_brut','avg_span_f05'):.4f}|{g('pipeline_structuré','avg_span_f05'):.4f}|{g('pipeline+mémoire','avg_span_f05'):.4f}|meilleure localisation|")
    print(f"|Type accuracy|{g('llm_brut','type_acc'):.4f}|{g('pipeline_structuré','type_acc'):.4f}|{g('pipeline+mémoire','type_acc'):.4f}|stable|")
    print(f"|Feedback present|{g('llm_brut','feedback_present'):.4f}|{g('pipeline_structuré','feedback_present'):.4f}|{g('pipeline+mémoire','feedback_present'):.4f}|feedback systématique|")
    print(f"|Feedback type↔gold|{g('llm_brut','feedback_type_match'):.4f}|{g('pipeline_structuré','feedback_type_match'):.4f}|{g('pipeline+mémoire','feedback_type_match'):.4f}|alignement partiel|")

    # ---- Tableau 4.2 ----
    print("\n### Tableau 4.2 — ERRANT F0,5 (moyenne sur runs valides)\n")
    print("|Métrique|llm_brut|pipeline_structuré|pipeline+mémoire|")
    print("| ---| ---: | ---: | ---: |")
    e = lambda c, a: float(getattr(err.get(c), a) or 0)
    es = lambda c: float(getattr(err.get(c), "errant_f05_std", 0) or 0)
    nr = lambda c: int(getattr(err.get(c), "n_runs", 0) or 0)
    print(f"|n_runs valides|{nr('llm_brut')}|{nr('pipeline_structuré')}|{nr('pipeline+mémoire')}|")
    print(f"|ERRANT F0,5 (moyenne ± écart-type)|{e('llm_brut','errant_f05'):.4f} ± {es('llm_brut'):.4f}|{e('pipeline_structuré','errant_f05'):.4f} ± {es('pipeline_structuré'):.4f}|{e('pipeline+mémoire','errant_f05'):.4f} ± {es('pipeline+mémoire'):.4f}|")
    print(f"|ERRANT Précision|{e('llm_brut','errant_p'):.4f}|{e('pipeline_structuré','errant_p'):.4f}|{e('pipeline+mémoire','errant_p'):.4f}|")
    print(f"|ERRANT Rappel|{e('llm_brut','errant_r'):.4f}|{e('pipeline_structuré','errant_r'):.4f}|{e('pipeline+mémoire','errant_r'):.4f}|")

    # ---- Tableau 4.3 ----
    print("\n### Tableau 4.3 — Analyse typologique du classifieur heuristique (pipeline_structuré)\n")
    print("|Type d'erreur gold|Nombre d'exemples|Taux d'alignement|")
    print("| ---| ---: | ---: |")
    for r in type_rows:
        print(f"|{r.error_type_gold or 'unknown'}|{r.n}|{float(r.alignment_rate or 0):.4f}|")

    # ---- Tableau 4.4 ----
    print("\n### Tableau 4.4 — Distribution des types prédits (pipeline_structuré)\n")
    print("|Type prédit|Nombre|Pourcentage|")
    print("| ---| ---: | ---: |")
    for r in dist_rows:
        print(f"|{r.error_type_predicted or 'none'}|{r.n}|{float(r.pct or 0):.2f} %|")

    # ---- H2 ----
    print("\n### Tableau H2 — Validation fonctionnelle du moteur adaptatif\n")
    if h2_row:
        print("|Métrique|Valeur|")
        print("| ---| ---: |")
        print(f"|run_id|{h2_row.run_id}|")
        print(f"|Nombre de profils simulés|{h2_row.learners}|")
        print(f"|top_priority_match_rate|{100*float(h2_row.top_priority_match_rate or 0):.0f} %|")
        print(f"|adaptive_loop_success_rate|{100*float(h2_row.adaptive_loop_success_rate or 0):.0f} %|")
        print(f"|priority_shift_rate|{100*float(h2_row.priority_shift_rate or 0):.0f} %|")
        print(f"|failed_correction_rate|{100*float(h2_row.failed_correction_rate or 0):.0f} %|")
    else:
        print("Aucun run H2 trouvé.")


def print_errant_mean(errant_rows):
    print("\n" + "=" * 70)
    print("ERRANT (moyenne sur runs valides, table benchmarks)")
    print("=" * 70)
    configs = ["llm_brut", "pipeline_structuré", "pipeline+mémoire"]
    data = {r.model_name: r for r in errant_rows}
    for name in configs:
        r = data.get(name)
        if not r or not r.n_runs:
            continue
        std = float(r.errant_f05_std or 0)
        print(f"\n{name} (n_runs={r.n_runs}):")
        print(f"  ERRANT F0.5       : {float(r.errant_f05):.4f}  (±{std:.4f})")
        print(f"  ERRANT Precision  : {float(r.errant_p):.4f}")
        print(f"  ERRANT Recall     : {float(r.errant_r):.4f}")


def print_summary(rows):
    configs = ["llm_brut", "pipeline_structuré", "pipeline+mémoire"]
    data = {r.model_name: r for r in rows}

    print("\n" + "=" * 70)
    print("BENCHMARK H1 — RÉSUMÉ PAR CONFIG")
    print("=" * 70)

    for name in configs:
        r = data.get(name)
        if not r:
            continue
        print(f"\n{name} (n={r.n}):")
        print(f"  F0.5              : {r.avg_f05}")
        print(f"  Precision         : {r.avg_p}")
        print(f"  Recall            : {r.avg_r}")
        print(f"  Exact match       : {r.exact_match}")
        print(f"  Span F0.5         : {r.avg_span_f05}")
        print(f"  Type accuracy     : {r.type_acc}")
        print(f"  Feedback present  : {r.feedback_present}")
        print(f"  Feedback type↔gold: {r.feedback_type_match}")

    # Delta vs baseline
    baseline = data.get("llm_brut")
    if not baseline:
        return
    print("\n" + "-" * 70)
    print("DELTA vs llm_brut")
    print("-" * 70)
    headers = ["metric", "pipeline_structuré", "pipeline+mémoire"]
    metrics = [
        ("F0.5",               "avg_f05"),
        ("Precision",          "avg_p"),
        ("Recall",             "avg_r"),
        ("Exact match",        "exact_match"),
        ("Span F0.5",          "avg_span_f05"),
        ("Type accuracy",      "type_acc"),
        ("Feedback present",   "feedback_present"),
        ("Feedback type↔gold", "feedback_type_match"),
    ]
    print(f"{'Metric':<22} {'pipeline_structuré':>20} {'pipeline+mémoire':>18}")
    print("-" * 62)
    for label, attr in metrics:
        base_val = float(getattr(baseline, attr) or 0)
        vals = []
        for cfg in ["pipeline_structuré", "pipeline+mémoire"]:
            r = data.get(cfg)
            v = float(getattr(r, attr) or 0) if r else 0.0
            delta = v - base_val
            sign = "+" if delta >= 0 else ""
            vals.append(f"{sign}{delta:.4f}")
        print(f"  {label:<20} {vals[0]:>20} {vals[1]:>18}")

    print()
    print("H1 — Interprétation rapide:")
    ps = data.get("pipeline_structuré")
    pm = data.get("pipeline+mémoire")
    if ps and pm:
        f05_delta = float(ps.avg_f05 or 0) - float(baseline.avg_f05 or 0)
        span_delta = float(ps.avg_span_f05 or 0) - float(baseline.avg_span_f05 or 0)
        em_delta = float(ps.exact_match or 0) - float(baseline.exact_match or 0)
        fb = float(ps.feedback_present or 0)
        print(f"  F0.5 delta        : {f05_delta:+.4f}  {'✓ pas de dégradation significative' if abs(f05_delta) < 0.05 else '⚠ dégradation notable'}")
        print(f"  Span F0.5 delta   : {span_delta:+.4f}  {'✓ amélioration localisation' if span_delta > 0 else '✗'}")
        print(f"  Exact match delta : {em_delta:+.4f}  {'✓ plus de corrections exactes' if em_delta > 0 else ''}")
        print(f"  Feedback present  : {fb:.0%}  {'✓ feedback systématique' if fb > 0.9 else '⚠ partiel'}")


def print_by_type(rows):
    from collections import defaultdict
    by_type = defaultdict(dict)
    for r in rows:
        by_type[r.error_type_gold][r.model_name] = r

    configs = ["llm_brut", "pipeline_structuré", "pipeline+mémoire"]

    print("\n" + "=" * 90)
    print("BREAKDOWN PAR ERROR TYPE")
    print("=" * 90)
    print(f"{'Type':<14} {'Config':<25} {'n':>4} {'F0.5':>7} {'exact':>7} {'span_F05':>9} {'type_acc':>9}")
    print("-" * 90)

    for etype in sorted(by_type.keys()):
        for cfg in configs:
            r = by_type[etype].get(cfg)
            if not r:
                continue
            print(f"  {etype:<12} {cfg:<25} {r.n:>4} {r.avg_f05:>7} {r.exact_match:>7} {r.avg_span_f05:>9} {r.type_acc:>9}")
        print()


def print_runs(rows):
    print("\n" + "=" * 70)
    print("HISTORIQUE DES RUNS (table benchmarks)")
    print("=" * 70)

    from datetime import timedelta
    runs = []
    current = []
    cur_time = None
    for r in rows:
        t = r.created_at
        if cur_time is None or abs((cur_time - t).total_seconds()) > 300:
            if current:
                runs.append(current)
            current = [r]
            cur_time = t
        else:
            current.append(r)
    if current:
        runs.append(current)

    for i, run in enumerate(runs):
        print(f"\nRun {i+1} — {run[0].created_at}")
        for r in run:
            print(f"  {r.model_name:<25} ERRANT F0.5={r.errant_f05:.4f} | P={r.errant_precision:.4f} | R={r.errant_recall:.4f} | type_acc={r.error_type_accuracy:.4f} | span_f05={r.avg_span_f05:.4f} | feedback={r.feedback_valid_rate:.4f}")


def print_type_alignment(rows, model_name: str = "pipeline_structuré"):
    print("\n" + "=" * 60)
    print(f"TABLEAU 4.2 — ANALYSE TYPOLOGIQUE DU CLASSIFIEUR ({model_name})")
    print("=" * 60)
    print(f"  {'Type d\'erreur gold':<22} {'n':>6} {'Taux d\'alignement':>18}")
    print("-" * 60)
    for r in rows:
        print(f"  {(r.error_type_gold or 'unknown'):<22} {r.n:>6} {float(r.alignment_rate or 0):>18.4f}")
    print()


def print_predicted_distribution(rows, model_name: str = "pipeline_structuré"):
    print("\n" + "=" * 60)
    print(f"TABLEAU 4.3 — DISTRIBUTION DES TYPES PRÉDITS ({model_name})")
    print("=" * 60)
    print(f"  {'Type prédit':<22} {'Nombre':>8} {'Pourcentage':>12}")
    print("-" * 60)
    for r in rows:
        print(f"  {(r.error_type_predicted or 'none'):<22} {r.n:>8} {float(r.pct or 0):>11.2f} %")
    print()


def export_csv(rows, path):
    cols = [
        "model_name", "input_phrase", "corrected", "gold",
        "f05", "exact_match", "span_f05",
        "error_type_gold", "error_type_predicted", "error_type_match",
        "feedback_present", "feedback_type_match", "created_at",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for r in rows:
            writer.writerow([getattr(r, c, "") for c in cols])
    print(f"Exported {len(rows)} rows → {path}")


async def main(args):
    from backend.storage import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        if args.runs:
            rows = await fetch_runs(session)
            print_runs(rows)
            return

        agg = await fetch_aggregated(session)
        if not agg:
            print("Aucune donnée dans benchmark_rows. Lance le benchmark d'abord.")
            sys.exit(1)

        print_summary(agg)

        if args.by_type:
            type_rows = await fetch_by_error_type(session)
            print_by_type(type_rows)

        if args.typological:
            model = args.model or "pipeline_structuré"
            align_rows = await fetch_type_alignment(session, model)
            print_type_alignment(align_rows, model)
            dist_rows = await fetch_predicted_distribution(session, model)
            print_predicted_distribution(dist_rows, model)

        if args.export:
            all_rows = await fetch_all_rows(session)
            export_csv(all_rows, args.export)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyse benchmark H1")
    parser.add_argument("--by-type", action="store_true", help="Breakdown par error_type")
    parser.add_argument("--typological", action="store_true", help="Tableau 4.2 (alignement par type gold) + 4.3 (distribution types prédits)")
    parser.add_argument("--model", default=None, help="Config pour --typological (défaut: pipeline_structuré)")
    parser.add_argument("--export", metavar="FILE.csv", help="Exporter toutes les lignes en CSV")
    parser.add_argument("--runs", action="store_true", help="Historique des runs (table benchmarks)")
    args = parser.parse_args()

    asyncio.run(main(args))
