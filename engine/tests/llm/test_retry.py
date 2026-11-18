import random

import pytest

from corelata.config import RetryConfig
from corelata.llm.retry import RetryPolicy, call_with_retry
from corelata.llm.types import PermanentBackendError, TransientBackendError


def test_delay_grows_exponentially_with_jitter_and_cap():
    policy = RetryPolicy(max_attempts=5, base_delay_s=2, max_delay_s=5)
    rng = random.Random(0)
    delays = [policy.delay(a, rng) for a in (1, 2, 3, 4)]
    assert 1.0 <= delays[0] <= 2.0
    assert 2.0 <= delays[1] <= 4.0
    assert 2.5 <= delays[2] <= 5.0
    assert delays[3] <= 5.0


def test_from_config():
    p = RetryPolicy.from_config(RetryConfig(max_attempts=2, base_delay_s=1, max_delay_s=3))
    assert (p.max_attempts, p.base_delay_s, p.max_delay_s) == (2, 1, 3)


async def test_retries_transient_then_succeeds():
    calls, slept = [], []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise TransientBackendError("busy")
        return "ok"

    async def sleep(d):
        slept.append(d)

    result = await call_with_retry(
        fn, RetryPolicy(max_attempts=3), sleep=sleep, rng=random.Random(1)
    )
    assert result == "ok"
    assert len(calls) == 3
    assert len(slept) == 2


async def test_gives_up_after_max_attempts():
    async def fn():
        raise TransientBackendError("down")

    async def sleep(d):
        pass

    with pytest.raises(TransientBackendError):
        await call_with_retry(fn, RetryPolicy(max_attempts=2), sleep=sleep)


async def test_permanent_errors_are_not_retried():
    calls = []

    async def fn():
        calls.append(1)
        raise PermanentBackendError("bad request")

    with pytest.raises(PermanentBackendError):
        await call_with_retry(fn, RetryPolicy(max_attempts=5))
    assert calls == [1]
