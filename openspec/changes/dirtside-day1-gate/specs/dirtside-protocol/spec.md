# Spec Delta

## Purpose

Define the shared signed wire format so the gateway and device agree on authenticated requests and raw output.

## ADDED Requirements

### Requirement: Signed canonical envelopes
Messages MUST authenticate version, kind, sender, integer timestamp, nonce and body over stable sorted UTF-8 JSON without extra whitespace. Version 1 MUST reject invalid signatures, malformed envelopes and timestamps outside 300 seconds.

#### Scenario: Round trip and tampering
- **WHEN** a valid message is signed and verified with its public key
- **THEN** its fields and body are preserved
- **AND** changing any signed field or using a different key fails verification

#### Scenario: Invalid envelope
- **WHEN** an envelope has the wrong shape, version, types, encoding or timestamp
- **THEN** verification raises a protocol error before dispatch

### Requirement: Device replay protection
The device MUST reject a repeated sender and nonce within the timestamp window, keeping at most 4096 recent nonces. The gateway MUST permit retries to reach sequence and terminal-state deduplication.

#### Scenario: Replay
- **WHEN** the same valid message is verified twice with device replay protection
- **THEN** the first succeeds and the second fails
- **AND** verification without that protection permits the retry

### Requirement: Strict message bodies
Hello, execution, chunk, result and poll bodies MUST reject missing fields, extra fields, invalid types and invalid values. Public keys MUST be 32 bytes, output MUST be validated base64 raw bytes, and each output part MUST be at most 65536 bytes.

#### Scenario: Wire bodies
- **WHEN** each supported body is parsed
- **THEN** it produces its typed value without session or task identifiers in execution messages
- **AND** a wrong shape is rejected

### Requirement: Inline result tail
A result MUST carry a finished or refused outcome and MAY carry one final output part with both sequence and data present.

#### Scenario: Optional tail
- **WHEN** a result contains a valid sequence and raw output encoded as base64
- **THEN** parsing returns the outcome and the final output part
- **AND** a result without either optional field returns no final part
