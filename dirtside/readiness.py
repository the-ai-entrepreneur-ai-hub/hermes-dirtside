"""Bounded readiness waits without select's descriptor-number ceiling."""
import selectors


def wait_ready(fileobj, timeout, *, write=False):
    with selectors.DefaultSelector() as ready:
        ready.register(fileobj, selectors.EVENT_WRITE if write else selectors.EVENT_READ)
        return bool(ready.select(timeout))
