## ADDED Requirements

### Requirement: Minimal child environment
A device command MUST receive only set PATH, HOME, USER, LANG, LC_*, TERM, TMPDIR and owner-declared env_passthrough values; the parent environment MUST remain unchanged.

#### Scenario: test_executor_exact_environment
- **WHEN** a non-login command with stdin runs env -0
- **THEN** the exact allowed name set plus bash's PWD, SHLVL and _ is returned without planted secrets

### Requirement: Login isolation
Login commands MUST start with the same minimal environment.

#### Scenario: test_login_environment
- **WHEN** a login shell uses an empty temporary profile
- **THEN** allowed values arrive and no planted secret name or value arrives

### Requirement: Owner passthrough
Only the device policy MUST widen the child environment; unset declared names MUST remain absent.

#### Scenario: test_declared_passthrough
- **WHEN** a declared name is set and another is unset
- **THEN** only the set declared name arrives and undeclared secrets do not

### Requirement: Policy compatibility
The policy MUST load old four-key files, save env_passthrough, and refuse duplicate, malformed, oversized or wrongly typed lists.

#### Scenario: test_policy_files
- **WHEN** old and new policy files are loaded and saved
- **THEN** old files mean an empty list and invalid lists fail with a clear error

### Requirement: Device policy CLI
The policy command and serve startup MUST disclose names only and changes MUST apply at the next start.

#### Scenario: test_policy_cli
- **WHEN** the owner shows, sets or clears passthrough
- **THEN** the saved names and startup names match without printing values

### Requirement: Real serve isolation
The real serve CLI MUST keep Hermes .env keys out of device commands in both transports.

#### Scenario: test_serve_dotenv_isolation
- **WHEN** core terminal executes env on a real CLI-served device
- **THEN** none of the fake provider names or values appears and ordinary shell commands still work
