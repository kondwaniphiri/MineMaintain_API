from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from getpass import getpass
from math import ceil
from time import perf_counter
from uuid import uuid4

import httpx

from scripts.seed_mopani import DEMO_DOMAIN


def p95(samples: list[float]) -> float:
    return sorted(samples)[ceil(len(samples) * 0.95) - 1] * 1000


def run(client: httpx.Client, password: str, iterations: int) -> tuple[float, float]:
    token = (
        client.post(
            "auth/token",
            json={"email": f"technician@{DEMO_DOMAIN}", "password": password},
        )
        .raise_for_status()
        .json()["access_token"]
    )
    client.headers["Authorization"] = f"Bearer {token}"
    orders = []
    for page in range(1, 11):
        result = (
            client.get(
                "work-orders",
                params={
                    "status": "IN_PROGRESS",
                    "page": page,
                    "page_size": 100,
                },
            )
            .raise_for_status()
            .json()
        )
        if result["total"] != 1000:
            raise ValueError("Run the benchmark against the dedicated 1,000-order seed")
        orders.extend(result["items"])

    def measure(index: int):
        order = orders[index % 1000]
        path = f"work-orders/{order['id']}"
        start = perf_counter()
        current = client.get(path).raise_for_status().json()
        read = perf_counter() - start
        start = perf_counter()
        client.post(
            f"{path}/notes",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "expected_version": current["version"],
                "kind": "PROGRESS",
                "text": "Benchmark note",
            },
        ).raise_for_status()
        return read, perf_counter() - start

    # Each batch owns distinct work orders, even when running another batch.
    samples = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for batch in range(iterations):
            samples.extend(pool.map(measure, range(batch * 100, (batch + 1) * 100)))
    return p95([read for read, _ in samples]), p95([write for _, write in samples])


def main() -> None:
    parser = ArgumentParser(
        description="Measure loopback HTTP reads and writes at 10 concurrent clients"
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--iterations", type=int, default=5, choices=range(1, 11))
    args = parser.parse_args()
    password = getpass("Seeded demo password: ")
    with httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}/api/v1/", timeout=10
    ) as client:
        read, write = run(client, password, args.iterations)
    print(
        f"{args.iterations * 100} reads and writes each. "
        f"p95 read {read:.2f} ms, write {write:.2f} ms."
    )


if __name__ == "__main__":
    main()
