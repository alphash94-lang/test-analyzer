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

## Runtime limitation

`vercel.json` gives the ASGI function a 300-second maximum duration. An active
Streamlit session can reconnect when Vercel recycles the function, but in-memory
session state can be lost. Durable application data must remain in PostgreSQL.
