import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as addonUi from '../uiKit';

// The reference addon's own component, exactly as an addon author would
// write it: a tier-2 bundle that reads React and the UI kit off
// window.__qlsm rather than importing them. Real end-to-end coverage of the
// contract described in addons/README.md ("UI, tier 2"), not a mock of it.
import Panel from '../../../../../addons/_examples/ui-kit-test-addon/ui/Panel';

describe('ui-kit-test-addon reference Panel', () => {
  beforeEach(() => {
    window.__qlsm = { react: React, ui: addonUi, version: 1 };
  });

  afterEach(() => {
    delete window.__qlsm;
  });

  it('renders its fields and buttons using the shared UI kit', () => {
    render(<Panel ctx={{ addonId: 'ui-kit-test-addon' }} />);

    expect(screen.getByText('UI Kit Test Addon')).toBeInTheDocument();
    expect(screen.getByLabelText('Sample text')).toBeInTheDocument();
    expect(screen.getByLabelText('Sample choice')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open modal' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Secondary' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Danger' })).toBeInTheDocument();
  });

  it('opens the generic Modal on demand', () => {
    render(<Panel ctx={{ addonId: 'ui-kit-test-addon' }} />);

    expect(screen.queryByText('Generic modal')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open modal' }));
    expect(screen.getByText('Generic modal')).toBeInTheDocument();
  });
});
