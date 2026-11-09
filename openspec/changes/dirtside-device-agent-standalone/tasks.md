# Tasks

## Proof and implementation

- [x] Prove `test_legacy_service_keeps_override_and_profile` red on the base and the first implementation, then green after preserving both service state roots.
- [x] Prove `test_isolated_homes_ignore_state_override` red on the base and the first implementation, then green after isolating pytest and rig state.

- [x] Trace core and propose this change before implementation.
- [x] Prove `test_device_imports_without_core` red on the base and green after implementation.
- [x] Prove `test_state_location_order_and_legacy_pairing` red on the base and green after implementation.
- [x] Prove `test_standalone_install_signed_terminal_and_revoke` red on the base and green after implementation.
- [x] Correction 2 replaces the vacuous terminal-child dotenv assertion with a check of the serving process itself. Prove real home and project load_dotenv mutations red in temporary source copies, then green without mutation.
- [x] Prove `test_console_and_pairing_guidance` red on the base and green after implementation.
- [x] Prove `test_pipx_local_install` red on the base and green after implementation.
- [x] Finish documentation and line budgets.
- [x] Save tracked diff and untracked checkpoint, leave the change unarchived.
- [x] Review: prove absolute relative-override lookup and unknown-tilde-user command errors red then green on both cores, including a fresh process in another directory.
