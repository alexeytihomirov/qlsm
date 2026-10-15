import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Menu } from '@headlessui/react';

vi.mock('../../../services/addons', () => ({
  addonRequest: vi.fn(),
}));

let mockMounts = [];
vi.mock('../../../contexts/AddonsContext', () => ({
  useAddonMounts: () => mockMounts,
}));

// The modal pulls in the panel stack; a stub is enough to see it open.
vi.mock('../AddonModal', () => ({
  default: ({ isOpen, mount }) => (isOpen ? <div data-testid="modal">{mount?.label} open</div> : null),
}));

import { addonRequest } from '../../../services/addons';
import { useAddonMenu } from '../AddonMenuSection';

const mount = (key, entry = {}) => ({
  key,
  label: `Entry ${key}`,
  icon: undefined,
  scope: 'instance',
  addon: { id: 'demo-stream' },
  entry: { id: key, panel: 'p', ...entry },
});

function Harness() {
  const addonMenu = useAddonMenu('instance_menu', { id: 7 });
  return (
    <>
      {addonMenu.modal}
      <Menu>
        <Menu.Button>Actions</Menu.Button>
        <Menu.Items>{addonMenu.items(() => {})}</Menu.Items>
      </Menu>
    </>
  );
}

const openMenu = () => userEvent.click(screen.getByText('Actions'));

beforeEach(() => {
  vi.clearAllMocks();
  mockMounts = [];
});

describe('addon menu entry status', () => {
  it('renders the label and a green dot when the status is ok', async () => {
    mockMounts = [mount('a', { status: 'GET instances/{instance_id}/status' })];
    addonRequest.mockResolvedValue({ ok: true, label: 'Streaming, delay 5 s' });
    render(<Harness />);
    await openMenu();

    const label = await screen.findByText('Streaming, delay 5 s');
    expect(label).toHaveAttribute('title', 'Streaming, delay 5 s');
    expect(addonRequest).toHaveBeenCalledWith('demo-stream', 'GET', 'instances/7/status');
    expect(screen.getByTestId('addon-menu-status-dot')).toHaveClass('bg-emerald-400');
  });

  it('renders a grey dot when ok is false', async () => {
    mockMounts = [mount('a', { status: 'GET s' })];
    addonRequest.mockResolvedValue({ ok: false, label: 'Not ready' });
    render(<Harness />);
    await openMenu();

    await screen.findByText('Not ready');
    const dot = screen.getByTestId('addon-menu-status-dot');
    expect(dot).not.toHaveClass('bg-emerald-400');
    expect(dot).toHaveClass('bg-gray-400');
  });

  it.each([
    ['rejects', () => addonRequest.mockRejectedValue(new Error('down'))],
    ['returns null', () => addonRequest.mockResolvedValue(null)],
    ['returns no label', () => addonRequest.mockResolvedValue({ ok: true })],
    ['returns a non-boolean ok', () => addonRequest.mockResolvedValue({ ok: 'yes', label: 'x' })],
  ])('shows nothing extra when the fetch %s, and the entry still opens', async (_name, arrange) => {
    mockMounts = [mount('a', { status: 'GET s' })];
    arrange();
    render(<Harness />);
    await openMenu();

    const entry = await screen.findByText('Entry a');
    await waitFor(() => expect(addonRequest).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByTestId('addon-menu-status-dot')).toBeNull();

    await userEvent.click(entry);
    expect(await screen.findByTestId('modal')).toHaveTextContent('Entry a open');
  });

  it('does not fetch for an entry without status', async () => {
    mockMounts = [mount('a')];
    render(<Harness />);
    await openMenu();

    await screen.findByText('Entry a');
    expect(addonRequest).not.toHaveBeenCalled();
    expect(screen.queryByTestId('addon-menu-status-dot')).toBeNull();
  });

  it('fetches again when the menu is re-opened', async () => {
    mockMounts = [mount('a', { status: 'GET s' })];
    addonRequest.mockResolvedValue({ ok: true, label: 'Up' });
    render(<Harness />);
    await openMenu();
    await screen.findByText('Up');
    expect(addonRequest).toHaveBeenCalledTimes(1);

    await openMenu(); // close
    await waitFor(() => expect(screen.queryByText('Entry a')).toBeNull());
    await openMenu(); // open again
    await screen.findByText('Up');
    expect(addonRequest).toHaveBeenCalledTimes(2);
  });
});
