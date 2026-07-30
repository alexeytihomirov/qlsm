# Preset Name Null Crash Design

## Problem

Clearing the Preset Manager's name combobox can crash the Save / Overwrite tab
with `Cannot read properties of null (reading 'trim')`. Headless UI 2.2.2
intentionally calls the combobox `onChange` handler with `null` when a
single-value input is cleared, while `PresetSaveTab` assumes every callback
value is a string.

The recreated plugin folder, uploaded file count, authentication response,
blocked browser request, and nested-dialog accessibility warnings do not enter
this failing code path and are outside this fix.

## Selected Approach

Normalize the combobox callback value at the `PresetSaveTab` state boundary:
convert `null` or `undefined` to an empty string before validation, matching,
description selection, or state storage. This preserves the component's
existing string-only state contract and avoids scattering null guards across
every `.trim()` call.

Changing the combobox library integration is unnecessary because `null` is a
documented callback value. Guarding every string operation independently would
be more fragile and could leave future call sites exposed.

## State And Flow

- The combobox may emit a preset-name string or `null`.
- `handleNameChange` converts the value to a string immediately.
- All downstream validation, preset matching, description handling, rendering,
  and submit logic continue to operate on strings.
- A cleared value displays the existing required-name validation and keeps the
  Save Preset button disabled.
- Valid new names and existing-preset overwrite behavior remain unchanged.

## Testing

Add a focused `PresetSaveTab` regression test whose combobox stub emits `null`.
Verify that the tab stays rendered, returns to New preset mode, shows the
required-name validation, and leaves Save Preset disabled. Run the focused
preset-manager tests and frontend lint.

## Release

Publish this patch as `v1.19.2`. Keep all three version sources synchronized:
`VERSION`, `docs/user/version.json`, and `docs/user/releases.md`. Per the
requested release-note style, the changelog text is `Bug fixes and
improvements.`
