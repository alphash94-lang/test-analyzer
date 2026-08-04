# Vercel deployment

The repository exposes `vercel_app:app` as an ASGI entrypoint. Vercel loads this
entrypoint instead of treating `app/main.py` as a FastAPI or Flask module.

## Required Vercel settings

Keep the Vercel project Framework Preset and Build Command on their automatic
defaults. Add the following Environment Variables for Production and Preview:

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

Do not use the default SQLite URL in production. A Vercel Function does not
provide durable application-local storage. Apply migrations to the PostgreSQL
database before opening the deployment:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DBNAME"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

After pushing the changes to the branch connected to Vercel, redeploy and check:

```text
https://YOUR_PROJECT.vercel.app/api/health
```

The endpoint must return `{"status":"ok", ...}`. The Streamlit application is
served at the deployment root.

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

`vercel.json` gives the ASGI function a 300-second maximum duration. An active
Streamlit session can reconnect when Vercel recycles the function, but in-memory
session state can be lost. Durable application data must remain in PostgreSQL.
The committed Streamlit configuration disables anonymous usage-metrics writes,
which are incompatible with Vercel's read-only home filesystem.
