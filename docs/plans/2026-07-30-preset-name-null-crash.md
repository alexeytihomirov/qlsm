# Preset Name Null Crash Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent the Preset Manager Save / Overwrite tab from crashing when Headless UI clears the preset-name combobox with a `null` value.

**Architecture:** Keep `PresetSaveTab` state string-only by normalizing the combobox callback at the component boundary. Exercise the real callback contract through the existing mocked combobox, leaving the backend, file upload flow, nested dialogs, and authentication behavior unchanged.

**Tech Stack:** React 19, Headless UI 2.2.2, Vitest, Testing Library, ESLint

---

### Task 1: Reproduce The Null Combobox Crash

**Files:**
- Modify: `frontend-react/src/components/presetManager/__tests__/PresetSaveTab.test.jsx`
- Test: `frontend-react/src/components/presetManager/__tests__/PresetSaveTab.test.jsx`

**Step 1: Extend the combobox test stub**

Add a button to the existing `PresetNameCombobox` mock that forwards `null` to
the parent callback:

```jsx
default: ({ value, onChange }) => (
  <>
    <input
      aria-label="Preset Name"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
    <button type="button" onClick={() => onChange(null)}>
      Clear Preset Name
    </button>
  </>
),
```

**Step 2: Write the failing regression test**

Start from an existing editable preset so clearing also exercises the
overwrite-to-new transition:

```jsx
it('treats a null combobox value as an empty preset name', () => {
  setup({ initialOverwriteName: 'duel-cfg' });

  fireEvent.click(screen.getByRole('button', { name: 'Clear Preset Name' }));

  expect(screen.getByLabelText('Preset Name')).toHaveValue('');
  expect(screen.getByText('New preset')).toBeInTheDocument();
  expect(screen.getByLabelText('Description')).toHaveValue('');
  expect(screen.getByText('Preset name is required.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /save preset/i })).toBeDisabled();
});
```

**Step 3: Run the test to verify it fails**

Run:

```bash
cd frontend-react
pnpm test src/components/presetManager/__tests__/PresetSaveTab.test.jsx
```

Expected: FAIL with `Cannot read properties of null (reading 'trim')`.

**Step 4: Commit the regression test**

```bash
git add frontend-react/src/components/presetManager/__tests__/PresetSaveTab.test.jsx
git commit -m "test: reproduce null preset name crash"
```

### Task 2: Normalize The Preset Name At The State Boundary

**Files:**
- Modify: `frontend-react/src/components/presetManager/PresetSaveTab.jsx:52-57`
- Test: `frontend-react/src/components/presetManager/__tests__/PresetSaveTab.test.jsx`

**Step 1: Implement the minimal normalization**

Normalize the callback value once and use the normalized string throughout the
handler:

```jsx
const handleNameChange = (next) => {
  const normalizedName = next ?? '';
  setName(normalizedName);
  setValidationError(validateNameLocally(normalizedName));
  if (descriptionTouched) return;
  const match = editablePresets.find(
    (p) => p.name.toLowerCase() === normalizedName.trim().toLowerCase()
  );
  setDescription(match ? (match.description || '') : '');
};
```

Do not add unrelated null guards or modify `PresetNameCombobox`; its `null`
callback is part of the installed Headless UI contract.

**Step 2: Run the focused regression test**

Run:

```bash
cd frontend-react
pnpm test src/components/presetManager/__tests__/PresetSaveTab.test.jsx
```

Expected: all `PresetSaveTab` tests PASS.

**Step 3: Run the preset-manager test group**

Run:

```bash
cd frontend-react
pnpm test src/components/presetManager/__tests__
```

Expected: all preset-manager tests PASS.

**Step 4: Commit the fix**

```bash
git add frontend-react/src/components/presetManager/PresetSaveTab.jsx
git commit -m "fix: handle cleared preset name"
```

### Task 3: Bump The Patch Release

**Files:**
- Modify: `VERSION`
- Modify: `docs/user/version.json`
- Modify: `docs/user/releases.md`

**Step 1: Update synchronized version sources**

Set `VERSION` and `docs/user/version.json` to `1.19.2`. Add the newest release
row with the current date and the requested generic description:

```markdown
| `v1.19.2` | 2026-07-30 | — | Bug fixes and improvements. |
```

The PR link is added after GitHub assigns the PR number.

**Step 2: Verify version consistency**

Run:

```bash
test "$(tr -d '\n' < VERSION)" = \
  "$(node -p "require('./docs/user/version.json').latest")"
rg -n 'v1\.19\.2|Bug fixes and improvements\.' docs/user/releases.md
```

Expected: both commands exit successfully and the release row is the first
entry.

**Step 3: Commit the release bump**

```bash
git add VERSION docs/user/version.json docs/user/releases.md
git commit -m "chore: release v1.19.2"
```

### Task 4: Verify The Complete Change

**Files:**
- No additional files

**Step 1: Run frontend lint**

Run:

```bash
cd frontend-react
pnpm lint
```

Expected: PASS with no errors.

**Step 2: Run the full frontend test suite**

Run:

```bash
cd frontend-react
pnpm test
```

Expected: all frontend tests PASS.

**Step 3: Run the production build**

Run:

```bash
cd frontend-react
pnpm build
```

Expected: Vite production build succeeds.

**Step 4: Review repository integrity**

Run:

```bash
git diff main...HEAD --check
git status --short
git log --oneline main..HEAD
```

Expected: no whitespace errors, a clean working tree, and only the approved
design, plan/review artifacts, regression test, source fix, and synchronized
release bump.

### Task 5: Review And Open The Pull Request

**Files:**
- Modify after PR creation: `docs/user/releases.md`

**Step 1: Run the requesting-code-review skill**

Review the complete `main...HEAD` diff for correctness, scope, accessibility
regressions, test coverage, and compliance with the approved design. Address
all accepted findings and repeat verification.

**Step 2: Push the branch**

```bash
git push -u origin bug/preset-name-null-crash
```

Expected: the remote branch is created successfully.

**Step 3: Open the pull request**

Create a PR against `main` summarizing the null normalization, regression test,
and `v1.19.2` bump. Include the focused tests, full frontend suite, lint, and
build in the test plan.

**Step 4: Add the assigned PR link to release notes**

Replace the `—` in the `v1.19.2` row with the assigned link:

```markdown
[#PR_NUMBER](https://github.com/dngrtech/qlsm/pull/PR_NUMBER)
```

Commit and push this release-note completion:

```bash
git add docs/user/releases.md
git commit -m "docs: link v1.19.2 release to PR"
git push
```

**Step 5: Verify the published PR state**

Confirm the PR targets `main`, contains all expected commits, and has no
unexpected files. Report its URL to the user and stop. Do not merge or enable
auto-merge without explicit user approval.
