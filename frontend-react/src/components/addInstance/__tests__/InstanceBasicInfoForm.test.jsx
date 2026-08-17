import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import InstanceBasicInfoForm from '../InstanceBasicInfoForm';

vi.mock('@headlessui/react', () => {
  const Listbox = ({ children }) => <div>{children({ open: false })}</div>;
  Listbox.Label = ({ children, ...props }) => <label {...props}>{children}</label>;
  Listbox.Button = ({ children, ...props }) => <button type="button" {...props}>{children}</button>;
  Listbox.Options = ({ children, ...props }) => <div {...props}>{children}</div>;
  Listbox.Option = ({ children, className }) => {
    const optionState = { selected: false, active: false };
    const resolvedClassName = typeof className === 'function'
      ? className(optionState)
      : className;

    return <div className={resolvedClassName}>{children(optionState)}</div>;
  };
  const Transition = ({ children }) => <>{children}</>;

  return { Listbox, Transition };
});

vi.mock('../../common/InfoTooltip', () => ({
  default: ({ text }) => <span data-testid="lan-rate-tooltip">{text}</span>,
}));

describe('InstanceBasicInfoForm', () => {
  it('renders the instance name field and the host selector', () => {
    render(
      <InstanceBasicInfoForm
        name="my-server"
        onNameChange={vi.fn()}
        selectedHostId="2"
        onHostChange={vi.fn()}
        hosts={[{ id: 2, name: 'ubu-host', provider: 'self-hosted', ip_address: '203.0.113.10' }]}
        port=""
        onPortChange={vi.fn()}
        availablePorts={[]}
        loadingPorts={false}
        hostname=""
        onHostnameChange={vi.fn()}
      />
    );

    expect(screen.getByDisplayValue('my-server')).toBeInTheDocument();
    // The mocked Transition always renders Listbox.Options regardless of
    // open state, so the host name appears both in the selected-value
    // display and in the options list -- assert on the first match.
    expect(screen.getAllByText('ubu-host')[0]).toBeInTheDocument();
  });
});
