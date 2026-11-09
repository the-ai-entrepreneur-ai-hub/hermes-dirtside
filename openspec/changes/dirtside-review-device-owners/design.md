# Design

## Context and evidence

Use one Access object holding ctx and a validated owners list. Read ctx.session_surface and public get_session_env at every command and dispatch. Local host surfaces require trusted policy provenance and no messaging platform; policy-free surface local additionally needs core's actual non-relay command source as specified in Correction 4. A platform value cli with a messaging user id cannot grant local authority. Cron retains the existing explicit-target and server-default behavior. Missing remote identity fails closed, never becomes local.

Core 84a0301 evidence: core's `hermes_cli/plugins.py`, lines 602 to 605 at `84a0301`; core's `hermes_cli/plugin_session.py`, lines 23 to 30, 43 to 45 at `84a0301` prefers active policy surface and classic CLI reference; core's `gateway/run.py`, lines 3959 to 3989 at `84a0301` binds adapter platform and sender id each turn; core's `gateway/session_context.py`, lines 131 to 158 at `84a0301` binds task-local values. Canonical local surfaces are validated and mapped in core's `gateway/session_policy.py`, lines 85, 429 to 430, 489 at `84a0301` and authorized in core's `gateway/session_commands.py`, lines 258 to 264 at `84a0301`. Legacy TUI/Desktop binds source, not platform, in core's `tui_gateway/server.py`, lines 931 to 950 at `84a0301`; direct ACP binds empty platform/id in core's `acp_adapter/server.py`, lines 770 to 772 at `84a0301`; classic CLI uses the manager CLI reference. Therefore an empty platform alone is not proof: use the public surface or the core local source, and never infer local from a user id. Latest 8d7061f adds session_client (a label, not auth), moves ctx to plugins_context.py, and preserves these identity semantics.

Add owner TEXT NOT NULL DEFAULT 'local' transactionally; pending codes carry the minting owner and completion reuses a revoked device id only for the same owner. Registry commands check active and pending name ownership without disclosing hidden devices through use/revoke; pairing availability is observable. An explicit inaccessible target fails closed, a default inaccessible target resolves server. The prompt uses the same resolver. The turn process authorizes before creating delegates; the client carries a bounded sender identity in local IPC, not in the device protocol, and the owner rechecks against its own owners config before submitting. Host-authenticated dashboard controls remain local.

Rejected: per-conversation ownership permits group-chat borrowing; checking only slash commands misses cached dispatch; trusting a supplied user id local allows spoofing; adding owner data to device protocol is unnecessary.

## Validation and migration

Follow-on core tracing during WP3 found native user ids outside the initial ASCII subset: core's `plugins/platforms/email/adapter.py`, line 839 at `84a0301` carries the full sender address, core's `plugins/platforms/signal/adapter.py`, lines 423 to 424, 471 at `84a0301` carries a phone number, and core's `plugins/platforms/irc/adapter.py`, line 318 at `84a0301` carries the nick. Preserve bounded printable ids verbatim, including plus signs and brackets; reject control and formatting characters. test_native_sender_spelling_can_own_device covers ownership and private discovery for these three sources.

Each scenario names its regression test below. Run every new file on a pristine git archive of 0ae9359 with only the test files copied in, then on this tree; keep logs in the supplied notes folder. Existing compatibility controls may already pass on the old code and are reported separately, never claimed as red fixes. Use temporary HOME and HERMES_HOME for every process. Run package and fast suites before the next package. Save cumulative tracked diff and untracked tar checkpoints. Final verification uses both supplied core interpreters without changing core or installing a replacement CLI.

- `test_owner_commands`: Owner controls.
- `test_pairing_authority`: Pairing authority.
- `test_group_dispatch`: Dispatch authority.
- `test_owned_default`: Default authority.
- `test_old_registry_migration`: Compatible registry migration.
- `test_sender_provenance`: Unspoofable local identity.

The final native-email regression uses core's actual _extract_email_address to prove quoted local parts with ASCII spaces are valid identities (core's `plugins/platforms/email/adapter.py`, lines 287 to 304, 734, 839 to 840 at `84a0301`). Preserve those spaces exactly; reject control and formatting characters, not valid adapter spelling.

## Correction 1

An implicit default is eligible only when owned by the current sender, local, or a configured owner. Privileged senders do not implicitly trust an unprivileged owner's machine. Non-privileged senders may still mint the configured default name while owners is empty: it cannot capture privileged implicit work, and privileged explicit selection names its owner. Device ownership remains unchanged for ordinary command authority.

Completion reuses only the newest previous paired id and only when that row has the same owner as the pending code. Different-owner completion keeps revoked rows and stale targets intact and uses the pending id; an active previous row is revoked in the same transaction before installing the replacement. Returning to an ancient owner after another owner's pairing never revives the ancient id. Same-owner re-pairing retains its id.

