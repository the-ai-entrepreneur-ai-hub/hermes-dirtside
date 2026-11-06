"""Use the mounted owner's HTTP boundary without changing conformance assertions."""
from contextlib import contextmanager
import time
import httpx
from nacl.signing import SigningKey
from network_support import listening, mounted
from dirtside.client import Client
from dirtside.protocol import sign
from dirtside.relay import Relay
from test_routes import headers, hello

@contextmanager
def client_relay(owner, url=None):
    if url is None:
        with mounted(owner.registry.path.parent, relay=owner) as (app, *_), listening(app) as origin:
            with client_relay(owner, origin) as worker:
                yield worker
        return
    worker = Relay(owner.registry)
    worker._client = client = Client(worker)
    # The domain fake delivers directly; earn discovery with a verified device message.
    name, key = "client-fixture", SigningKey.generate()
    code = owner.registry.mint(name, int(time.time()))
    response = httpx.post(url + "/api/plugins/dirtside/device/pair", headers=headers(code),
                          json=sign(key, "hello", name, hello(key, owner.registry.path.parent, name)), trust_env=False)
    assert response.status_code == 200, response.text
    device = owner.registry.revoke(name, int(time.time()))
    owner.revoke(device.id)
    response = httpx.get(url + "/api/plugins/dirtside/local/devices", headers=client.headers, trust_env=False)
    assert response.status_code == 200, response.text
    try:
        yield worker
    finally:
        client.http.close()
