# Tasks

## 1. Timeout ownership

- [x] 1.1 Device-first, empty-output, ordinary-exit-124 and bounded-capture regressions distinguish terminal outcomes.
- [x] 1.2 Execution and upload retries share the policy-capped grace duration.
- [x] 1.3 Core's timeout rendering retains exact output, flags and spill metadata without losing cap identity.

## 2. Portable execution

- [x] 2.1 Signal tests keep a real shell and child, with acknowledged dispatch and observed worker readiness.
- [x] 2.2 Cwd and flush/stop tests use portable paths and observed readiness rather than fixed delays.
- [x] 2.3 CI scratch stays outside the checkout while doctor stages that checkout.
- [x] 2.4 Background-log tests acknowledge both fragments before exit, retaining exact output, exit 7 and failure cleanup.
