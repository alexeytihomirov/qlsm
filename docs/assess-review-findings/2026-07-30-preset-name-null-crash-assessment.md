# Preset Name Null Crash Findings Assessment

Reviewed:
- `docs/plans/2026-07-30-preset-name-null-crash-design.md`
- `docs/plans/2026-07-30-preset-name-null-crash.md`
- `docs/findings/2026-07-30-preset-name-null-crash-findings.md`

## Assessment

### 1. Clearing during server validation can still save the old name
- **Finding says:** The editable fields can change while asynchronous name validation is pending, but submission still saves the name and description captured before those edits.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. `handleSubmit` captures both values before awaiting `validatePresetName()`, while the combobox and description textarea remain enabled during `isValidating`; ordinary network latency gives a user time to edit or clear them.
- **Pros of fixing:** Prevents a visible cleared or edited form from saving stale values, makes the validation state internally consistent, and closes the same race for both string and `null` name changes.
- **Cons of fixing:** Expands the patch slightly beyond null normalization and requires an asynchronous regression test. Request invalidation would add unnecessary coordination complexity, but disabling the two fields during validation is a small change.
- **Action:** Amend plan
- **Reasoning:** This is a concrete correctness issue in the affected interaction, not a hypothetical future case. The plan should choose the minimal option—disable the name and description fields during validation—and add the deferred-validation regression before implementation proceeds.

### 2. The regression test does not verify the description transition
- **Finding says:** Clearing an existing preset through the null callback should also prove that its untouched auto-filled description is cleared.
- **Assessment:** Accept
- **Edge-case validity:** Realistic. The test starts with `duel-cfg` specifically to exercise the overwrite-to-new transition, and description selection is explicitly part of the design's normalized downstream flow.
- **Pros of fixing:** One assertion verifies the complete intended transition and catches stale preset metadata without requiring another test setup.
- **Cons of fixing:** It adds a small amount of test coupling to the intentional auto-description behavior, but that behavior is already part of the component contract and design.
- **Action:** Amend plan
- **Reasoning:** The assertion is focused, low-cost, and directly supports the stated behavior. Add an empty Description assertion to the proposed null-clear regression; the existing manual-description test remains sufficient for the preservation case.

### 3. The stub-only regression does not cover the actual clear event chain
- **Finding says:** Add an integration test using the real Headless UI combobox so a future wrapper forwarding regression cannot evade the direct-null unit test.
- **Assessment:** Reject
- **Edge-case validity:** Speculative. The production wrapper passes `onChange` directly to Headless UI, and the regression intentionally targets the documented nullable callback contract at `PresetSaveTab`'s state boundary.
- **Pros of fixing:** It could provide broader confidence across the third-party widget and wrapper integration.
- **Cons of fixing:** Reproducing Headless UI's internal clear behavior in jsdom is more brittle, couples the focused test to library event mechanics, and duplicates coverage of a trivial callback pass-through for a hypothetical future regression.
- **Action:** No action needed
- **Reasoning:** The direct `null` callback test precisely exercises the crash and proposed guard. Existing `PresetNameCombobox` coverage already checks typed-value forwarding; a full widget integration test is not necessary to ship this focused fix.

## Bottom Line

2 of 3 findings need action before implementation. Amend the plan to disable name and description editing during server validation with a deferred-promise regression, and add the empty-description assertion to the null-clear test; do not add the proposed Headless UI integration test.
