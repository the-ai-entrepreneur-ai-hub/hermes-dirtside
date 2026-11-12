# Tasks

## 1. Child environment

- [x] 1.1 Exact child names, login, stdin, passthrough, policy compatibility and names-only CLI output have regression coverage.
- [x] 1.2 The policy field, executor environment and startup disclosure keep four-key files readable.
- [x] 1.3 Real serve and terminal calls cover both transports with fake dotenv credentials.

## 2. Re-pairing

- [x] 2.1 Validated passthrough names survive signed re-pairing without printing values.
- [x] 2.2 Only pairing recovers from damaged old configuration with empty names and a constant warning; normal configuration reads remain strict.
