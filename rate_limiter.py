"""
Token-bucket rate limiter – one instance per platform.
PRD §5 NFR: configurable tokens/second, 750–1250 ms jitter per request.
"""

import time
import threading
from config import get_inter_request_delay


class TokenBucketRateLimiter:
    """Simple token-bucket that blocks the caller until a token is available."""

    def __init__(self, tokens_per_second: float, max_burst: int = 2):
        self.tokens_per_second = tokens_per_second
        self.max_burst = max_burst
        self._tokens = float(max_burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.max_burst,
            self._tokens + elapsed * self.tokens_per_second,
        )
        self._last_refill = now

    def acquire(self) -> None:
        """Block until a token is available, then add inter-request jitter."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    break
            # Sleep a short interval before retrying
            time.sleep(0.05)

        # PRD §5 NFR: 750–1250 ms random delay per external request
        jitter = get_inter_request_delay()
        time.sleep(jitter)


def build_rate_limiters(rate_limits: dict[str, float]) -> dict[str, TokenBucketRateLimiter]:
    """Create one ``TokenBucketRateLimiter`` per platform from the config dict."""
    return {
        platform: TokenBucketRateLimiter(tokens_per_second=rate, max_burst=2)
        for platform, rate in rate_limits.items()
    }
