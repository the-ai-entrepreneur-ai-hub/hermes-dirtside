"""Bounded private operational log, without commands, output or credentials."""
import json
import logging
import os
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from .config import device_path

class _PrivateLog(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")

class Activity:
    def __init__(self):
        path = device_path().with_name("agent.log")
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.handler = _PrivateLog(path, maxBytes=5 << 20, backupCount=1)
        self.logger = logging.Logger("dirtside-agent", logging.INFO)
        self.logger.addHandler(self.handler)

    def write(self, event, **fields):
        self.logger.info(json.dumps(dict(time=time.time(), event=event, **fields)))

    def close(self):
        self.handler.close()

def recent_activity():
    path = device_path().with_name("agent.log")
    try:
        with path.open() as stream:
            return [json.loads(line) for line in deque(stream, maxlen=12)]
    except FileNotFoundError:
        return []
