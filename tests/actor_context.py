"""Real core turn bindings and sequential actions for actor regression tests."""
import inspect
from contextlib import contextmanager
from contextvars import Context, copy_context
from types import SimpleNamespace

from gateway.config import GatewayConfig, Platform
from gateway.platforms.event import MessageEvent
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_context
from gateway.session_context import clear_session_vars, get_session_env, set_session_vars

HAS_ACTOR = "actor_id" in inspect.signature(set_session_vars).parameters


def values():
    return dict(actor=get_session_env("HERMES_SESSION_ACTOR_ID", None),
                route=get_session_env("HERMES_SESSION_USER_ID"),
                platform=get_session_env("HERMES_SESSION_PLATFORM"))


@contextmanager
def turn(actor="owner", route="owner", shared=False, session="actor-turn", slash=False):
    source = SessionSource(Platform.TELEGRAM, "shared-room", chat_type="group",
                           user_id=actor if slash else route, shared_session=shared)
    event = MessageEvent("first input", source=source, user_id=actor)
    config = GatewayConfig(group_sessions_per_user=False)
    ctx = (build_session_context(source, config) if slash
           else build_session_context(source, config, event=event))
    assert ctx.shared_multi_user_session
    ctx.session_key = ctx.session_id = session
    tokens = GatewayRunner._set_session_env(SimpleNamespace(adapters={}), ctx)
    try:
        yield event
    finally:
        clear_session_vars(tokens)


def sequence(runtime, args):
    """Keep the real event and its copied tool context alive across a merge."""
    result = []
    with turn(args["actor"], args.get("route"), args.get("shared", False),
              args["session"], args.get("slash", False)) as event:
        copied = copy_context()
        for step in args["steps"]:
            method, params = step["method"], {**args, **step.get("params", {})}
            if method == "absorb":
                event.absorb_turn_input(MessageEvent("joined input", source=event.source,
                                                     user_id=params["joined"]))
                result.append(copied.run(values))
            elif method == "identity":
                result.append(dict(**copied.run(values), sender=copied.run(runtime.auth.relay.access.identity)))
            elif method == "unbound":
                result.append(Context().run(values))
            elif method == "request_ids":
                result.append([row.id for row in runtime.auth.registry.recent(200)])
            else:
                result.append(copied.run(getattr(runtime, method), params))
    return result
