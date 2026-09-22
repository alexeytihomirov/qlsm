import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/addons', () => ({
  getAddonState: vi.fn(),
  updateAddonState: vi.fn(),
  addonRequest: vi.fn(),
}));

import { addonRequest, getAddonState, updateAddonState } from '../../../services/addons';
import AddonFormPanel from '../AddonFormPanel';

const ADDON = {
  id: 'sample-addon',
  settings_schema: {
    host: [
      { key: 'timeout_sec', type: 'number', label: 'Timeout (s)', default: 2, min: 1, max: 30 },
      { key: 'verbose', type: 'bool', label: 'Verbose' },
    ],
  },
};

beforeEach(() => vi.clearAllMocks());

// Submitting via the form's own submit event rather than clicking Save:
// jsdom's click-to-submit emulation is unreliable here, and what these tests
// are about is the panel's validate/serialize/report behaviour, not whether
// jsdom forwards a click. `saveButtonIsWired` covers the button itself once.
const submitPanel = (anyFieldInForm) => fireEvent.submit(anyFieldInForm.closest('form'));

describe('AddonFormPanel, managed mode', () => {
  const managed = () => render(
    <AddonFormPanel addon={ADDON} panel={{ kind: 'form' }} scope="host" scopeId={7} />,
  );

  it('reads values through core state when the panel declares no load route', async () => {
    getAddonState.mockResolvedValue({ settings: { timeout_sec: 9, verbose: true }, enabled: true, effective: true });
    managed();
    await waitFor(() => expect(screen.getByLabelText('Timeout (s)')).toHaveValue(9));
    expect(getAddonState).toHaveBeenCalledWith('sample-addon', 'host', 7);
  });

  it('renders the manifest defaults when nothing is stored', async () => {
    getAddonState.mockResolvedValue({ settings: {}, enabled: false, effective: false });
    managed();
    await waitFor(() => expect(screen.getByLabelText('Timeout (s)')).toHaveValue(2));
  });

  it('warns when this layer is on but a layer above blocks it', async () => {
    // The bug this prevents: operator ticks the box, save succeeds, nothing
    // happens, and the UI gives no hint why.
    getAddonState.mockResolvedValue({ settings: {}, enabled: true, effective: false });
    managed();
    expect(await screen.findByText(/still inactive/i)).toBeInTheDocument();
  });

  it('does not warn when the addon is effectively enabled', async () => {
    getAddonState.mockResolvedValue({ settings: {}, enabled: true, effective: true });
    managed();
    await waitFor(() => expect(getAddonState).toHaveBeenCalled());
    expect(screen.queryByText(/still inactive/i)).not.toBeInTheDocument();
  });

  it('blocks a save that violates a declared bound, without calling the API', async () => {
    getAddonState.mockResolvedValue({ settings: { timeout_sec: 2 }, enabled: false, effective: false });
    managed();
    const input = await screen.findByLabelText('Timeout (s)');
    // fireEvent.change rather than userEvent.type: typing several characters
    // into a controlled number input drops characters under jsdom, and what
    // is under test here is the validation rule, not keystroke emulation.
    fireEvent.change(input, { target: { value: '99' } });
    submitPanel(input);

    expect(await screen.findByText(/at most 30/i)).toBeInTheDocument();
    expect(updateAddonState).not.toHaveBeenCalled();
  });

  it('submits coerced values and the enable flag together', async () => {
    getAddonState.mockResolvedValue({ settings: { timeout_sec: 2 }, enabled: false, effective: false });
    updateAddonState.mockResolvedValue({ settings: { timeout_sec: 5 }, effective: false });
    managed();

    const input = await screen.findByLabelText('Timeout (s)');
    fireEvent.change(input, { target: { value: '5' } });
    await userEvent.click(screen.getByLabelText(/Enabled for this host/i));
    submitPanel(input);

    await waitFor(() => expect(updateAddonState).toHaveBeenCalledWith(
      'sample-addon', 'host', 7,
      { settings: { timeout_sec: 5, verbose: false }, enabled: true },
    ));
  });

  it('surfaces a backend rejection instead of claiming success', async () => {
    getAddonState.mockResolvedValue({ settings: {}, enabled: false, effective: false });
    updateAddonState.mockRejectedValue({ response: { data: { error: { message: 'nope' } } } });
    managed();
    submitPanel(await screen.findByLabelText('Timeout (s)'));
    expect(await screen.findByText('nope')).toBeInTheDocument();
    expect(screen.queryByText('Saved')).not.toBeInTheDocument();
  });

  it('wires Save as the form submit button', async () => {
    getAddonState.mockResolvedValue({ settings: {}, enabled: false, effective: false });
    managed();
    const input = await screen.findByLabelText('Timeout (s)');
    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toHaveAttribute('type', 'submit');
    expect(save.closest('form')).toBe(input.closest('form'));
  });

  it('offers a retry when loading fails', async () => {
    getAddonState.mockRejectedValue({ response: { data: { error: { message: 'down' } } } });
    managed();
    expect(await screen.findByText('down')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});

describe('AddonFormPanel, custom mode', () => {
  const PANEL = {
    kind: 'form',
    load: 'GET hosts/{host_id}',
    submit: 'PUT hosts/{host_id}',
    fields: [{ key: 'url', type: 'string', label: 'Stats hub URL' }],
  };

  it('loads from the addon own route with the scope filled in', async () => {
    addonRequest.mockResolvedValue({ url: 'https://hub.example' });
    render(<AddonFormPanel addon={ADDON} panel={PANEL} scope="host" scopeId={4} />);
    await waitFor(() => expect(screen.getByLabelText('Stats hub URL')).toHaveValue('https://hub.example'));
    expect(addonRequest).toHaveBeenCalledWith('sample-addon', 'GET', 'hosts/4');
  });

  it('submits to the submit route, not the load route', async () => {
    addonRequest.mockResolvedValue({ url: '' });
    render(<AddonFormPanel addon={ADDON} panel={PANEL} scope="host" scopeId={4} />);
    const field = await screen.findByLabelText('Stats hub URL');
    fireEvent.change(field, { target: { value: 'x' } });
    submitPanel(field);

    await waitFor(() => expect(addonRequest).toHaveBeenCalledWith(
      'sample-addon', 'PUT', 'hosts/4', { data: { url: 'x' } },
    ));
  });

  it('shows no enable toggle in custom mode', async () => {
    addonRequest.mockResolvedValue({ url: '' });
    render(<AddonFormPanel addon={ADDON} panel={PANEL} scope="host" scopeId={4} />);
    await screen.findByLabelText('Stats hub URL');
    expect(screen.queryByLabelText(/Enabled for this/i)).not.toBeInTheDocument();
  });
});
