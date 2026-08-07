import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import InstanceBasicInfoForm from '../InstanceBasicInfoForm';

// Headless UI v2 Listbox doesn't open under (user-)click in JSDOM (see the
// identical note in PresetLoadTab.test.jsx), so the mock renders the options
// inline unconditionally and threads value/onChange/disabled through a real
// React context -- close enough to the real Listbox contract to exercise
// selection and the disabled state, which is what these tests need.
vi.mock('@headlessui/react', async () => {
  const React = await import('react');
  const ListboxCtx = React.createContext({ value: undefined, onChange: () => {}, disabled: false });

  const Listbox = ({ value, onChange, disabled, children }) => (
    <ListboxCtx.Provider value={{ value, onChange, disabled }}>
      {children({ open: true })}
    </ListboxCtx.Provider>
  );
  Listbox.Label = ({ children, ...props }) => <label {...props}>{children}</label>;
  function ListboxButton({ children, ...props }) {
    const { disabled } = React.useContext(ListboxCtx);
    return <button type="button" disabled={disabled} {...props}>{children}</button>;
  }
  Listbox.Button = ListboxButton;
  Listbox.Options = ({ children, ...props }) => <div role="listbox" {...props}>{children}</div>;
  function ListboxOption({ children, className, value }) {
    const { value: selectedValue, onChange, disabled } = React.useContext(ListboxCtx);
    const optionState = { selected: selectedValue === value, active: false };
    const resolvedClassName = typeof className === 'function' ? className(optionState) : className;
    return (
      <div
        role="option"
        className={resolvedClassName}
        onClick={() => { if (!disabled) onChange(value); }}
      >
        {children(optionState)}
      </div>
    );
  }
  Listbox.Option = ListboxOption;
  const Transition = ({ children, show }) => (show === false ? null : <>{children}</>);

  return { Listbox, Transition };
});

// InfoTooltip is deliberately left un-mocked (unlike other suites in this
// repo) because these tests need to see its real markup -- a `span` with
// `cursor-help` wrapping a lucide `Info` icon -- to verify the "used DB"
// flag actually renders. `@floating-ui/react-dom` is mocked to static values
// (same shape as InstanceActionsMenu.test.jsx) purely so the positioning
// hook doesn't need real layout in JSDOM; the tooltip bubble itself never
// mounts in these tests since nothing hovers.
vi.mock('@floating-ui/react-dom', () => ({
  autoUpdate: vi.fn(),
  flip: vi.fn(() => ({ name: 'flip' })),
  offset: vi.fn(() => ({ name: 'offset' })),
  shift: vi.fn(() => ({ name: 'shift' })),
  arrow: vi.fn(() => ({ name: 'arrow' })),
  useFloating: () => ({
    x: 0,
    y: 0,
    strategy: 'absolute',
    placement: 'top',
    middlewareData: {},
    refs: {
      setFloating: vi.fn(),
      setReference: vi.fn(),
    },
  }),
}));

const baseProps = {
  name: '',
  onNameChange: vi.fn(),
  selectedHostId: '2',
  onHostChange: vi.fn(),
  hosts: [{ id: 2, name: 'ubu-host', provider: 'self-hosted', ip_address: '203.0.113.10' }],
  port: '',
  onPortChange: vi.fn(),
  availablePorts: [],
  loadingPorts: false,
  hostname: '',
  onHostnameChange: vi.fn(),
  lanRateEnabled: false,
  onLanRateChange: vi.fn(),
};

// Scopes queries to the Redis DB field's own subtree (label + button +
// options), so assertions can't accidentally match the Host Server or Port
// listboxes that sit next to it in the same grid row.
function getRedisDbField() {
  return screen.getByText('Redis DB').closest('div');
}

describe('InstanceBasicInfoForm - Redis DB dropdown', () => {
  it('renders the label and shows the current value on the button', () => {
    render(
      <InstanceBasicInfoForm
        {...baseProps}
        redisDb={2}
        onRedisDbChange={vi.fn()}
        redisDbOptions={[
          { db: 1, inUse: false, instanceName: null },
          { db: 2, inUse: false, instanceName: null },
        ]}
      />
    );

    const field = getRedisDbField();
    expect(within(field).getByText('Redis DB')).toBeInTheDocument();
    const button = within(field).getByRole('button');
    expect(button).toHaveTextContent('2');
  });

  it('disables the listbox when no host is selected, and enables it once one is', () => {
    const { rerender } = render(
      <InstanceBasicInfoForm
        {...baseProps}
        selectedHostId=""
        redisDb={1}
        onRedisDbChange={vi.fn()}
        redisDbOptions={[{ db: 1, inUse: false, instanceName: null }]}
      />
    );
    expect(within(getRedisDbField()).getByRole('button')).toBeDisabled();

    rerender(
      <InstanceBasicInfoForm
        {...baseProps}
        selectedHostId="2"
        redisDb={1}
        onRedisDbChange={vi.fn()}
        redisDbOptions={[{ db: 1, inUse: false, instanceName: null }]}
      />
    );
    expect(within(getRedisDbField()).getByRole('button')).not.toBeDisabled();
  });

  it('lists exactly as many options as redisDbOptions provides, with the right numbers', () => {
    const options = [
      { db: 1, inUse: true, instanceName: 'Duel #1' },
      { db: 2, inUse: false, instanceName: null },
      { db: 3, inUse: true, instanceName: 'FFA' },
    ];
    render(
      <InstanceBasicInfoForm
        {...baseProps}
        redisDb={2}
        onRedisDbChange={vi.fn()}
        redisDbOptions={options}
      />
    );

    const rows = within(getRedisDbField()).getAllByRole('option');
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.textContent.trim().charAt(0))).toEqual(['1', '2', '3']);
  });

  it('shows the InfoTooltip trigger only on occupied options', () => {
    const options = [
      { db: 1, inUse: true, instanceName: 'Duel #1' },
      { db: 2, inUse: false, instanceName: null },
    ];
    render(
      <InstanceBasicInfoForm
        {...baseProps}
        redisDb={2}
        onRedisDbChange={vi.fn()}
        redisDbOptions={options}
      />
    );

    const rows = within(getRedisDbField()).getAllByRole('option');
    // Selector used: the tooltip's hover-trigger `span.cursor-help`, which
    // wraps a lucide-react `Info` icon rendered as `svg.lucide-info`. Both
    // are checked; neither requires simulating hover since we only assert
    // the trigger is present, not the (hover-only) tooltip bubble text.
    expect(rows[0].querySelector('.cursor-help')).not.toBeNull();
    expect(rows[0].querySelector('svg.lucide-info')).not.toBeNull();
    expect(rows[1].querySelector('.cursor-help')).toBeNull();
    expect(rows[1].querySelector('svg.lucide-info')).toBeNull();
  });

  it('keeps an occupied DB selectable -- clicking it still calls onRedisDbChange with that DB', async () => {
    const user = userEvent.setup();
    const onRedisDbChange = vi.fn();
    const options = [
      { db: 1, inUse: true, instanceName: 'Duel #1' },
      { db: 2, inUse: false, instanceName: null },
    ];
    render(
      <InstanceBasicInfoForm
        {...baseProps}
        redisDb={2}
        onRedisDbChange={onRedisDbChange}
        redisDbOptions={options}
      />
    );

    const rows = within(getRedisDbField()).getAllByRole('option');
    await user.click(rows[0]);

    expect(onRedisDbChange).toHaveBeenCalledTimes(1);
    expect(onRedisDbChange).toHaveBeenCalledWith(1);
  });
});
