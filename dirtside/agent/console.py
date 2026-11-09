"""Core-free entry point sharing the plugin's device command handlers."""
import argparse
from ..cli import handle, setup_parser


def main():
    parser = argparse.ArgumentParser(prog="dirtside-agent", description="Pair and run a personal device")
    setup_parser(parser, standalone=True)
    return handle(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
