"""Pairing errors stay useful and private; device pairing is not local IPC."""
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from network_support import mounted

from dirtside import cli
from dirtside.protocol import sign
from test_cli import parser
from test_routes import API, headers, hello


@pytest.mark.parametrize("status,body,expected", [
    (400, {"detail": "invalid message"}, "invalid message"),
    (401, {"detail": "unknown device credential"}, "unknown device credential"),
    (400, "<html>private-code</html>", "Bad Request"),
    (400, {"detail": ["private-code"]}, "Bad Request"),
    (400, {"detail": "\x1b[31mrejected private-code\n" + "x" * 2000}, "rejected [redacted]"),
    (400, {"detail": "rejected pri\x1bvate-code"}, "rejected [redacted]"),
])
def test_pairing_refusal_is_bounded_and_redacted(tmp_path, monkeypatch, capsys, status, body, expected):
    original = httpx.Client
    def respond(request):
        assert request.headers["authorization"] == "Bearer private-code"
        return httpx.Response(status, **({"json": body} if isinstance(body, dict) else {"text": body}))
    monkeypatch.setattr(cli.httpx, "Client",
                        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(respond)))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    args = parser().parse_args(["dirtside", "pair", "https://public.invalid", "--name", "device",
                               "--code=private-code"])
    assert args.func(args) == 1
    output = capsys.readouterr().out
    assert f"HTTP {status}" in output and expected in output
    assert "private-code" not in output and "\x1b" not in output
    assert len(output) < 700 and output.count("\n") == 1
    assert not (tmp_path / "dirtside/device.json").exists()


@pytest.mark.parametrize("gate", [False, True])
def test_device_pairing_accepts_non_loopback_https_peer(tmp_path, gate):
    with mounted(tmp_path, gate=gate) as (app, registry, *_):
        key = SigningKey.generate()
        code = registry.mint("device", int(time.time()))
        with TestClient(app, base_url="https://public.invalid", client=("203.0.113.7", 4321)) as client:
            response = client.post(API + "/device/pair", headers=headers(code),
                                   json=sign(key, "hello", "device", hello(key, tmp_path)))
        assert response.status_code == 200
        assert registry.active_device("device").id == response.json()["device_id"]


def test_host_refusal_prints_gateway_configuration_hint(tmp_path, monkeypatch, capsys):
    original = httpx.Client
    detail = "Invalid Host header. Dashboard requests must use the bound hostname or the configured public hostname."
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(400, json={"detail": detail}))))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    args = parser().parse_args(["dirtside", "pair", "https://public.invalid", "--name", "device", "--code=secret"])
    assert args.func(args) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and f"HTTP 400: {detail}" in lines[0]
    assert lines[1] == ("The gateway does not trust this hostname. On the gateway run: "
                        "hermes config set dashboard.public_url https://public.invalid and restart it.")
    assert not (tmp_path / "dirtside/device.json").exists()
