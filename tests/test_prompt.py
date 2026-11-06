"""Prompt facts stay bounded and respect the same conversation identity."""
import json
import time
from dataclasses import replace

import pytest
from gateway.session_context import clear_session_vars, set_session_vars

from dirtside.prompt import TargetPrompt
from dirtside.registry import Registry
from dirtside.relay import Relay
from test_registry import paired


@pytest.fixture
def prompt(tmp_path):
    registry = Registry(tmp_path / "data.db")
    tokens = set_session_vars(session_key="", session_id="")
    try:
        yield TargetPrompt(registry, Relay(registry))
    finally:
        clear_session_vars(tokens)


def test_server_is_empty_even_over_device_default(prompt, tmp_path):
    device, _, _ = paired(prompt.registry, tmp_path)
    assert prompt.current_target_section({"session_id": "chat"}) == ""
    prompt.default_target = device.name
    prompt.registry.set_target("chat", "server")
    assert prompt.current_target_section({"session_id": "chat"}) == ""
    assert device.name in prompt.current_target_section({"session_id": "other"})
    assert prompt.current_target_section({"session_id": "other", "platform": "cron"}) == ""


def test_offline_device_facts_and_missing_selection(prompt, tmp_path):
    device, _, _ = paired(prompt.registry, tmp_path)
    prompt.registry.set_target("chat", device.id)
    text = prompt.current_target_section({"session_id": "chat"})
    assert all(value in text for value in (device.name, device.os, device.home, "Commands run there"))
    assert len(text) <= 600 and not prompt.relay.is_online(device.id)
    prompt.registry.revoke(device.name, int(time.time()))
    assert prompt.current_target_section({"session_id": "chat"}) == ""


def test_bound_conversation_wins_over_prompt_metadata(prompt, tmp_path):
    device, _, _ = paired(prompt.registry, tmp_path)
    prompt.registry.set_target("bound", device.id)
    prompt.registry.set_target("metadata", "server")
    tokens = set_session_vars(session_key="bound", session_id="another")
    try:
        assert device.name in prompt.current_target_section({"session_id": "metadata"})
    finally:
        clear_session_vars(tokens)
    assert prompt.current_target_section({"session_id": "metadata"}) == ""


def test_server_default_never_uses_facts_from_a_device_named_server(prompt, tmp_path):
    device, _, _ = paired(prompt.registry, tmp_path)
    with prompt.registry._tx() as conn:
        conn.execute("UPDATE devices SET name='server' WHERE id=?", (device.id,))
    assert prompt.registry.active_device("server") is not None
    assert prompt.current_target_section({"session_id": "chat"}) == ""


@pytest.mark.parametrize("os,home", [
    ("system", "/" + "very-long-home/" * 300),
    ('x"\n' * 100, "\x01" * 4000),
    ("地" * 1000, "/" + "界" * 4000),
])
def test_untrusted_facts_remain_quoted_and_bounded(prompt, tmp_path, os, home):
    device, _, _ = paired(prompt.registry, tmp_path)
    # Plugin-owned read boundary substitute, not a core patch.
    changed = replace(device, os=os, home=home)
    prompt.registry.active_device = lambda name: changed
    prompt.default_target = device.name
    text = prompt.current_target_section({})
    assert len(text) <= 600 and "\n" not in text and "\x01" not in text
    fields = text.split("device=", 1)[1].removesuffix(". Commands run there, not on the server.")
    name, os_value, home_value = fields.split(", OS=")[0], *fields.split(", OS=")[1].split(", home=")
    assert json.loads(name) == device.name
    assert isinstance(json.loads(os_value), str) and isinstance(json.loads(home_value), str)
