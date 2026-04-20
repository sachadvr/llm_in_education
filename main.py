"""
API correction grammaticale et feedback pédagogique (ALAO).
Pipeline NLP (tokenisation → correcteur → classification → feedback),
moteur d'adaptativité, Redis, PostgreSQL+pgvector, logs anonymisés.
"""
import argparse
import asyncio
import json
import logging
import hashlib
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from pathlib import Path

from sqlalchemy.sql import text

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from backend.auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    create_session_token,
    get_current_user,
    hash_password,
    logout_session,
    verify_password,
)
from backend.schemas import LoginRequest, RegisterRequest, UserResponse
from backend.cache import SimpleCache
from backend.settings import settings
from backend.storage import AsyncSessionLocal, engine, metadata, users_table
from backend.routes.poster import router as poster_router
from backend.routes.learning import router as learning_router
from backend.routes.evaluation import router as evaluation_router
from backend.routes.analytics import router as analytics_router
from backend.routes.benchmark import router as benchmark_router

# Helpers
# settings.is_ollama_enabled(app) is used directly where needed

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_available = False
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        async with engine.begin() as conn2:
            await conn2.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn2.execute(text("ALTER TABLE IF EXISTS dataset ADD COLUMN IF NOT EXISTS embedding TEXT"))
            await conn2.execute(text("ALTER TABLE IF EXISTS learner_progression ADD COLUMN IF NOT EXISTS mastery_level INTEGER DEFAULT 0"))
            await conn2.execute(text("ALTER TABLE IF EXISTS learner_progression ADD COLUMN IF NOT EXISTS next_review_at TIMESTAMP WITH TIME ZONE"))
        app.state.db_available = True
    except Exception:
        app.state.db_available = True

    app.state.local_cache = SimpleCache()
    app.state.redis = None
    if settings.redis_url:
        try:
            import redis.asyncio as aioredis
            app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await app.state.redis.ping()
        except Exception:
            app.state.redis = None

    app.state.use_ollama_override = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{settings.ollama_host.rstrip('/')}/api/tags", timeout=2.0)
        app.state.ollama_available = r.status_code == 200
    except Exception:
        app.state.ollama_available = False
    yield
    if getattr(app.state, "redis", None):
        try:
            await app.state.redis.aclose()
        except Exception:
            pass



