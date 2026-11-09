# Design

## Context and evidence

Use one Access object holding ctx and a validated owners list. Read ctx.session_surface and public get_session_env at every command and dispatch. Local host surfaces require trusted surface provenance and no messaging platform; canonical platform local plus the core local surface is also local. A platform value cli with a messaging user id cannot grant local authority. Cron retains the existing explicit-target and server-default behavior. Missing remote identity fails closed, never becomes local.

Core 84a0301 evidence: hermes_cli/plugins.py:602-605; hermes_cli/plugin_session.py:23-30,43-45 prefers active policy surface and classic CLI reference; gateway/run.py:3959-3989 binds adapter platform and sender id each turn; gateway/session_context.py:131-158 binds task-local values. Canonical local surfaces are validated and mapped in gateway/session_policy.py:85,429-430,489 and authorized in gateway/session_commands.py:258-264. Legacy TUI/Desktop binds source, not platform, in tui_gateway/server.py:931-950; direct ACP binds empty platform/id in acp_adapter/server.py:770-772; classic CLI uses the manager CLI reference. Therefore an empty platform alone is not proof: use the public surface or the core local source, and never infer local from a user id. Latest 8d7061f adds session_client (a label, not auth), moves ctx to plugins_context.py, and preserves these identity semantics.

Add owner TEXT NOT NULL DEFAULT 'local' transactionally; pending codes carry the minting owner and completion preserves it even when reusing a revoked device id. Registry commands check active and pending name ownership without disclosing hidden devices. An explicit inaccessible target fails closed, a default inaccessible target resolves server. The prompt uses the same resolver. The turn process authorizes before creating delegates; the client carries a bounded sender identity in local IPC, not in the device protocol, and the owner rechecks against its own owners config before submitting. Host-authenticated dashboard controls remain local.

Rejected: per-conversation ownership permits group-chat borrowing; checking only slash commands misses cached dispatch; trusting a supplied user id local allows spoofing; adding owner data to device protocol is unnecessary.

## Validation and migration

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_owner_commands`: Owner controls.
- `test_pairing_authority`: Pairing authority.
- `test_group_dispatch`: Dispatch authority.
- `test_owned_default`: Default authority.
- `test_old_registry_migration`: Compatible registry migration.
- `test_sender_provenance`: Unspoofable local identity.
