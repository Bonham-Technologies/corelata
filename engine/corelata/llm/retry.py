"""Exponential backoff with jitter for transient backend failures."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from corelata.config import RetryConfig
from corelata.llm.types import TransientBackendError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_s: float = 2.0
    max_delay_s: float = 60.0

    @classmethod
    def from_config(cls, cfg: RetryConfig) -> "RetryPolicy":
        return cls(cfg.max_attempts, cfg.base_delay_s, cfg.max_delay_s)

    def delay(self, attempt: int, rng: random.Random) -> float:
        """Delay before retry number `attempt` (1-based): capped exponential, 50–100% jitter."""
        return min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1)) * rng.uniform(0.5, 1.0)


async def call_with_retry[T](
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
) -> T:
    rng = rng or random.Random()
    attempt = 1
    while True:
        try:
            return await fn()
        except TransientBackendError:
            if attempt >= policy.max_attempts:
                raise
            await sleep(policy.delay(attempt, rng))
            attempt += 1
