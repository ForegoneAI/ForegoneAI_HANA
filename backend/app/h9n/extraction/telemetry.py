"""Optional, request-local model usage capture for offline evaluation.

This does not change deal profiles or persistence. ContextVar prevents concurrent
FastAPI requests from contributing tokens to another request's benchmark run.
Only returned provider usage is measurable; a failed request may have unknown
billing, so callers must label costs on failed runs as partial estimates.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

_usage: ContextVar[list[dict[str, Any]] | None] = ContextVar("extraction_usage", default=None)


@contextmanager
def capture_model_usage() -> Iterator[list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    token = _usage.set(calls)
    try:
        yield calls
    finally:
        _usage.reset(token)


def record_model_response(response: Any, requested_model: str) -> None:
    calls = _usage.get()
    if calls is None:
        return
    usage = getattr(response, "usage", None)
    model = getattr(response, "model", None)
    # Anthropic reports uncached input, cache reads, and cache creation
    # separately. The benchmark contract's input_tokens includes all three.
    uncached = getattr(usage, "input_tokens", None)
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    counts = (uncached, cached, created)
    total = sum(counts) if all(type(n) is int and n >= 0 for n in counts) else None
    calls.append({
        "model": model if isinstance(model, str) and model else requested_model,
        "input_tokens": total,
        "cached_input_tokens": cached,
        "cache_creation_input_tokens": created,
        "output_tokens": getattr(usage, "output_tokens", None),
    })
