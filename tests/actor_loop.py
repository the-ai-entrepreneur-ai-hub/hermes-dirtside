"""One real release-core turn, with a scripted loopback model and real tool dispatch."""
import json
import socket
from contextlib import closing, contextmanager
from unittest.mock import patch


@contextmanager
def loopback_only(external):
    connect, lookup = socket.socket.connect, socket.getaddrinfo
    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            external.append("connect")
            raise OSError("Test permits loopback only")
        return connect(sock, address)
    def guarded_lookup(host, *pos, **kw):
        if host not in ("127.0.0.1", "::1", "localhost", None, ""):
            external.append("lookup")
            raise socket.gaierror("Test permits loopback only")
        return lookup(host, *pos, **kw)
    with patch("socket.socket.connect", guarded_connect), patch("socket.getaddrinfo", guarded_lookup):
        yield


def run(runtime, args):
    from actor_context import turn, values
    from gateway.platforms.event import MessageEvent
    from hermes_cli.config import atomic_config_write, load_config
    from hermes_cli.lifecycle import invoke_hook
    from hermes_cli.observability.shared_metrics_consent import OFFER_VERSION
    from hermes_constants import get_hermes_home
    from hermes_state import SessionDB
    from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall
    state, external = {}, []
    def respond(record):
        messages = record.get("body", record).get("messages", [])
        count = sum(m.get("role") == "tool" for m in messages)
        if count == 0:
            return ToolCall("terminal", {"command": "pwd; cat proof"})
        if count == 1 and "before" not in state:
            state["before"] = [r.id for r in runtime.auth.registry.recent(200)]
            state["redirect"] = state["agent"].redirect("[other] also do this")
            event = state["event"]
            event.absorb_turn_input(MessageEvent("joined input", source=event.source, user_id="other"))
            return Text("cancelled by redirect")
        if count == 1:
            return ToolCall("terminal", {"command": "pwd; cat proof; printf forbidden > after-merge"})
        return Text("done")
    with FakeLLMServer(respond) as server:
        home, config = get_hermes_home(), load_config()
        config["model"] = {"provider": "custom", "base_url": server.base_url,
                           "default": "fake-model", "context_length": 128000}
        for section, settings in dict(
                agent={"api_max_retries": 1}, updates={"check": False}, models_dev={"url": "http://127.0.0.1:9/api.json"},
                skills={"creation_nudge_interval": 0}, memory={"nudge_interval": 0}).items():
            config.setdefault(section, {}).update(settings)
        config.setdefault("telemetry", {}).setdefault("shared_metrics", {}).update(
            enabled=False, send=False, offer_version=OFFER_VERSION)
        atomic_config_write(home / "config.yaml", config)
        with loopback_only(external):
            from run_agent import AIAgent
            with turn("owner", "owner", session=args["session"]) as event, \
                    patch("hermes_cli.lifecycle.invoke_hook", wraps=invoke_hook) as hooks, \
                    closing(SessionDB(db_path=home / "state.db")) as db:
                with closing(AIAgent(provider="custom", base_url=server.base_url, api_key="fake-loopback",
                        model="fake-model", session_db=db, session_id=args["session"], quiet_mode=True,
                        platform="telegram", user_id="owner", gateway_session_key=args["session"],
                        enabled_toolsets=["terminal"], skip_memory=True, skip_context_files=True,
                        skip_background_review=True)) as agent:
                    state.update(agent=agent, event=event)
                    result = agent.run_conversation("run two commands", conversation_history=[], task_id=args["session"])
                actor = values()["actor"]
        requests = server.main_requests()
        messages = requests[-1]["messages"]
        blobs = [json.dumps(r["messages"]) for r in requests]
        return dict(response=result["final_response"], actor=actor, redirect=state["redirect"],
                    tools=[str(m.get("content")) for m in messages if m.get("role") == "tool"],
                    before=state["before"], after=[r.id for r in runtime.auth.registry.recent(200)],
                    hook_calls=sum(c.args[0] == "pre_llm_call" for c in hooks.call_args_list),
                    requests=len(requests),
                    frozen_device_prompt=all("Commands run there, not on the server." in json.dumps(r["messages"][:1])
                                             for r in requests),
                    start_facts=all("Dirtside target facts (data)" in b for b in blobs),
                    server_line=any("Dirtside target: server. Commands run on the server." in b for b in blobs),
                    external_connections=external)