Pairing intentionally reveals whether a name is available because an available name produces a real code while an occupied foreign name refuses. README narrows the missing-name claim to use/revoke and describes this occupancy disclosure; no fake codes or weakened pending-name protection.

## Correction 2

Correction 2 confirms that registry completion revokes a displaced active row but never calls relay.revoke. Under the existing pairing lock, read the previous active device, complete the authenticated pairing transaction, then revoke the previous relay id if the new id differs. Do not cancel anything for invalid or consumed codes, and preserve same-owner id reuse. The gateway request closes immediately; revoked credentials remain rejected by core.

## Correction 3

The earlier policy-only positive control missed canonical commands without an active policy. Both prepared cores' `hermes_cli/plugin_session.py`, lines 23 to 30 at `84a0301` return the environment platform in that case, hence surface local. At pinned core, core's `gateway/control_socket.py`, lines 399 to 411 at `84a0301` (latest lines 411 to 423), only a safe same-user control-socket peer obtains uid matching os.getuid(); core's `gateway/session_worker_reservation.py`, lines 54 to 60 at `84a0301` is identical. Core's `gateway/session_local_recovery.py`, lines 41 to 50 at `84a0301` stamps Platform.LOCAL, and core's `gateway/session_local.py`, lines 369 to 375 at `84a0301` uses the authenticated actor.subject, never a client-supplied user id. Pinned core's `gateway/session_policy.py`, lines 425 to 432 at `84a0301` (latest lines 426 to 433) rejects messaging sources or extra create fields. Messaging build_source takes platform from its adapter, not its user, at core's `gateway/platforms/base.py`, lines 4713 to 4728 at `84a0301`.

C3 added surface local to the existing local-platform branch and required an empty user or the exact process uid; Correction 4 below narrows this insufficient rule. Keep legacy empty-user provenance and cron unchanged; do not accept arbitrary local subjects or messaging user-id lookalikes. Guard the POSIX uid query on Windows rather than raising for a non-uid actor. No new private import or core edit is needed.

tests/test_review_local_native.py boots the ordinary core daemon, obtains a real same-uid control ticket and creates CLI/TUI sessions over the canonical WebSocket. The CLI uses HermesCLI's normal _ensure_gateway_session and process_command, then actual hermes chat quiet single-query turns with a loopback model. The TUI uses slash.exec and prompt.submit on its real canonical transport. Both use the mounted plugin and a real signed device agent. No LocalSessionPolicy or session identity is fabricated. Check status, local-owned discovery, use, per-target cd/export, device execution, revoke and refusal of the next command. Legacy slash_worker initializes HermesCLI but does not open the canonical session itself; the canonical gateway does not use it (core's `gateway/session_commands.py`, lines 195 to 227 at `84a0301`). Do not mistake that older sidecar for this native path.

## Correction 4

C3's ordinary-adapter trace omitted relay ingress. At both prepared cores, core's `gateway/relay/ws_transport.py`, lines 198 to 238, accepts wire platform local and chat_id but stamps delivered_via_upstream_relay=True itself. Core's `gateway/session.py`, lines 100 to 107, marks relay and detached-route signals wire-invisible. Native chat_id equals session_id in both real probes, but the wire can choose chat_id and routes may be reused; equality is not authentication.

Restore the trusted policy-surface restriction for turns. Policy-free surface local additionally requires actual source platform value local, strict relay flag False and no detached route, scoped to the command with an instance-owned ContextVar and reset in finally. Core's `hermes_cli/plugin_command_dispatch.py`, lines 11 to 32 at both prepared revisions, passes declared context keywords; core's `gateway/run_inbound_hooks.py`, lines 288 to 299, supplies the actual source. The existing empty-or-exact-POSIX-uid check remains. Missing/remote/incomplete source metadata fails closed; no new core import is needed. Overlapping calls and exceptions cannot leak proof to another command.

Native turns bind trusted policy in core's `gateway/run_turn_runner.py`, lines 1213 to 1220 at `84a0301`, and lines 1215 to 1222 at `8d7061f`. Keep the actual native CLI/TUI slash-and-turn demos green. Test the real wire decoder through GatewayRunner._set_session_env, including an ignored forged false relay flag, absent/same-uid users and matching chat/session ids. A one-paragraph ingress suggestion stays in private notes, unposted.

Core's `gateway/owner_identity.py`, lines 23 to 44 at both prepared revisions, maps all dashboard and Webapp sign-ins, forwarded logins included, to the host owner. Correct C3's contrary disclosure; arbitrary raw subjects still do not become the host. Windows sid: subjects are not recognized by the current POSIX rule.

Sibling-label controls are already safe on C3: core's `gateway/config.py`, lines 250 to 267 at both prepared revisions, accepts only registered platform names; unknown cli/tui/desktop/acp wire labels fall back to relay at ingress. Keep the existing legacy classifier rather than changing unconfirmed behavior.
