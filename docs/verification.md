# Local verification

The benchmark used Windows 11, an Intel Core i7-10750H (12 logical
processors), Python 3.13.17, PostgreSQL 18.6, and one Uvicorn worker. The
server, database, and client ran on the same machine over loopback.

The timed workload issued 500 order-detail reads and 500 authenticated note
writes with 10 client threads against 1,000 seeded orders. Login and fixture
setup were outside the timing window.

| Operation | Observed p95 | Target |
| --- | ---: | ---: |
| GET work order detail | 251.23 ms | Under 500 ms |
| POST work note | 317.17 ms | Under 500 ms |

To repeat, migrate a dedicated empty local database, seed it with
`uv run --locked python -m scripts.seed_mopani --orders 1000`, start the API, and
run `uv run --locked python -m scripts.benchmark`. The script prompts for the
seeded password and writes fictional notes to the benchmark database.

Bruno CLI 4.3.0 ran the full 22-request collection against the live local
API and passed every request and test.

Docker and WSL were unavailable in this environment. The PostgreSQL 17
container build, hosted CI run, and staging deployment are release checks
to perform on the target setup.
