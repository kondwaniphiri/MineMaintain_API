from collections import OrderedDict
from math import ceil
from threading import Lock
from time import monotonic


class LoginLimits:
    def __init__(self, *, window: int = 60, capacity: int = 10_000):
        self.window = window
        self.capacity = capacity
        self.buckets: OrderedDict[tuple[str, str], tuple[float, int]] = OrderedDict()
        self.lock = Lock()

    def consume(self, email: str, ip: str) -> int:
        limits = {("account", email): 5, ("ip", ip): 30}
        with self.lock:
            now = monotonic()
            while self.buckets:
                expires, _ = next(iter(self.buckets.values()))
                if expires > now:
                    break
                self.buckets.popitem(last=False)

            retry_after = 0
            for key, limit in limits.items():
                expires, count = self.buckets.get(key, (now + self.window, 0))
                if count >= limit:
                    retry_after = max(retry_after, ceil(expires - now))

            new_keys = limits.keys() - self.buckets.keys()
            if len(self.buckets) + len(new_keys) > self.capacity:
                retry_after = max(retry_after, self.window)

            # Count blocked account attempts against the source IP as well.
            for key, limit in limits.items():
                if key not in self.buckets and retry_after:
                    continue
                expires, count = self.buckets.get(key, (now + self.window, 0))
                self.buckets[key] = (expires, min(count + 1, limit))
            return retry_after
