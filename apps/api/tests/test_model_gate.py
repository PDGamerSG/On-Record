"""Concurrency and priority guarantees for model requests."""

import asyncio

import pytest

from wsw_brain.brain.llm import LLMError, ModelGate, llm_priority, model_gate


async def _wait_until(predicate) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


@pytest.mark.asyncio
async def test_gate_limits_in_flight_calls_and_releases_waiters():
    gate = ModelGate(slots=1, max_waiting=2, wait_s=1)
    entered = asyncio.Event()
    release = asyncio.Event()
    active = 0
    maximum = 0

    async def work():
        nonlocal active, maximum
        async with gate.slot():
            active += 1
            maximum = max(maximum, active)
            entered.set()
            await release.wait()
            active -= 1

    first = asyncio.create_task(work())
    await entered.wait()
    second = asyncio.create_task(work())
    await _wait_until(lambda: gate.waiting == 1)
    assert gate.busy == 1

    release.set()
    await asyncio.gather(first, second)

    assert maximum == 1
    assert gate.busy == 0 and gate.waiting == 0


@pytest.mark.asyncio
async def test_priority_work_is_served_before_ordinary_waiters():
    gate = ModelGate(slots=1, max_waiting=3, wait_s=1)
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def holder():
        async with gate.slot():
            order.append("holder")
            entered.set()
            await release.wait()

    async def ordinary():
        async with gate.slot():
            order.append("ordinary")

    async def important():
        with llm_priority():
            async with gate.slot():
                order.append("important")

    first = asyncio.create_task(holder())
    await entered.wait()
    normal = asyncio.create_task(ordinary())
    await _wait_until(lambda: gate.waiting == 1)
    urgent = asyncio.create_task(important())
    await _wait_until(lambda: gate.waiting == 2)
    release.set()
    await asyncio.gather(first, normal, urgent)

    assert order == ["holder", "important", "ordinary"]


@pytest.mark.asyncio
async def test_normal_queue_rejects_when_waiting_limit_is_full():
    gate = ModelGate(slots=1, max_waiting=1, wait_s=1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.slot():
            entered.set()
            await release.wait()

    async def waiting():
        async with gate.slot():
            return

    first = asyncio.create_task(holder())
    await entered.wait()
    queued = asyncio.create_task(waiting())
    await _wait_until(lambda: gate.waiting == 1)
    with pytest.raises(LLMError, match="language model is busy"):
        await waiting()
    release.set()
    await asyncio.gather(first, queued)


@pytest.mark.asyncio
async def test_waiting_call_times_out_with_public_error():
    gate = ModelGate(slots=1, max_waiting=1, wait_s=0.01)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with gate.slot():
            entered.set()
            await release.wait()

    first = asyncio.create_task(holder())
    await entered.wait()
    with pytest.raises(LLMError, match="waited 0 s"):
        async with gate.slot():
            pass
    release.set()
    await first


def test_model_gate_is_shared_by_endpoint_key():
    key = "test-model-gate-endpoint"
    assert model_gate(key) is model_gate(key)
