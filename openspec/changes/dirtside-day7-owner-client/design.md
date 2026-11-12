# Design

## Context

See proposal.md. The pinned core mounts dashboard routes in its gateway process, spawns compute and slash workers, and offers no plugin-to-owner execution registration seam. The current rig puts terminal execution in its router process. SQLite stores selections and history, not live relay state.

## Goals / Non-Goals

**Goals:** Keep one relay, one terminal transition and core's existing pipe-backed process handle. Separate the local authenticated IPC protocol from unchanged device protocol version 1.

**Non-Goals:** Core changes, a new daemon, shared-memory queues, SQLite execution coordination, remote local-route access or service installation.

## Decisions

1. Only handling device pair, poll, chunk or result records ownership and performs first-owner stale cleanup. Imports, pane and local routes never do. Any number of servers may mount the API, including the unmanaged gateway auto-started by chat. Publish owner.json atomically for a new pid or origin. Take only the port from the ASGI server tuple and publish 127.0.0.1, or ::1 when an IPv6 listener cannot accept IPv4 loopback. Never trust request headers or the accepted socket's interface address.
2. Registry's existing locked private-key file boundary also mints local.secret once. The owner authenticates loopback peers, unwrapping IPv4-mapped addresses, even with the session gate disabled. Register fixed exec, stream, kill, devices and requests paths at startup. Stream and kill carry a strictly validated id in the query; execution never grows core's exemption set.
3. Relay exposes one transport-selection seam. Registered plugin relays choose their thin client until the router records ownership; isolated domain relays used by the existing unit rig stay direct. The environment, command state and prompt state use this seam.
4. The local stream frames each raw output block with a four-byte big-endian size. A zero size introduces one trailing JSON outcome line. This prevents arbitrary output from impersonating the outcome and avoids buffering an unbounded final output line. Owner reads never exceed CHUNK_BYTES; disconnection closes as LOST with the existing stopped-reading reason. Unattached streams have a bounded attachment window.
5. The client validates literal loopback HTTP and checks pid liveness and its start epoch using the system ps command before connecting. It retains no pid-only cache across reuse. Missing files, dead pids and reused pids mean offline. A live owner's connection/read or malformed-stream failure uses OWNER_MISSING; HTTP status failures report the status and at most 200 printable detail characters. Proxy environment and redirects stay disabled. Submission and stream attachment may retry an owner's pre-handler 401 within three seconds using the same request id; accepted work is never replayed. A stream thread copies bytes into the existing bounded pipe. Confirmed cancellation completes immediately even with a full pipe; only the owner drives device loss.
6. Online state comes from GET local/devices, and live history from GET local/requests, rather than SQLite heartbeats. Pane reads and revocation use the same connection seam as commands and prompts. Secondary local read/revoke routes also forward; local execution, stream and kill reject a non-owner with 409 rather than read its empty relay or create another queue. Stream polling and final closure run in threads because they may write SQLite.
7. Parameterize the existing conformance battery without changing assertions. Extend the rig to support a router-free core worker and a fake-device subprocess owner, plus a test-process core-terminal check. Benchmark 50 paired client pwd samples and report p50/p95 alongside the existing metrics without a client timing threshold.
8. Read session_identity and the cron flag in ConversationEnvironment._current on every dispatch. Retain only the creation key as a fallback for a context naming no session. Key delegates by conversation and target so audit rows and shell snapshots cannot borrow the first conversation's identity. Core binds ContextVars through gateway run._set_session_env and tui_gateway server._set_session_context; slash workers have an explicit per-process key.
9. The device CLI reports bounded printable refusal details and HTTP status, redacting the submitted code. The user verified core's Invalid Host header refusal through the public tunnel. That refusal adds a dashboard.public_url configuration-and-restart hint; non-loopback HTTPS pairing remains allowed by the plugin.

## Risks / Trade-offs

- Arbitrary output could mimic a terminal JSON line -> length framing makes the outcome unambiguous.
- Execution can finish before stream attachment -> retain its handle until attachment or a bounded abandonment timer, then close descriptors.
- The dashboard auth seam accepts only exact paths -> register fixed stream and kill paths once, with query ids.
- A specifically bound interface may not accept loopback -> fail closed, never publish a LAN destination for the secret.
- Separate listeners receiving device traffic can compete -> publish the last device-traffic owner; no leader election. Merely mounting another server cannot compete.

## Migration Plan

Restart the gateway or dashboard after updating. Existing registry and device credentials remain valid; local.secret is created if absent. Rollback ignores the two new private files.