app = FastAPI(
    title="MVP Correction ALAO/LLM",
    description="Pipeline NLP, adaptativité, Redis, pgvector, logs anonymisés",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://mvp.ergonis.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.include_router(poster_router)
app.include_router(learning_router)
app.include_router(evaluation_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(benchmark_router, prefix="/api")

logger = logging.getLogger("mvp")
logger.setLevel(logging.INFO)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Logs anonymisés (poster) : pas de corps de requête, pas de phrase utilisateur."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    if not request.url.path.startswith("/static"):
        logger.info("request method=%s path=%s status=%s duration_ms=%.0f", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.middleware("http")
async def auth_gatekeeper(request: Request, call_next):
    """Gatekeeper: require login before serving any content (except login page itself).
    
    Sets request.state.current_user with user info for authenticated requests.
    """
    public_paths = ["/health", "/login", "/register", "/me", "/docs", "/openapi.json", "/redoc"]
    path = request.url.path

    # Always allow CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # Always allow public paths and static assets
    if path in public_paths or path.startswith("/static/") or path.startswith("/assets/"):
        return await call_next(request)

    # Check session and set current user
    user_session = get_current_user(request)
    if user_session:
        request.state.current_user = {
            "user_id": user_session["user_id"],
            "username": user_session["username"],
        }
        return await call_next(request)

    # No valid session — return 401 JSON for API/fetch calls, HTML page for browser navigation
    origin = request.headers.get("origin", "")
    cors_headers = {}
    allowed_origins = ["http://localhost:5173", "http://localhost:3000", "https://mvp.ergonis.app"]
    if origin in allowed_origins:
        cors_headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    accept = request.headers.get("accept", "")
    if "application/json" in accept or "text/html" not in accept:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401, headers=cors_headers)

    from fastapi.responses import HTMLResponse
    login_page = """<!DOCTYPE html>
<html><head><title>Login Required - ALAO Learning</title><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #f0f2f5; }
.login-container { background: white; padding: 2.5rem; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); width: 100%; max-width: 400px; }
h1 { margin: 0 0 0.5rem; font-size: 1.75rem; text-align: center; color: #1a1a1a; }
p.subtitle { text-align: center; color: #666; margin-bottom: 2rem; font-size: 0.9rem; }
input { width: 100%; padding: 0.875rem; margin-bottom: 1.25rem; border: 1px solid #dcdfe6; border-radius: 8px; box-sizing: border-box; font-size: 1rem; transition: border-color 0.2s; }
input:focus { outline: none; border-color: #4F46E5; box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }
button { width: 100%; padding: 0.875rem; background: #4F46E5; color: white; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background-color 0.2s, transform 0.1s; }
button:hover { background: #4338CA; }
button:active { transform: translateY(1px); }
.error { color: #DC2626; text-align: center; margin-top: 1rem; font-size: 0.875rem; padding: 0.75rem; background: #FEF2F2; border-radius: 6px; border: 1px solid #FEE2E2; }
.register-link { text-align: center; margin-top: 1rem; font-size: 0.875rem; }
.register-link a { color: #4F46E5; text-decoration: none; }
.register-link a:hover { text-decoration: underline; }
</style></head>
<body>
<div class="login-container">
<h1>ALAO Learning</h1>
<p class="subtitle">Connectez-vous pour acceder a votre session d'apprentissage</p>
<form id="loginForm">
<input type="text" id="username" name="username" placeholder="Nom d'utilisateur" required autofocus>
<input type="password" id="password" name="password" placeholder="Mot de passe" required>
<button type="submit">Se connecter</button>
</form>
<p class="register-link">Pas encore de compte? <a href="/register">S'inscrire</a></p>
<p id="error" class="error" style="display:none;"></p>
</div>
<script>
document.getElementById('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const error = document.getElementById('error');
    error.style.display = 'none';
    try {
        const res = await fetch('/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password})
        });
        if (res.ok) {
            window.location.reload();
        } else {
            const data = await res.json();
            error.textContent = data.detail || 'Identifiants incorrects';
            error.style.display = 'block';
        }
    } catch (err) {
        error.textContent = 'Erreur de connexion';
        error.style.display = 'block';
    }
});
</script>
</body></html>"""
    return HTMLResponse(content=login_page, status_code=200)


@app.post("/login")
async def login(req: LoginRequest):
    """Authenticate user against database and create session."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(users_table).where(users_table.c.username == req.username)
        )
        user = result.fetchone()

        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = create_session_token(user_id=user.id, username=user.username)

        response = JSONResponse({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
            }
        })
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax"
        )
        return response


@app.post("/register")
async def register(req: RegisterRequest):
    """Register a new user."""
    from sqlalchemy import select

    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    if len(req.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")

    if len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")

    async with AsyncSessionLocal() as session:
        # Check if username already exists
        result = await session.execute(
            select(users_table).where(users_table.c.username == req.username)
        )
        if result.fetchone():
            raise HTTPException(status_code=409, detail="Username already exists")

        # Hash password and insert user
        password_hash = hash_password(req.password)
        result = await session.execute(
            users_table.insert().values(
                username=req.username,
                display_name=req.display_name or req.username,
                password_hash=password_hash,
            )
        )
        await session.commit()

        # Get the inserted user ID
        user_id = result.inserted_primary_key[0] if result.inserted_primary_key else None

        return JSONResponse({
            "success": True,
            "message": "User registered successfully",
            "user": {
                "id": user_id,
                "username": req.username,
                "display_name": req.display_name or req.username,
            }
        }, status_code=201)



@app.get("/me")
async def me(request: Request):
    """Return current authenticated user from session cookie."""
    session = get_current_user(request)
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "user_id": session["user_id"],
        "username": session["username"],
    }


@app.post("/logout")
async def logout(request: Request):
    """Logout and clear session."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        logout_session(token)

    response = JSONResponse({"success": True})
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


def cli_dataset_stats():
    """CLI command to show dataset statistics."""
    parser = argparse.ArgumentParser(description="Show dataset statistics")
    args = parser.parse_args()

    async def run():
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as session:
            # Total count
            result = await session.execute(select(func.count()).select_from(dataset_table))
            total = result.scalar()

            # Count by split
            result = await session.execute(
                select(dataset_table.c.dataset_split, func.count())
                .group_by(dataset_table.c.dataset_split)
            )
            split_counts = {row[0]: row[1] for row in result.fetchall()}

            # Count by error type
            result = await session.execute(
                select(dataset_table.c.error_type_gold, func.count())
                .group_by(dataset_table.c.error_type_gold)
            )
            type_counts = {row[0]: row[1] for row in result.fetchall()}

            stats = {
                "total": total,
                "by_split": split_counts,
                "by_error_type": type_counts,
            }
            print(json.dumps(stats, indent=2))

    asyncio.run(run())


def cli_update_embeddings():
    """CLI command to update dataset embeddings."""
    parser = argparse.ArgumentParser(description="Update dataset embeddings for pgvector")
    args = parser.parse_args()

    async def run():
        from backend.memory.similarity import update_dataset_embeddings

        result = await update_dataset_embeddings()
        print(json.dumps(result, indent=2))

    asyncio.run(run())


def cli_validate_dataset():
    """CLI command to validate dataset annotations."""
    parser = argparse.ArgumentParser(description="Validate dataset annotations")
    parser.add_argument("--limit", "-l", type=int, default=None, help="Maximum rows to validate")
    args = parser.parse_args()

    async def run():
        from backend.storage import AsyncSessionLocal, dataset_table
        from backend.data.validation import generate_validation_report
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            query = select(dataset_table)
            if args.limit:
                query = query.limit(args.limit)
            result = await session.execute(query)
            rows = [dict(row._mapping) for row in result.fetchall()]

            report = generate_validation_report(rows)
            print(str(report))

            # Exit with error code if issues found
            if report.issues:
                sys.exit(1)

    asyncio.run(run())


def cli_balance_dataset():
    """CLI command to balance dataset by error type."""
    parser = argparse.ArgumentParser(description="Balance dataset by error type")
    parser.add_argument(
        "--strategy", "-s",
        choices=["proportional", "equal", "median"],
        default="proportional",
        help="Balancing strategy"
    )
    parser.add_argument(
        "--total-target", "-t",
        type=int,
        default=None,
        help="Total number of samples after balancing"
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Show what would be done without modifying database"
    )
    args = parser.parse_args()

    async def run():
        from backend.storage import AsyncSessionLocal, dataset_table
        from backend.data.balancer import balance_dataset, get_balance_stats
        from backend.data.validation import compute_error_type_distribution
        from sqlalchemy import select, delete

        async with AsyncSessionLocal() as session:
            # Fetch all dataset rows
            result = await session.execute(select(dataset_table))
            rows = [dict(row._mapping) for row in result.fetchall()]

            if not rows:
                print("Dataset is empty. Nothing to balance.")
                return

            # Show current stats
            current_stats = get_balance_stats(rows)
            print("Current balance:")
            print(json.dumps(current_stats, indent=2))
            print()

            # Balance
            balanced = balance_dataset(
                rows,
                strategy=args.strategy,
                total_target=args.total_target,
            )

            new_stats = get_balance_stats(balanced)
            print("New balance:")
            print(json.dumps(new_stats, indent=2))
            print()

            if args.dry_run:
                print("Dry run mode - no changes made to database.")
                return

            # Replace dataset with balanced version
            # Note: We keep original IDs for non-synthetic rows
            try:
                await session.execute(delete(dataset_table))
                await session.commit()

                # Insert balanced rows
                batch = []
                batch_size = 100
                inserted = 0

                for row in balanced:
                    record = {
                        "input_phrase": row["input_phrase"],
                        "corrected_gold": row["corrected_gold"],
                        "error_type_gold": row["error_type_gold"],
                        "dataset_split": row.get("dataset_split", "train"),
                        "error_spans_gold": row.get("error_spans_gold"),
                        "embedding": row.get("embedding"),
                        "is_verified": row.get("is_verified", False),
                    }
                    batch.append(record)

                    if len(batch) >= batch_size:
                        await session.execute(dataset_table.insert(), batch)
                        await session.commit()
                        inserted += len(batch)
                        batch = []

                if batch:
                    await session.execute(dataset_table.insert(), batch)
                    await session.commit()
                    inserted += len(batch)

                print(f"Successfully balanced dataset: {len(rows)} -> {inserted} rows")

            except Exception as e:
                await session.rollback()
                logger.error(f"Failed to balance dataset: {e}")
                sys.exit(1)

    asyncio.run(run())


def cli_reset_benchmark():
    """CLI command to reset/clear benchmark rows."""
    parser = argparse.ArgumentParser(description="Reset benchmark results")
    parser.add_argument("--model", "-m", default=None, help="Reset only this model (e.g., llm_brut)")
    args = parser.parse_args()

    async def run():
        from backend.storage import AsyncSessionLocal, benchmark_rows_table
        from sqlalchemy import delete

        async with AsyncSessionLocal() as session:
            if args.model:
                await session.execute(
                    delete(benchmark_rows_table).where(
                        benchmark_rows_table.c.model_name == args.model
                    )
                )
                print(f"Reset benchmark_rows for: {args.model}")
            else:
                await session.execute(delete(benchmark_rows_table))
                print("Reset ALL benchmark_rows")

            await session.commit()
            print("Done.")

    asyncio.run(run())


def cli_clean_dataset():
    """CLI command to normalize dataset (fix whitespace, punctuation)."""
    parser = argparse.ArgumentParser(description="Normalize dataset")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Show what would be changed")
    args = parser.parse_args()

    async def run():
        import re
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select, update

        def norm(text: str) -> str:
            text = text.strip()
            # Remove spaces before punctuation
            text = re.sub(r'\s+([.,!?;:])', r'\1', text)
            # Detokenize M2 apostrophe contractions: "you 'll" → "you'll", "It 's" → "It's"
            text = re.sub(r"(\w)\s+'(s|ll|ve|re|d|m|t)\b", r"\1'\2", text)
            # Detokenize "n 't" → "n't" (ca n't, do n't, wo n't, etc.)
            text = re.sub(r"\bn\s+'t\b", r"n't", text)
            text = text.replace("`", "'").replace("''", "'").replace("’", "'")
            text = re.sub(r'\s+', ' ', text)
            text = text.replace(' -- ', ' - ')
            return text

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(dataset_table))
            rows = result.fetchall()

            stats = {"total": len(rows), "normalized": 0, "unchanged": 0}

            for row in rows:
                original = row.input_phrase
                output = row.corrected_gold
                row_id = row.id

                normalized_in = norm(original)
                normalized_out = norm(output)

                # Skip if unchanged after norm
                if normalized_in.lower() == normalized_out.lower():
                    stats["unchanged"] += 1
                    continue

                # Normalize text if needed
                if original != normalized_in or output != normalized_out:
                    stats["normalized"] += 1
                    if not args.dry_run:
                        await session.execute(
                            update(dataset_table)
                            .where(dataset_table.c.id == row_id)
                            .values(
                                input_phrase=normalized_in,
                                corrected_gold=normalized_out,
                            )
                        )

            await session.commit()
            print(json.dumps({
                "total": stats["total"],
                "normalized": stats["normalized"],
                "unchanged": stats["unchanged"],
                "dry_run": args.dry_run,
            }, indent=2))

    asyncio.run(run())


def cli_load_jfleg():
    """CLI command to load JFLEG dataset. Downloads if not present."""
    parser = argparse.ArgumentParser(description="Load JFLEG dataset")
    parser.add_argument("--path", "-p", default="/tmp/jfleg-master", help="Path to JFLEG directory")
    parser.add_argument("--split", "-s", default="test", choices=["test", "dev"], help="Split to load")
    parser.add_argument("--download", "-d", action="store_true", help="Force re-download")
    args = parser.parse_args()

    async def run():
        import os
        from pathlib import Path
        from backend.data.jfleg_loader import load_jfleg_from_path

        jfleg_path = Path(args.path)

        # Download if not exists or forced
        if args.download or not jfleg_path.exists():
            print("Downloading JFLEG dataset...")
            zip_path = "/tmp/jfleg.zip"
            url = "https://github.com/keisks/jfleg/archive/refs/heads/master.zip"

            # Download using Python
            import urllib.request
            urllib.request.urlretrieve(url, zip_path)

            # Unzip
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall("/tmp")

            print(f"JFLEG downloaded to {jfleg_path}")

        if not jfleg_path.exists():
            print(f"Error: JFLEG not found at {jfleg_path}")
            return

        result = await load_jfleg_from_path(str(jfleg_path), split=args.split)
        print(json.dumps(result, indent=2))

    asyncio.run(run())


def cli_load_wi_locness():
    """CLI command to load W&I+LOCNESS dataset (BEA2019)."""
    parser = argparse.ArgumentParser(description="Load W&I+LOCNESS dataset")
    parser.add_argument("--path", "-p", default="/tmp/wi+locness", help="Path to extracted wi+locness directory")
    parser.add_argument("--split", "-s", default="dev", choices=["dev", "train"], help="Split to load")
    parser.add_argument("--levels", "-l", default="A,B,C,N", help="CEFR levels to load (comma-separated: A,B,C,N)")
    parser.add_argument("--max-examples", "-m", type=int, default=None, help="Max rows to load")
    args = parser.parse_args()

    async def run():
        from backend.data.wi_locness_loader import load_wi_locness

        levels = [lv.strip().upper() for lv in args.levels.split(",")]
        result = await load_wi_locness(
            directory=args.path,
            split=args.split,
            levels=levels,
            max_examples=args.max_examples,
        )
        print(json.dumps(result, indent=2))

    asyncio.run(run())


def cli_update_spans():
    """Recompute error_spans_gold from diff(input_phrase, corrected_gold)."""
    parser = argparse.ArgumentParser(description="Recompute gold spans from diff")
    parser.add_argument("--batch-size", "-b", type=int, default=200)
    args = parser.parse_args()

    async def run():
        import json as _json
        from backend.storage import AsyncSessionLocal, dataset_table
        from backend.text_utils import compute_diff
        from sqlalchemy import select, update

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(dataset_table))
            rows = result.fetchall()

        updated = 0
        batch = []
        async with AsyncSessionLocal() as session:
            for row in rows:
                spans = compute_diff(row.input_phrase, row.corrected_gold)
                new_spans = _json.dumps(spans)
                batch.append({"id": row.id, "spans": new_spans})

                if len(batch) >= args.batch_size:
                    for item in batch:
                        await session.execute(
                            update(dataset_table)
                            .where(dataset_table.c.id == item["id"])
                            .values(error_spans_gold=item["spans"])
                        )
                    await session.commit()
                    updated += len(batch)
                    batch = []

            for item in batch:
                await session.execute(
                    update(dataset_table)
                    .where(dataset_table.c.id == item["id"])
                    .values(error_spans_gold=item["spans"])
                )
            await session.commit()
            updated += len(batch)

        print(json.dumps({"updated": updated, "total": len(rows)}))

    asyncio.run(run())


