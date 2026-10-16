# Deployment Runbook

This is the Phase 1 deployment runbook for MediScribe AI. The plan is Railway for the backend and PostgreSQL, Vercel for the frontend. Both providers' free tiers are sufficient for the portfolio demo.

The runbook is documentation only — execution belongs to a later milestone. Treat it as the canonical source for environment variables, build commands, and CORS expectations.

## Architecture in deployment

```
Vercel (Vite/Nginx static)            Railway
        |                                |
  Browser ── HTTPS ──> Vercel ──> https://<railway-host>/api/...
                                        |
                                        v
                                    FastAPI container
                                        |
                                        v
                                    Railway PostgreSQL
```

The browser never talks to PostgreSQL directly. CORS only matters between the Vercel origin and the Railway origin.

## Backend on Railway

### One-time project setup

1. Create a new Railway project from the GitHub repo, branch `main` (or whichever branch you intend to deploy).
2. Add the **PostgreSQL** plugin to the project. Railway injects `DATABASE_URL` automatically — do not set it manually.
3. The default Railway buildpack picks up `Dockerfile` at the repo root, which already runs `alembic -c alembic.ini upgrade head` before starting Uvicorn (see `Dockerfile` `CMD`).
4. Set the start port to **8000** (matches `EXPOSE 8000` in the Dockerfile).
5. Health check path: `/health`.

### Required environment variables (Railway)

| Variable | Source | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Auto-injected by the Postgres plugin | Do not override |
| `JWT_SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_hex(32))"` | Must be stable; rotating it invalidates every existing token |
| `GROQ_API_KEY` | Groq console | Required for SOAP generation. Without it the rule-based fallback runs and the `source` field on saved notes will say `rule-based-fallback` |
| `CORS_ORIGINS` | Vercel deployment URL (set after the frontend is deployed) | Comma-separated list. Must include the exact Vercel origin (scheme + host, no trailing slash) |

### Optional environment variables

| Variable | Default | Reason to override |
| --- | --- | --- |
| `WHISPER_BACKEND` | `faster-whisper` | The only supported backend at deploy time. `openai-whisper` is not installed in the image |
| `WHISPER_MODEL` | `small.en` | 464 MB on disk and roughly 1x realtime on CPU. Set `base.en` (141 MB, ~9x faster than realtime, medical-term error 0.169 against 0.109) where the memory budget or latency will not take it — Railway's smaller tiers are the case to watch |
| `WHISPER_COMPUTE_TYPE` | `int8` | int8 is the fastest CPU option; do not change without benchmarking |
| `WHISPER_BEAM_SIZE` | `5` (faster-whisper default) | Lower values trade quality for latency |

### First deploy

1. Push the branch you want to deploy.
2. Railway builds the image. The faster-whisper model is baked into the image (see `Dockerfile` lines around `RUN python -c "from faster_whisper..."`), so the first transcription request after each cold start is fast — no runtime download.
3. Once the build is green, hit `https://<railway-host>/health`. Expect `200`.
4. Inspect the deploy logs for `alembic -c alembic.ini upgrade head` — the schema is created on this first run.

## Frontend on Vercel

### One-time project setup

1. Connect Vercel to the GitHub repo.
2. Set the project root to `frontend/`.
3. Build command: `npm run build` (Vercel detects Vite automatically; the explicit command is fine).
4. Output directory: `dist`.
5. Install command: `npm ci` (deterministic, faster).

### Required environment variables (Vercel)

| Variable | Value | Notes |
| --- | --- | --- |
| `VITE_API_URL` | `https://<railway-host>` (no trailing slash) | The Vite client uses this as the base URL for every `axios` call. If left undefined, the build assumes `http://localhost:8000`, which only works in local dev |

`VITE_API_URL` is read at **build time**, not runtime. After updating it, redeploy the frontend so Vercel rebuilds the bundle.

### First deploy

1. Push the branch.
2. Vercel builds and serves from `frontend/dist`.
3. Visit the Vercel URL and try to log in. If you see a CORS error in DevTools, jump to the next section.

## CORS handshake (post-deploy)

CORS must be configured **after** both Railway and Vercel URLs are known. The flow:

1. Note the Vercel production URL (e.g. `https://mediscribe.vercel.app`). Production previews on Vercel use distinct subdomains — if you want previews to talk to Railway too, add them as well.
2. On Railway, set:
   ```
   CORS_ORIGINS=https://mediscribe.vercel.app,https://mediscribe-staging.vercel.app
   ```
3. Restart the Railway backend so the new env var takes effect.
4. Reload the Vercel frontend and confirm `POST /api/auth/login` succeeds with no preflight error.

The backend's CORS layer is in `backend/main.py` — it uses an explicit allow-list, not `allow_origins=["*"]`, because credentials are required (`allow_credentials=True`).

## Sanity checks after deploy

These match steps in `scripts/smoke-test.sh`. Run them against the deployed backend (`BASE_URL=https://<railway-host> ./scripts/smoke-test.sh`) once both sides are up.

- `GET /health` → 200
- `POST /api/auth/register` → 201 with `access_token`
- `POST /api/auth/login` → 200 with `access_token`
- `GET /api/auth/me` with Bearer token → 200
- `POST /api/transcribe` with the fixture → 200 with `success: true`, populated `soap_note`
- `GET /api/history` → array length 1
- `DELETE /api/history/{id}` → 204
- `DELETE /api/auth/me` → 204
- `GET /api/auth/me` after delete → 401

## Things to avoid

- Do not set `DATABASE_URL` manually on Railway when the Postgres plugin is attached. Railway rotates it; manual values go stale.
- Do not commit `JWT_SECRET_KEY` or `GROQ_API_KEY` to the repo, even on a private branch. Set them through the Railway dashboard.
- Do not set `allow_origins=["*"]` together with `allow_credentials=True` in the FastAPI CORS middleware — browsers reject the combination.
- Do not skip migrations. The Dockerfile's `CMD` runs `alembic upgrade head` before Uvicorn; do not change the CMD to start Uvicorn directly.
- Do not deploy the `openai-whisper` backend. The package is not installed in the image, and `WHISPER_BACKEND=openai-whisper` will error at the first transcription request.
