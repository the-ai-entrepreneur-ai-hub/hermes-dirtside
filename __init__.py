"""Directory plugin entry point."""

def register(ctx):
    from .dirtside import register as register_package

    register_package(ctx)
