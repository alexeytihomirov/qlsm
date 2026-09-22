import { describe, expect, it } from 'vitest';
import {
  MOUNT_SCOPES, fillPath, initialValues, normalizeFields, parseRoute,
  resolveRoute, serializeValues, validateValues,
} from '../panelRoute';

describe('parseRoute', () => {
  it('splits a verb from a path', () => {
    expect(parseRoute('GET hosts/{host_id}')).toEqual({ method: 'GET', path: 'hosts/{host_id}' });
  });

  it('defaults to GET when no verb is given', () => {
    expect(parseRoute('hosts/1')).toEqual({ method: 'GET', path: 'hosts/1' });
  });

  it('uppercases the verb', () => {
    expect(parseRoute('put hosts/1').method).toBe('PUT');
  });

  it('returns null for an empty route', () => {
    expect(parseRoute('')).toBeNull();
    expect(parseRoute(undefined)).toBeNull();
  });
});

describe('fillPath', () => {
  it('fills host_id only in host scope', () => {
    expect(fillPath('hosts/{host_id}', { scope: 'host', scopeId: 7 })).toBe('hosts/7');
  });

  it('fills instance_id only in instance scope', () => {
    expect(fillPath('demos?instance_id={instance_id}', { scope: 'instance', scopeId: 3 }))
      .toBe('demos?instance_id=3');
  });

  it('does not fill host_id while in instance scope', () => {
    // Leaving it literal makes the backend reject it loudly. Substituting
    // the instance id here would silently address the wrong resource.
    expect(fillPath('hosts/{host_id}', { scope: 'instance', scopeId: 3 })).toBe('hosts/{host_id}');
  });

  it('leaves an unknown placeholder alone rather than writing undefined', () => {
    expect(fillPath('a/{nope}', { scope: 'host', scopeId: 1 })).toBe('a/{nope}');
  });

  it('fills scope_id in any scope', () => {
    expect(fillPath('x/{scope_id}', { scope: 'global', scopeId: 0 })).toBe('x/0');
  });
});

describe('resolveRoute', () => {
  it('parses and fills in one step', () => {
    expect(resolveRoute('PUT hosts/{host_id}', { scope: 'host', scopeId: 2 }))
      .toEqual({ method: 'PUT', path: 'hosts/2' });
  });

  it('returns null when there is no route', () => {
    expect(resolveRoute(null, {})).toBeNull();
  });
});

describe('MOUNT_SCOPES', () => {
  it('derives the scope from the mount point, not the manifest', () => {
    expect(MOUNT_SCOPES.host_menu).toBe('host');
    expect(MOUNT_SCOPES.instance_menu).toBe('instance');
    expect(MOUNT_SCOPES.instance_tabs).toBe('instance');
    expect(MOUNT_SCOPES.settings_section).toBe('global');
    expect(MOUNT_SCOPES.page).toBe('global');
  });
});

describe('normalizeFields', () => {
  it('drops entries with an unusable type instead of throwing', () => {
    const fields = normalizeFields([
      { key: 'ok', type: 'string' },
      { key: 'bad', type: 'hologram' },
      { key: '', type: 'string' },
      null,
    ]);
    expect(fields.map(f => f.key)).toEqual(['ok']);
  });

  it('falls back to the key when no label is given', () => {
    expect(normalizeFields([{ key: 'timeout_sec', type: 'number' }])[0].label).toBe('timeout_sec');
  });

  it('keeps numeric bounds only as numbers', () => {
    const [field] = normalizeFields([{ key: 'n', type: 'number', min: 1, max: '9' }]);
    expect(field.min).toBe(1);
    expect(field.max).toBeUndefined();
  });

  it('returns an empty list for a non-array', () => {
    expect(normalizeFields(undefined)).toEqual([]);
  });
});

describe('initialValues', () => {
  const fields = normalizeFields([
    { key: 's', type: 'string' },
    { key: 'n', type: 'number' },
    { key: 'b', type: 'bool' },
  ]);

  it('falls back per type when nothing is loaded', () => {
    expect(initialValues(fields, null)).toEqual({ s: '', n: 0, b: false });
  });

  it('takes loaded values when present', () => {
    expect(initialValues(fields, { s: 'x', n: 5, b: 1 })).toEqual({ s: 'x', n: 5, b: true });
  });

  it('ignores keys the field set does not declare', () => {
    expect(initialValues(fields, { gone: 'x' })).toEqual({ s: '', n: 0, b: false });
  });
});

describe('validateValues', () => {
  const fields = normalizeFields([{ key: 'n', type: 'number', min: 1, max: 30 }]);

  it('rejects below min', () => {
    expect(validateValues(fields, { n: 0 }).n).toMatch(/at least 1/);
  });

  it('rejects above max', () => {
    expect(validateValues(fields, { n: 99 }).n).toMatch(/at most 30/);
  });

  it('rejects a non-number', () => {
    expect(validateValues(fields, { n: 'soon' }).n).toMatch(/must be a number/i);
  });

  it('rejects an empty value', () => {
    expect(validateValues(fields, { n: '' }).n).toBeTruthy();
  });

  it('accepts a value inside the bounds', () => {
    expect(validateValues(fields, { n: 5 })).toEqual({});
  });
});

describe('serializeValues', () => {
  it('coerces each field to its declared type', () => {
    const fields = normalizeFields([
      { key: 'n', type: 'number' },
      { key: 'b', type: 'bool' },
      { key: 's', type: 'string' },
    ]);
    expect(serializeValues(fields, { n: '5', b: 1, s: undefined }))
      .toEqual({ n: 5, b: true, s: '' });
  });
});
