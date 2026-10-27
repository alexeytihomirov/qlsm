import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import BulkActionsModal from '../BulkActionsModal';

const mocks = vi.hoisted(() => ({
  checkPluginUpdates: vi.fn(),
  applyPluginUpdates: vi.fn(),
  checkAllPresetPluginUpdates: vi.fn(),
  applyPresetPluginUpdates: vi.fn(),
  getDeferRestartsSetting: vi.fn(),
}));

vi.mock('../../../services/api', () => mocks);

const hosts = [
  { id: 1, name: 'alpha', status: 'ACTIVE' },
  { id: 2, name: 'bravo', status: 'ACTIVE' },
  { id: 3, name: 'charlie', status: 'PROVISIONING' },
];

const hostCheck = (instId, file) => ({
  data: {
    common_pool_changes: [],
    common_pool_error: null,
    instances: [
      { id: instId, name: `inst${instId}`, port: 27960, status: 'running', selected_plugin_changes: [{ name: file, change: 'modified' }] },
    ],
  },
});

const presets = [
  {
    preset_id: 7, name: 'duel', runtime: 'minqlx',
    plugin_changes: [{ name: 'a.py', change: 'modified' }, { name: 'b.py', change: 'modified' }],
    plugins: [{ name: 'a.py', status: 'outdated' }, { name: 'b.py', status: 'outdated' }],
  },
];

const renderModal = () => render(<BulkActionsModal isOpen onClose={() => {}} hosts={hosts} />);

describe('BulkPluginUpdatesTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getDeferRestartsSetting.mockResolvedValue({ enabled: false });
    mocks.checkAllPresetPluginUpdates.mockResolvedValue(presets);
    mocks.applyPluginUpdates.mockResolvedValue({ message: 'queued' });
    mocks.applyPresetPluginUpdates.mockResolvedValue({ message: 'ok', data: {} });
  });

  it('lists hosts and presets with their outdated files', async () => {
    mocks.checkPluginUpdates.mockImplementation(async (id) => (id === 1 ? hostCheck(11, 'x.py') : hostCheck(22, 'y.py')));
    renderModal();

    expect(await screen.findByText('x.py')).toBeTruthy();
    expect(screen.getByText('y.py')).toBeTruthy();
    expect(screen.getByText('a.py')).toBeTruthy();
    expect(screen.getByText('b.py')).toBeTruthy();
    expect(screen.getByText('alpha')).toBeTruthy();
    expect(screen.getByText('duel')).toBeTruthy();
    // Not ACTIVE: listed with the reason, never checked.
    expect(screen.getByText(/PROVISIONING/)).toBeTruthy();
    expect(mocks.checkPluginUpdates).toHaveBeenCalledTimes(2);
    expect(mocks.checkPluginUpdates).not.toHaveBeenCalledWith(3);
  });

  it('a host whose check fails shows the reason and the rest stay selectable', async () => {
    mocks.checkPluginUpdates.mockImplementation(async (id) => {
      if (id === 1) throw { error: { message: 'SSH unreachable' } };
      return hostCheck(22, 'y.py');
    });
    renderModal();

    expect(await screen.findByText('SSH unreachable')).toBeTruthy();
    expect(await screen.findByText('y.py')).toBeTruthy();
    const box = screen.getByLabelText(/y\.py/);
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(box.checked).toBe(false);
  });

  it('apply sends one request per host and per preset with only the ticked files', async () => {
    mocks.checkPluginUpdates.mockImplementation(async (id) => (id === 1 ? hostCheck(11, 'x.py') : hostCheck(22, 'y.py')));
    renderModal();
    await screen.findByText('y.py');

    fireEvent.click(screen.getByLabelText(/^b\.py/));
    fireEvent.click(screen.getByRole('button', { name: /update selected/i }));

    await waitFor(() => expect(mocks.applyPresetPluginUpdates).toHaveBeenCalledTimes(1));
    expect(mocks.applyPresetPluginUpdates).toHaveBeenCalledWith(7, { files: ['a.py'] });
    expect(mocks.applyPluginUpdates).toHaveBeenCalledTimes(2);
    expect(mocks.applyPluginUpdates).toHaveBeenCalledWith(1, {
      update_common_pool: false,
      instances: { 11: ['x.py'] },
      restart_instances: [11],
    });
    expect(mocks.applyPluginUpdates).toHaveBeenCalledWith(2, {
      update_common_pool: false,
      instances: { 22: ['y.py'] },
      restart_instances: [22],
    });
  });

  it('a 409 on one host is shown on its row and the others report queued', async () => {
    mocks.checkPluginUpdates.mockImplementation(async (id) => (id === 1 ? hostCheck(11, 'x.py') : hostCheck(22, 'y.py')));
    mocks.applyPluginUpdates.mockImplementation(async (id) => {
      if (id === 1) throw { error: { message: 'Host is busy with another task' } };
      return { message: 'queued' };
    });
    renderModal();
    await screen.findByText('y.py');

    fireEvent.click(screen.getByRole('button', { name: /update selected/i }));

    expect(await screen.findByText('Host is busy with another task')).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText('queued').length).toBeGreaterThanOrEqual(1));
    expect(screen.getByTestId('apply-result-host-2').textContent).toBe('queued');
  });
});
