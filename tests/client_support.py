"""Use the mounted owner's HTTP boundary without changing conformance assertions."""
from contextlib import contextmanager
import httpx
from network_support import listening, mounted
from dirtside.client import Client
from dirtside.relay import Relay

@contextmanager
def client_relay(owner, url=None):
    if url is None:
        with mounted(owner.registry.path.parent, relay=owner) as (app, *_), listening(app) as origin:
            with client_relay(owner, origin) as worker:
                yield worker
        return
    worker = Relay(owner.registry)
    worker._client = client = Client(worker)
    # The domain fake delivers directly; only a device route may earn discovery.
    response = httpx.post(url + "/api/plugins/dirtside/device/poll", headers=client.headers, trust_env=False)
    assert response.status_code == 401, response.text
    response = httpx.get(url + "/api/plugins/dirtside/local/devices", headers=client.headers, trust_env=False)
    assert response.status_code == 200, response.text
    try:
        yield worker
    finally:
        client.http.close()
