# Preset Name Null Crash Review Findings

Reviewed:
- `docs/plans/2026-07-30-preset-name-null-crash-design.md`
- `docs/plans/2026-07-30-preset-name-null-crash.md`

## Important

### Clearing during server validation can still save the old name

`handleSubmit` captures `name` and `description`, awaits
`validatePresetName()`, and then unconditionally calls `onSavePreset()` with
those captured values. The Save button is disabled while validation is in
progress, but `PresetNameCombobox` is not. A user can therefore start
validation, clear the combobox (including through the `null` path), see the
required-name state, and still have the earlier name saved when the validation
promise resolves. That contradicts the specified cleared state and leaves the
null transition incomplete.

Required fix: Define how edits during `isValidating` are handled. Either disable
the name and description inputs for the entire validation request, or invalidate
the pending request when either value changes and ignore its eventual result.
Add a deferred-promise test that clears the name while validation is pending and
asserts that resolving the old request cannot call `onSavePreset`.

## Minor

### The regression test does not verify the description transition

The test deliberately starts from `duel-cfg`, whose description is
`Comp duel`, but it never checks that an untouched auto-filled description is
cleared with the name. The design explicitly includes description selection in
the normalized downstream flow. The proposed assertions would still pass if a
future change left the old preset description visible after returning to New
preset mode.

Suggested fix: Assert that the Description textarea contains an empty string
after the null clear. Retain the existing manual-description test to document
that a user-edited description is intentionally preserved.

### The stub-only regression does not cover the actual clear event chain

The new button invokes `PresetSaveTab`'s callback directly, so it verifies the
state-boundary guard but not the production chain from Headless UI's empty input
handling through `PresetNameCombobox` to that guard. A wrapper regression could
break that forwarding while this test remains green.

Suggested fix: Add one integration-level test using the real
`PresetNameCombobox`/Headless UI interaction that enters a value and clears the
input, then asserts the tab remains rendered with an empty controlled value.
Keep the direct-null unit test for focused coverage of the callback contract.

## Tests To Add

- Start validation for a valid new name with a deferred
  `validatePresetName()` result, clear the combobox, resolve validation, and
  assert `onSavePreset` is not called with the stale name.
- Clear `duel-cfg` through the null callback and assert the untouched
  auto-filled description changes from `Comp duel` to an empty string.
- Clear the input through the real `PresetNameCombobox`/Headless UI event path
  and verify the controlled name becomes empty without unmounting the tab.
