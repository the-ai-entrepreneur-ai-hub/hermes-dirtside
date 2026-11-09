"""Short spellings for the same conversation target handler."""


class Shortcuts:
    def __init__(self, commands):
        self.commands = commands

    def land(self, raw_args: str, *, source=None) -> str:
        if len(raw_args.split()) > 1:
            return "Use /land [name|server]."
        return self.select(raw_args.strip(), source=source)

    def orbit(self, raw_args: str, *, source=None) -> str:
        return "Use /orbit." if raw_args.strip() else self.select("server", source=source)

    def select(self, name, *, source=None):
        reply = self.commands("use " + name, source=source)
        if reply.startswith("This conversation now targets server."):
            return "Back in orbit. Commands run on the server."
        return reply.replace("This conversation now targets ", "Landed on ", 1)
