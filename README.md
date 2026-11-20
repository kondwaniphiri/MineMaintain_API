# Mine Equipment Maintenance API

A Python API for corrective maintenance at a fictional mine. It tracks a fault
from reporting and assignment through repair, independent verification, and
maintenance history.

- [Verification and benchmark results](docs/verification.md)

## Local development with native PostgreSQL

Copy `.env.example` to an ignored `.env`. In your local PostgreSQL instance,
create a login and a database it owns. For example, run these in `psql` as a
database administrator:

```sql
CREATE ROLE minemaintain LOGIN;
\password minemaintain
CREATE DATABASE minemaintain OWNER minemaintain;
CREATE DATABASE minemaintain_test OWNER minemaintain;
```

Set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` in `.env`
to match your installation. Defaults are `127.0.0.1:5432` and database and
user `minemaintain`. The split settings accept passwords with URL-special
characters directly. An optional `DATABASE_URL` overrides them for both the
API and Alembic. Set a separate, random JWT signing secret in `JWT_SECRET`:

```sh
uv run --no-project --python 3.13 python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Install the locked dependencies, migrate, create an administrator, and start the
API. The administrator setup prompts for a password and confirmation.

```sh
uv sync --locked
uv run --locked alembic upgrade head
uv run --locked python -m scripts.create_admin --email admin@example.com --name "Local Administrator"
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-proxy-headers --no-access-log
```

## Local development with Docker Compose

For the Compose path, set `POSTGRES_PASSWORD` and `JWT_SECRET` in `.env`.
Compose connects the API container to PostgreSQL 17 on its private network
and applies migrations before the API starts. The API is published only on
loopback.

```sh
docker compose up --build -d
docker compose exec api python -m scripts.create_admin --email admin@example.com --name "Local Administrator"
```

Open [Swagger UI](http://127.0.0.1:8000/docs). Send a JSON object with
`email` and `password` to `POST /api/v1/auth/token` and paste the
`access_token` into **Authorize**. Roles and account status are read from
PostgreSQL on each authenticated request. Timestamps are returned in UTC.
Convert them to the `Africa/Lusaka` timezone for local display.

## Seed local test data

Use a dedicated local database with an empty equipment register and applied
migrations. The seed adds fictional Mopani Copper Mines locations, equipment,
fault reports, work orders, and three test accounts. It prompts for a shared
test password. Use a URL-safe password if running the Bruno collection.

```sh
uv run --locked python -m scripts.seed_mopani
```

For Compose, run `docker compose exec api python -m scripts.seed_mopani`.
The test accounts are `operator@mopani-demo.example.com`,
`technician@mopani-demo.example.com`, and `supervisor@mopani-demo.example.com`.
The fixtures are fictional, and the addresses use the reserved example.com
domain.

For the optional [Bruno regression collection](requests/), select **Local**
and enter the seed password in the `demo_password` secret variable.

Every command that updates a resource uses its current version. Fault creation,
conversion, and work-order POSTs also require an `Idempotency-Key`. Use a new
key for a new operation and reuse the original key and body for retries within
24 hours. Corrections append replacement records, preserve originals in history,
and count only the current values in work-order totals.

## Test and prepare a release

Set `TEST_DATABASE_URL` to a dedicated, empty database distinct from the
development data. For native PostgreSQL use your local host and test database.
For Compose, run `docker compose --profile test up -d --wait test-db` and use
`postgresql+psycopg://minemaintain_test:<password>@127.0.0.1:55432/minemaintain_test`.
Percent-encode credentials when writing a full URL.

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

Before deployment, run the suite against the target PostgreSQL 17 service,
build and smoke-test the image, and exercise the collection on a staging
database. Supply `ENVIRONMENT=production`, the signing secret, and the
database credentials through the host's secret store. Run migrations once
before starting the API. Use HTTPS at the ingress, keep direct access to the
API private, and verify backup and restore on the target host.

`GET /health/live` checks the process and `GET /health/ready` checks database
connectivity. Login throttling allows five attempts per normalized email and
30 per source IP in a 60-second window. At most four password verifications
run at a time. Throttling state resets on restart. When using a reverse proxy,
have it set the forwarding headers and enable Uvicorn proxy headers only for
the proxy addresses via `--forwarded-allow-ips`. Keep one API worker until a
shared limiter is available.

This portfolio application records maintenance and external references.
Operational clearance and permit approval occur outside the API.
