# Vercel deployment

The repository packages `vercel_app:app` as a container-backed ASGI service.
`Dockerfile.vercel` installs the locked Python environment at build time and
launches the Streamlit ASGI wrapper with Uvicorn, so dependencies are not
installed during a cold request.

## Required Vercel settings

Set the Vercel project Framework Preset to **Services** and keep the Build
Command on its automatic default. `vercel.json` exposes the internal `web`
container service through a catch-all rewrite. Add the following Environment
Variables for Production and Preview:

- `DATABASE_URL`: a persistent PostgreSQL URL such as
  `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME`
- `KRX_API_KEY`
- `DART_API_KEY`
- `KIS_APP_KEY`
- `KIS_APP_SECRET`
- `KIS_ACCOUNT_NO` when account-specific KIS calls are enabled
- `NCP_APIGW_API_KEY_ID`
- `NCP_APIGW_API_KEY`
- `ECOS_API_KEY` or `BOK_API_KEY`
- `CRON_SECRET`: a long random value used only for protected bootstrap requests

Do not use the default SQLite URL in production. The container is stateless and
does not provide durable application-local storage. Apply migrations to the
PostgreSQL database before opening the deployment:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The `kis_access_tokens` table stores the 24-hour KIS access token so separate
Vercel function instances can reuse it. The token is encrypted with an
authenticated key derived from the configured `KIS_APP_KEY` and
`KIS_APP_SECRET`; only a SHA-256 credential fingerprint is stored alongside
it. PostgreSQL advisory locking serializes token refreshes for the same
credentials, preventing cold starts from issuing duplicate tokens. Rotating
either KIS credential automatically moves the application to a new cache row.

After pushing the changes to the branch connected to Vercel, redeploy and check:

```text
https://YOUR_PROJECT.vercel.app/api/health
```

The endpoint must return `{"status":"ok", ...}`. The Streamlit application is
served at the deployment root.

## Scheduled provider freshness

`vercel.json` registers four bounded daily Cron Jobs. Vercel schedules are UTC;
the corresponding Korea times and work are:

| Path | UTC | KST | Work |
| --- | --- | --- | --- |
| `/api/cron/krx-daily` | 22:30 | 07:30 next day | KRX stock master, daily prices, and KOSPI index |
| `/api/cron/kind-daily-0` … `-4` | 09:40 … 13:40 | 18:40 … 22:40 | KIND market status, 10 watchlist stocks per shard |
| `/api/cron/naver-daily-0` … `-4` | 14:50 … 18:50 | 23:50 … 03:50 next day | OpenDART and Naver news, 10 watchlist stocks per shard |
| `/api/cron/ecos-daily` | 23:00 | 08:00 next day | All configured ECOS macro series for the last 30 days |

Vercel supplies `Authorization: Bearer $CRON_SECRET` to configured Cron Jobs.
The routes reject missing or incorrect credentials. Each scheduled step uses a
PostgreSQL advisory lock (and a process lock for local SQLite) so duplicate or
overlapping deliveries do not run the same provider refresh concurrently. The
underlying repositories use idempotent upserts, so re-running a date is safe.

These jobs run once daily so the configuration is valid on Vercel Hobby as well
as Pro. Vercel does not retry a failed Cron invocation; inspect **Settings > Cron
Jobs > View Logs** and the application's stored provider-attempt status after a
failure. A scheduled probe keeps the recorded connection status fresh, but it
cannot guarantee that an upstream provider itself is continuously available.

The watchlist falls back to Samsung Electronics (`005930`) when it is empty.
Add the production monitoring symbols to the event watchlist so KIND and Naver
refresh the intended stocks. The repository limit of 50 watchlist stocks is
split into five bounded shards so one provider request cannot monopolize a
container invocation or exceed the provider rate limit. KIND access remains
limited to the validated official public status pages; this job does not
introduce an undocumented API or bulk crawler.

## Production data bootstrap

The deployment exposes a protected, bounded bootstrap route so each data phase
can finish within the function duration. Send the secret as a bearer token and
run the normalized steps in order:

```text
POST /api/bootstrap?step=universe
POST /api/bootstrap?step=prices
POST /api/bootstrap?step=index
POST /api/bootstrap?step=phase3-inputs
POST /api/bootstrap?step=phase3-market
POST /api/bootstrap?step=screening
POST /api/bootstrap?step=recommendations
```

For Vercel's request-duration limit, replace the monolithic `phase3-inputs`
step with the bounded history windows below. Run recent offsets from `0` through
`115` in increments of `5`, then older offsets from `120` through `360` in
increments of `30`. Finish with `phase3-market`:

```text
POST /api/bootstrap?step=phase3-window-0
POST /api/bootstrap?step=phase3-window-5
...
POST /api/bootstrap?step=phase3-window-360
```

Each request also upgrades the database schema before running its selected
step. Provider verification steps (`krx`, `opendart`, `kis`, `kind`, `naver`,
and `ecos`) remain available through the same `step` query parameter.

## Runtime limitation

The project currently uses Vercel's 300-second function duration. An active
Streamlit WebSocket can reconnect when Vercel recycles or scales down the
container, but in-memory session state can be lost. Durable application data
must remain in PostgreSQL. The committed Streamlit configuration disables
anonymous usage-metrics writes, which are incompatible with ephemeral hosting.
