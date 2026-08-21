import { EditorState } from '@codemirror/state';
import { describe, expect, it, vi } from 'vitest';

import {
  commandCompletionOptions,
  createQlCfgLinter,
  cvarCompletionOptions,
  stripManagedCvars,
} from './codemirror-lang-qlcfg';

function lint(doc) {
  const onLintResults = vi.fn();
  const diagnostics = createQlCfgLinter([], onLintResults)({
    state: EditorState.create({ doc }),
  });

  return { diagnostics, onLintResults };
}

describe('createQlCfgLinter', () => {
  it('does not report qlx_serverBrandName as managed', () => {
    const { diagnostics, onLintResults } = lint('set qlx_serverBrandName "Custom Brand"');

    expect(diagnostics).toEqual([]);
    expect(onLintResults).toHaveBeenCalledWith(false);
  });

  it('still reports managed cvars as ignored', () => {
    const { diagnostics } = lint('set net_ip "192.0.2.1"');

    expect(diagnostics).toEqual([
      expect.objectContaining({
        severity: 'info',
        message: 'This cvar will be ignored. Forced to "" by the app (binds all interfaces, required for 99k LAN rate).',
      }),
    ]);
  });
});

describe('commandCompletionOptions', () => {
  it('matches a substring anywhere in the command name, not just the prefix', () => {
    const labels = commandCompletionOptions('dump').map((o) => o.label);
    expect(labels).toContain('condump');
  });

  it('matches regardless of the case of the typed text or the command name', () => {
    const labels = commandCompletionOptions('RESTART').map((o) => o.label);
    expect(labels).toContain('cvar_restart');
  });
});

describe('cvarCompletionOptions', () => {
  it('matches a substring anywhere in the cvar name, not just the prefix', () => {
    const labels = cvarCompletionOptions('rate').map((o) => o.label);
    expect(labels).toContain('sv_lanforcerate');
  });

  it('matches regardless of the case of the typed text or the cvar name', () => {
    const labels = cvarCompletionOptions('LAN').map((o) => o.label);
    expect(labels).toContain('sv_lanforcerate');
  });
});

describe('stripManagedCvars', () => {
  it('preserves qlx_serverBrandName values', () => {
    const cfg = [
      'set qlx_serverBrandName "Custom Brand"',
      'set net_ip "192.0.2.1"',
    ].join('\n');

    expect(stripManagedCvars(cfg)).toBe([
      'set qlx_serverBrandName "Custom Brand"',
      'set net_ip ""',
    ].join('\n'));
  });
});
