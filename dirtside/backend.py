"""Core local handoff and explicit terminal-workdir intent."""
from contextvars import ContextVar

_WORKDIR = ContextVar("dirtside_terminal_workdir", default=None)


def local_environment(cwd, timeout):
    # Pending public local-backend handoff seam; preserve core's credential scrub.
    from tools.environments.local import LocalEnvironment
    return LocalEnvironment(cwd=cwd, timeout=timeout)


def terminal_workdir():
    return _WORKDIR.get()


def tool_execution(*, tool_name, args, next_call, **context):
    token = _WORKDIR.set(bool(args.get("workdir")) if tool_name == "terminal" else None)
    try:
        return next_call(args)
    finally:
        _WORKDIR.reset(token)
