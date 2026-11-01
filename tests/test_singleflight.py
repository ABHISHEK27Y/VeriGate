"""Duplicate work coalesces without making failures or cancellation sticky."""

import asyncio

import pytest

from app.singleflight import SingleFlight


@pytest.mark.asyncio
async def test_same_key_runs_once_and_other_key_is_independent() -> None:
    flight = SingleFlight()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def work() -> str:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return "answer"

    leader = asyncio.create_task(flight.run("tenant-a:query", work, 1))
    await entered.wait()
    follower = asyncio.create_task(flight.run("tenant-a:query", work, 1))
    await asyncio.sleep(0)
    assert await flight.run("tenant-b:query", lambda: _answer("other"), 1) == (
        "other",
        False,
    )
    release.set()
    assert await leader == ("answer", False)
    assert await follower == ("answer", True)
    assert calls == 1
    assert not flight._active


async def _answer(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_leader_failure_reaches_follower_and_key_clears() -> None:
    flight = SingleFlight()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def failed() -> str:
        entered.set()
        await release.wait()
        raise ValueError("upstream failed")

    leader = asyncio.create_task(flight.run("key", failed, 1))
    await entered.wait()
    follower = asyncio.create_task(flight.run("key", failed, 1))
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(ValueError, match="upstream failed"):
        await leader
    with pytest.raises(ValueError, match="upstream failed"):
        await follower
    assert await flight.run("key", lambda: _answer("retry"), 1) == ("retry", False)


@pytest.mark.asyncio
async def test_follower_timeout_and_cancellation_leave_leader_owned() -> None:
    flight = SingleFlight()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def work() -> str:
        entered.set()
        await release.wait()
        return "answer"

    leader = asyncio.create_task(flight.run("key", work, 1))
    await entered.wait()
    with pytest.raises(TimeoutError):
        await flight.run("key", work, 0.001)
    cancelled = asyncio.create_task(flight.run("key", work, 1))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()
    assert await leader == ("answer", False)
    assert not flight._active


@pytest.mark.asyncio
async def test_capacity_bounded_and_leader_cancellation_releases_key() -> None:
    flight = SingleFlight(capacity=1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def work() -> str:
        entered.set()
        await release.wait()
        return "answer"

    leader = asyncio.create_task(flight.run("key", work, 1))
    await entered.wait()
    assert await flight.run("different", lambda: _answer("direct"), 1) == (
        "direct",
        False,
    )
    follower = asyncio.create_task(flight.run("key", work, 1))
    await asyncio.sleep(0)
    leader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await leader
    with pytest.raises(RuntimeError, match="leader cancelled"):
        await follower
    assert not flight._active


@pytest.mark.asyncio
async def test_owner_expiry_releases_key() -> None:
    flight = SingleFlight()
    with pytest.raises(TimeoutError):
        await flight.run("key", lambda: asyncio.sleep(1), 0.001)
    assert not flight._active
    assert await flight.run("key", lambda: _answer("retry"), 1) == ("retry", False)
