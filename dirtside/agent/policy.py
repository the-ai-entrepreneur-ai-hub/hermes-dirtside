"""Evaluate compiled deny patterns against the model's command."""
from ..model import Refused


def evaluate(command, policy):
    for pattern in policy.deny_patterns:
        if pattern.search(command):
            return Refused(f"command matches deny pattern: {pattern.pattern}")
    return None