def cli_run_benchmark():
    """CLI command to run benchmark with verbose logging."""
    parser = argparse.ArgumentParser(description="Run benchmark comparison")
    parser.add_argument("--max-examples", "-m", type=int, default=None, help="Maximum examples to test")
    parser.add_argument(
        "--config", "-c",
        default=None,
        choices=["llm_brut", "pipeline_structuré", "pipeline+mémoire"],
        help="Which config to run (default: all)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed logs for each example"
    )
    parser.add_argument(
        "--level", "-l",
        default="A2",
        choices=["A1", "A2", "B1", "B2"],
        help="CEFR level for feedback"
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        default=True,
        help="Save results to database (default: True)"
    )
    parser.add_argument(
        "--split",
        default="test",
        choices=["test", "dev"],
        help="Dataset split to benchmark against (default: test)"
    )
    args = parser.parse_args()

    async def run():
        import logging
        import sys as sys_mod

        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.WARNING,
            format="%(levelname)s: %(message)s",
            stream=sys_mod.stdout,
        )

        from backend.benchmark.runner import BenchmarkRunner
        from backend.storage import AsyncSessionLocal, dataset_table
        from sqlalchemy import select

        async with AsyncSessionLocal() as session:
            split = getattr(args, "split", "test")
            query = select(dataset_table).where(dataset_table.c.dataset_split == split)
            result = await session.execute(query)
            all_rows = result.fetchall()

            if not all_rows:
                print(f"No {split} dataset found. Seed dataset first.")
                sys_mod.exit(1)

            runner = BenchmarkRunner(max_examples=args.max_examples)

            if args.verbose:
                print("\n" + "=" * 60)
                print(f"Running benchmark (level={args.level})")
                print("=" * 60 + "\n")

            output = await runner.run_benchmark(
                session,
                all_rows,
                configs=[args.config] if args.config else None,
                level=args.level,
                verbose=args.verbose,
                save=args.save,
                split=split,
            )

            results = output.get("results", {})
            meta = output.get("meta", {})

            if not results:
                total = meta.get("total_input_rows", 0)
                skipped_tested = meta.get("skipped_already_tested", 0)
                skipped_llm = meta.get("skipped_llm_errors", 0)
                print(
                    f"No new rows to test. "
                    f"({skipped_tested} already tested, {skipped_llm} LLM errors skipped out of {total})"
                )
                sys_mod.exit(0)

            report = runner.generate_report(results)

            print("\n" + "=" * 60)
            print("BENCHMARK RESULTS")
            print("=" * 60)

            for config_name, metrics in report["configurations"].items():
                errant_f05 = metrics.get("errant_f05", 0.0)
                errant_p = metrics.get("errant_precision", 0.0)
                errant_r = metrics.get("errant_recall", 0.0)
                print(f"\n{config_name}:")
                print(f"  ERRANT F0.5:          {errant_f05:.4f}  (edit-level, BEA-2019 standard)")
                print(f"  ERRANT Precision:     {errant_p:.4f}")
                print(f"  ERRANT Recall:        {errant_r:.4f}")
                print(f"  TSF0.5:               {metrics['tsf05']:.4f}  (token-sequence, non-standard)")
                print(f"  Exact match:          {metrics['exact_match_accuracy']:.4f}")
                print(f"  Error type accuracy:  {metrics['error_type_accuracy']:.4f}")
                print(f"  Other ratio:          {metrics['other_ratio']:.4f}")
                print(f"  Avg span F0.5:        {metrics['avg_span_f05']:.4f}")
                print(f"  Feedback gold match:  {metrics['feedback_type_gold_rate']:.4f}")
                print(f"  Latency:              {metrics['latency_avg_ms']:.2f}ms")
                cfg_errors = meta.get("errors_by_config", {}).get(config_name, [])
                if cfg_errors:
                    print(f"  Errors:               {len(cfg_errors)}")

            all_errors = []
            for cfg_errors in meta.get("errors_by_config", {}).values():
                all_errors.extend(cfg_errors)
            if all_errors:
                print(f"\nTotal errors: {len(all_errors)}")
                for e in all_errors[:5]:
                    print(f"  {e}")

            if report["comparative"]:
                print("\n" + "-" * 60)
                print("vs LLM Brut baseline (pipeline annotation delta):")
                for name, delta in report["comparative"].items():
                    print(f"\n  {name}:")
                    print(f"    ERRANT F0.5 Δ:          {delta['vs_baseline_tsf05_delta']:+.4f}")
                    print(f"    Error type accuracy Δ:  {delta['vs_baseline_error_type_accuracy_delta']:+.4f}")
                    print(f"    Other ratio Δ:          {delta['vs_baseline_other_ratio_delta']:+.4f}")
                    print(f"    Feedback gold match Δ:  {delta['vs_baseline_feedback_type_gold_delta']:+.4f}")

            print("\n" + "=" * 60)
            print(f"Best config (TSF0.5): {report['summary']['best_config_by_tsf05']} ({report['summary']['best_tsf05_score']:.4f})")
            print(f"Best config (type accuracy): {report['summary']['best_config_by_error_type_accuracy']} ({report['summary']['best_error_type_accuracy_score']:.4f})")
            print("=" * 60)
            print(f"\nNote: {report['summary']['protocol_note']}")

    asyncio.run(run())


