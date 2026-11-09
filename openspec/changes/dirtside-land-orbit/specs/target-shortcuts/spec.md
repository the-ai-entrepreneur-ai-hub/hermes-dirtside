## ADDED Requirements

### Requirement: target shortcuts

The plugin SHALL provide the behavior below without changing core, protocol version 1 or the base authorization rules.

#### Scenario: test_land_orbit_real_dispatch
- **WHEN** real core dispatch receives land, orbit and the long form
- **THEN** both names register without collisions and store the same target

#### Scenario: test_shortcut_owner_picker_and_usage
- **WHEN** an unauthorized sender, empty land or extra arguments are supplied
- **THEN** owner refusal matches, picker matches, invalid arguments yield usage without mutation

#### Scenario: test_native_shortcuts_preserve_command_source
- **WHEN** native local source dispatch selects a named device, uses the picker or selects orbit
- **THEN** authorization, offered choices and stored targets match the long form, and command authority is reset

#### Scenario: test_relay_shortcuts_and_prompt_do_not_disclose_host_devices
- **WHEN** a relay-decoded local event names no user or the host uid and the device is a saved or configured-default target
- **THEN** device selection and picker refusal match the long form, explicit server selection remains available, and neither prompt path reveals device facts
