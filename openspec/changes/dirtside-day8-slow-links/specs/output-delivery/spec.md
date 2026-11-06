# Spec Delta

## Purpose

Deliver device command output without loss on slow links while keeping interactive output timely and all request sizes bounded.

## ADDED Requirements

### Requirement: Bounded coalesced output

The device SHALL coalesce pending output into parts of at most 2 MiB, send one part at a time with in-order sequence numbers, and retain the 64 MiB default output cap.

#### Scenario: Continuous capped flood

- **WHEN** a continuously available 64 MiB flood is drained before each flush deadline
- **THEN** it uses no more than 32 parts including any inline result tail
- **AND** every byte arrives once and in order

### Requirement: Timely interactive output

The device SHALL initiate sending pending output by 200 ms after its first byte, unless the command has already returned that output in its result.

#### Scenario: One hundred bytes while a command remains running

- **WHEN** a command writes 100 bytes and remains running without more output
- **THEN** sending begins by the first byte's 200 ms deadline without waiting for a full part

### Requirement: Gateway size enforcement

The gateway SHALL reject decoded output over 2 MiB with "output part too large" and enforce streamed HTTP body bounds before JSON parsing or verification: 2,797,228 bytes for chunks, including base64 and 1,024 bytes of envelope allowance, and 2,798,252 bytes for results, including another 1,024 bytes for outcome fields and reason. Credential recognition SHALL precede body reads.

#### Scenario: Oversized decoded part

- **WHEN** an authenticated signed part decodes to 2 MiB plus one byte
- **THEN** the part is rejected and no output from it reaches the request

#### Scenario: Oversized streamed body

- **WHEN** a chunk or result body exceeds its HTTP limit with absent or misleading Content-Length
- **THEN** it is rejected with HTTP 413 and "output part too large" without parsing or feeding it

### Requirement: Responsive output validation

JSON parsing, signature verification and body parsing for chunk and result posts SHALL run off the dashboard event loop in existing worker threads.

#### Scenario: A maximum part is being checked

- **WHEN** JSON parsing, signature verification or decoded-body parsing of a maximum chunk or result is held in a worker
- **THEN** a concurrent device poll still answers before that work is released

#### Scenario: A retry overlaps its first post

- **WHEN** concurrent valid chunk posts carry the same request and sequence
- **THEN** the existing relay serialization accepts the retry without HTTP 409 and feeds the bytes only once

### Requirement: Bounded lossless relay and compatible wire shape

The relay SHALL feed one decoded part into core's pipe without another part-sized output buffer, retain only its 4,096-byte pane tail, and keep wire protocol version 1 with unchanged message fields.

#### Scenario: Maximum-sized part

- **WHEN** a valid 2 MiB part arrives while core drains the pipe
- **THEN** all bytes reach core unchanged and the pane retains only the final 4,096 bytes
- **AND** no gateway reordering or parallel upload window is required

### Requirement: Measured remote flood budget

When a matrix run has an external gateway URL, the rig SHALL probe one maximum signed part and a small round trip from the device through that URL once before the rows. It SHALL derive the remote flood timeout as max(120, ceil(1.5 * encoded_flood_bytes / measured_bytes_per_second + part_count * round_trip_s + 10)), counting each part's base64 padding, and record rate, budget and elapsed time in flood evidence without changing its assertions.

#### Scenario: The measured link transfers 1.14 MB/s

- **WHEN** the 64 MiB flood uses 32 parts at 1,140,000 base64 bytes/s and a 0.7 s round trip
- **THEN** its remote command timeout is 151 s and its rig wait is 166 s
- **AND** exit zero, the device cap notice and bounded foreground output are still required

#### Scenario: Loopback matrix

- **WHEN** the matrix runs without an external gateway URL
- **THEN** no link probe runs and the flood keeps its 120 s command timeout and existing assertions

#### Scenario: Core reaches the command timeout

- **WHEN** a rig call's args include a timeout
- **THEN** the rig waits that timeout plus 15 s for core's rendered outcome
- **AND** calls without a timeout retain the existing 90 s default

#### Scenario: A remote row or probe fails

- **WHEN** the remote flood fails
- **THEN** its evidence still records the measured link and chosen budget
- **WHEN** a probe cannot produce a valid positive rate
- **THEN** the run fails with probe evidence before rows and releases its owned resources

#### Scenario: Fast upload is no slower than the sampled round trip

- **WHEN** a finite positive probe upload duration is less than or equal to the separately sampled round trip
- **THEN** the rate uses probe bytes divided by that upload duration alone
- **AND** the existing remote budget formula and 120 s floor remain unchanged
- **AND** the worker retains its retry coverage but returns the final valid sample instead of rejecting persistent jitter
- **AND** invalid schemas, nonfinite or nonpositive upload durations and nonfinite or negative round trips remain rejected

### Requirement: Non-gating hosted benchmark smoke

The benchmark subprocess smoke SHALL use --report-only and verify exit zero, the summary, four measured rows and two report-only client rows, without requiring PASS verdicts. Strict local acceptance SHALL retain the existing benchmark defaults and gates.

#### Scenario: Hosted throughput is below eight MB/s

- **WHEN** a successful benchmark measures 7.96 MB/s on a noisy hosted runner
- **THEN** the smoke accepts the report with its FAIL verdict visible
- **AND** strict threshold unit tests and execution or byte-integrity failures remain enforced