def cli_benchmark_stats():
    """CLI command to show benchmark stats (H1 analysis from benchmark_rows)."""
    parser = argparse.ArgumentParser(description="Show benchmark H1 analysis")
    parser.add_argument("--by-type", action="store_true", help="Breakdown par error_type")
    parser.add_argument("--typological", action="store_true", help="Tableau 4.2 (alignement par type gold) + 4.3 (distribution types prédits)")
    parser.add_argument("--model", default=None, help="Config pour --typological (défaut: pipeline_structuré)")
    parser.add_argument("--runs", action="store_true", help="Historique des runs (table benchmarks)")
    parser.add_argument("--export", metavar="FILE.csv", help="Exporter toutes les lignes en CSV")
    args = parser.parse_args()

    async def run():
        import sys as _sys
        # Reuse analyze_benchmark logic
        _sys.argv = ["analyze_benchmark"]  # reset so argparse in module doesn't conflict
        from analyze_benchmark import (
            fetch_aggregated, fetch_by_error_type, fetch_runs,
            fetch_all_rows, fetch_type_alignment, fetch_predicted_distribution,
            fetch_errant_mean, fetch_h2_latest,
            print_summary, print_by_type, print_runs, export_csv,
            print_type_alignment, print_predicted_distribution,
            print_errant_mean, print_markdown_tables,
        )
        from backend.storage import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            if args.runs:
                rows = await fetch_runs(session)
                print_runs(rows)
                return

            agg = await fetch_aggregated(session)
            if not agg:
                print("Aucune donnée dans benchmark_rows. Lance: python main.py benchmark")
                return

            print_summary(agg)

            errant_rows = await fetch_errant_mean(session)
            print_errant_mean(errant_rows)

            # Always print markdown tables for the mémoire
            type_rows = await fetch_type_alignment(session, "pipeline_structuré")
            dist_rows = await fetch_predicted_distribution(session, "pipeline_structuré")
            h2_row = await fetch_h2_latest(session)
            print_markdown_tables(agg, errant_rows, type_rows, dist_rows, h2_row)

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

    asyncio.run(run())


