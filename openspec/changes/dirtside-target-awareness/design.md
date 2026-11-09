# Design

## Context and evidence

Core's `tools/file_tools_paths.py`, lines 273, 310 and 334 at `84a0301`, special-cases only ssh; lines 147 to 154 expand tilde through the host and line 173 resolves gateway symlinks. Core's `agent/turn_context.py`, lines 849 to 907 at `84a0301`, aggregates hook context into the current user turn; lines 997 to 1013 stamp the composed text and lines 1381 to 1388 replay it on later turns. The latter paths are lines 1089 to 1105 and 1481 to 1487 at `8d7061f`. Every authorized turn's fact line stays in conversation history and can disclose device name, OS and home to other participants whose own device calls are denied. Both selection reply spellings also show the home to the whole chat. Core's `website/docs/user-guide/features/hooks.md`, lines 678 to 700 at `84a0301`, documents the public hook. Latest 8d7061f has the same relevant path behavior. Core's `tools/file_tools.py`, lines 685 and 1102 to 1104 at `84a0301`, passes raw paths to remote plain-text reads/searches, whereas lines 442, 902 and 1004 send resolved paths for extractable documents, writes and patches. Those operations still execute on the device, possibly at a gateway-shaped path because core resolves file paths on the gateway. The shared-disk rig cannot establish correctness across separate filesystems.

## Decision and rejected alternatives

Reuse resolve_target and Access with require_contact=False, quote supplied values with prompt.quoted and perform no contact or network probe. Compare the absolute device home with Path(home).resolve() on the gateway. If unchanged, forbid file-tool tilde and recommend absolute paths under that home. If changed, direct writes, patches and extractable document reads through terminal commands while retaining absolute plain-text reads and searches. Child paths may still contain gateway symlinks, so the docs retain that limit. Explicit stored server selection returns the fixed server fact; an untouched server-default conversation yields nothing. Return nothing on target-resolution failure. Do not mutate already frozen bytes, spoof ssh or set is_container as a path workaround.

The backend setup is mandatory. The public config reader and process environment
do not expose the frozen session policy, so no selection is refused. Lazily call
hermes_cli.config.read_raw_config_readonly, a public module on both cores (core's
`hermes_cli/plugin_validate_private_imports.py`, lines 27 to 68, and core's
`hermes_cli/config.py`, lines 1860 to 1864 at `84a0301`). A non-empty string in
terminal.backend keeps the configured-backend warning unless it is dirtside.
A missing or empty setting uses os.environ.get("TERMINAL_ENV", "").strip() or
"local"; that source is also silent only for dirtside. Otherwise the sentence
names the bounded, quoted fallback and explains that terminal.backend is not set.
Core's `tools/terminal_tool.py`, lines 813 to 817, reads the environment fallback;
core's `hermes_cli/config.py`, lines 2082 to 2086 at both revisions, gives it
precedence when the file omits backend. A missing or unparseable file returns
an empty mapping and follows the missing branch. An already bridged dirtside
process therefore stays silent if the file later becomes unreadable. A reader
that raises or exits and non-string explicit values stay silent.

Both warning sentences require the config command and gateway restart. The
hook and newly rendered frozen section return only the shared warning after
the same authorization for saved or default device targets. Keep the one helper
on Access and leave shortcuts delegating. Do not mutate config, import core
from a device entry point, add private surfaces or claim a frozen-session
effective-backend probe from the fallback.

## Boundaries and validation

New awareness module, registration, use reply, manifest, README, ARCHITECTURE and core-rig tests. No core changes.

Absolute-file and known-limit tests pin existing behavior and pass on the base; the hook and selection-home guards fail there. Tests run with isolated homes and ephemeral ports under nice. Each scenario below maps to the named test in tasks.md. First copy tests into a pristine archive of tree b67971b30ee06d71c69950e52f4bd135fc542afc and record red, then test the work tree and record green. No index changes, core edits, protocol changes or new private core imports. Shared docs and budgets may accumulate later package edits, recorded in the report.

The rig sends next-turn metadata through its already loaded manager's invoke_hook method, the same dispatcher used by core's `hermes_cli/plugins.py`, lines 1800 to 1811 at `84a0301`. It does not import private turn-context helpers or duplicate message assembly. Core's independent injection path is traced at core's `agent/turn_context.py`, lines 849 to 907 at `84a0301`. Existing registration fakes now accept the hook and named shortcuts, and patch both the lazy public storage definition and the base tree's old alias. Their default-target guard also checks the hook and shared shortcut command object.

Correction 3 first records negative checks against the previous implementation.
Real slash and hook cases boot a configuration naming local and verify core
also reports local, without requiring online device execution. They compare
silent cases with their original replies and facts, including an unreadable
config path. Reader-exception and bounded-value checks supplement dispatch.
The Android test variable rename is non-behavioral; do not invent a failing
assertion for it. Final validation uses one frozen export on both cores.

The rebase adds real prompt-call coverage for saved and configured-default
targets. Review extends real slash, hook and prompt coverage to missing and
empty settings with no environment, and to dirtside/docker environment
fallbacks including surrounding whitespace. Configured local, dirtside,
non-string, reader failures and already-bridged unreadability stay covered.
Raw missing/unparseable file results and hostile fallback values have direct
hook checks. Unit facts tests explicitly configure dirtside rather than
weakening assertions. Server selection never warns; cached bytes stay frozen.
