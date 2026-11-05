# Spec Delta

## Purpose

Back published performance claims with reproducible signed-loopback measurements and explicit pass or fail targets.

## ADDED Requirements

### Requirement: Comparable command latency
The loopback benchmark SHALL report p50 and p95 added elapsed time for pwd relative to core's local environment on the same host. Both paths SHALL be warmed, and the device path SHALL sign and verify normal protocol messages.

#### Scenario: Paired timing samples
- **WHEN** the loopback benchmark runs
- **THEN** at least 50 paired local/device samples produce nearest-rank percentiles of device-minus-local duration
- **AND** command failures fail the benchmark rather than becoming latency samples

### Requirement: Bulk output and cancellation measurements
The benchmark SHALL verify a complete 10,000,000-byte output transfer and report decimal MB/s. It SHALL measure elapsed time from kill to a running tool call returning, not merely the cancellation signal.

#### Scenario: Full-fidelity output
- **WHEN** throughput is measured
- **THEN** output capture is unbounded and all expected bytes and the exit code are verified

#### Scenario: Cancel a running command
- **WHEN** the benchmark kills an active request
- **THEN** it waits for the tool result and verifies cancellation with exit code 130

### Requirement: Enforced published targets
The loopback command SHALL print a Markdown table and exit nonzero if p50 exceeds 15 ms, p95 exceeds 40 ms, throughput is below 8 MB/s or cancellation exceeds 50 ms. Published results SHALL state the date, source revision and loopback limitations.

#### Scenario: Threshold boundary
- **WHEN** any measured metric misses its target
- **THEN** the table marks that metric as failed and the command exits nonzero
- **AND** exact boundary values pass
