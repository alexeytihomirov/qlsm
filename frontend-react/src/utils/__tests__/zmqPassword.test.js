import { describe, expect, it } from 'vitest';

import { validateZmqPassword } from '../zmqPassword';

describe('validateZmqPassword', () => {
  it('accepts a password using the generator alphabet', () => {
    expect(validateZmqPassword('Kp3-xR_9vT=2wQ', 'ZMQ Stats Password')).toBeNull();
  });

  it('accepts the boundary lengths', () => {
    expect(validateZmqPassword('a'.repeat(8), 'P')).toBeNull();
    expect(validateZmqPassword('a'.repeat(64), 'P')).toBeNull();
  });

  it('requires a value', () => {
    expect(validateZmqPassword('', 'ZMQ Stats Password')).toContain('is required');
    expect(validateZmqPassword('   ', 'ZMQ Stats Password')).toContain('is required');
    expect(validateZmqPassword(undefined, 'ZMQ Stats Password')).toContain('is required');
  });

  it('rejects a password that is too short or too long', () => {
    expect(validateZmqPassword('short1', 'P')).toContain('between 8 and 64');
    expect(validateZmqPassword('a'.repeat(65), 'P')).toContain('between 8 and 64');
  });

  it.each(['p@ssw0rdxx', 'has spaces1', 'quote"pass1', 'dollar$sign', 'hash#pass01'])(
    'rejects disallowed characters in %s',
    (value) => {
      expect(validateZmqPassword(value, 'P')).toContain('may only contain');
    },
  );

  it('ignores surrounding whitespace when validating', () => {
    expect(validateZmqPassword('  Kp3-xR_9vT=2wQ  ', 'P')).toBeNull();
  });
});