# Entry point for CLI
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] in (
    "load-c4", "dataset-stats", "update-embeddings", "validate-dataset", "balance-dataset", "load-jfleg", "load-wi-locness", "clean-dataset", "update-spans", "benchmark", "benchmark-stats", "help", "--help", "-h"
):
    command = sys.argv.pop(1)
    if command == "load-c4":
        cli_load_c4()
    elif command == "dataset-stats":
        cli_dataset_stats()
    elif command == "update-embeddings":
        cli_update_embeddings()
    elif command == "validate-dataset":
        cli_validate_dataset()
    elif command == "balance-dataset":
        cli_balance_dataset()
    elif command == "load-jfleg":
        cli_load_jfleg()
    elif command == "load-wi-locness":
        cli_load_wi_locness()
    elif command == "clean-dataset":
        cli_clean_dataset()
    elif command == "update-spans":
        cli_update_spans()
    elif command == "benchmark":
        cli_run_benchmark()
    elif command == "benchmark-stats":
        cli_benchmark_stats()
    elif command in ("help", "--help", "-h"):
        print("""CLI Commands:
  load-c4         - Load C4 dataset
  dataset-stats   - Show dataset statistics
  clean-dataset   - Normalize dataset (fix whitespace, punctuation)
  benchmark       - Run benchmark comparison
  benchmark-stats - Show benchmark history

""")
