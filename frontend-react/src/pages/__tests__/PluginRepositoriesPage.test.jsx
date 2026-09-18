import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PluginRepositoriesPage from '../PluginRepositoriesPage';

const mocks = vi.hoisted(() => ({
  getPluginRepositories: vi.fn(),
  createPluginRepository: vi.fn(),
  syncPluginRepository: vi.fn(),
  deletePluginRepository: vi.fn(),
  downloadPluginRepositoryPlugins: vi.fn(),
  getPluginRepositoryDiff: vi.fn(),
  installPluginRepositoryAddon: vi.fn(),
  getPluginRepositoryUpdates: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  getPluginRepositories: mocks.getPluginRepositories,
  createPluginRepository: mocks.createPluginRepository,
  syncPluginRepository: mocks.syncPluginRepository,
  deletePluginRepository: mocks.deletePluginRepository,
  downloadPluginRepositoryPlugins: mocks.downloadPluginRepositoryPlugins,
  getPluginRepositoryDiff: mocks.getPluginRepositoryDiff,
  installPluginRepositoryAddon: mocks.installPluginRepositoryAddon,
  getPluginRepositoryUpdates: mocks.getPluginRepositoryUpdates,
}));

vi.mock('../../components/NotificationProvider', () => ({
  useNotification: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

const REPO = {
  id: 1,
  name: 'Repo A',
  url: 'https://example.com/repo',
  last_synced_at: '2026-09-14T00:00:00Z',
  last_sync_error: null,
  plugins: [
    {
      filename: 'balance2.py', label: 'Balance', description: null,
      runtime: 'minqlx', requires_qlsm_version: null, version_risk: null,
    },
  ],
};

async function openAndCheckFirstPlugin() {
  render(<PluginRepositoriesPage />);
  fireEvent.click(await screen.findByText('Repo A'));
  const checkbox = await screen.findByRole('checkbox');
  fireEvent.click(checkbox);
}

describe('PluginRepositoriesPage downloads', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getPluginRepositories.mockResolvedValue([REPO]);
    mocks.getPluginRepositoryUpdates.mockResolvedValue([]);
    // Default resolution so a future Diff-click test fails on its own
    // assertion rather than on an unhandled rejection from the modal's fetch.
    mocks.getPluginRepositoryDiff.mockResolvedValue({ local: '', remote: '' });
  });

  it('shows a success toast on a clean download', async () => {
    mocks.downloadPluginRepositoryPlugins.mockResolvedValueOnce({ downloaded: ['balance2.py'], errors: [] });

    await openAndCheckFirstPlugin();
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    await waitFor(() => {
      expect(mocks.showSuccess).toHaveBeenCalledWith(expect.stringContaining('Downloaded 1'));
    });
  });

  it('offers an overwrite confirm when the backend reports code=exists, and retries with overwrite on confirm', async () => {
    mocks.downloadPluginRepositoryPlugins
      .mockRejectedValueOnce({
        downloaded: [], errors: [{ filename: 'balance2.py', error: 'already exists', code: 'exists' }],
      })
      .mockResolvedValueOnce({ downloaded: ['balance2.py'], errors: [] });

    await openAndCheckFirstPlugin();
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    expect(await screen.findByText(/overwrite existing plugins/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /overwrite selected/i }));

    await waitFor(() => {
      expect(mocks.downloadPluginRepositoryPlugins).toHaveBeenLastCalledWith(1, ['balance2.py'], {}, true);
    });
    await waitFor(() => {
      expect(mocks.showSuccess).toHaveBeenCalledWith(expect.stringContaining('Downloaded 1'));
    });
  });

  it('keeps the overwrite confirm mounted when only some of the selection was already in the pool', async () => {
    // A 207: one file landed, one was already there. Both branches of
    // reportResult fire -- it raises the confirm AND reports a download, which
    // refreshes the list. The confirm is card-local state, so a refresh that
    // swaps every card for the loading spinner would unmount it unseen.
    const twoPlugins = {
      ...REPO,
      plugins: [
        ...REPO.plugins,
        {
          filename: 'extra.py', label: 'Extra', description: null,
          runtime: 'minqlx', requires_qlsm_version: null, version_risk: null,
        },
      ],
    };
    // Latency so the refresh is genuinely in flight while the confirm renders.
    mocks.getPluginRepositories.mockImplementation(
      () => new Promise(resolve => { setTimeout(() => resolve([twoPlugins]), 60); }),
    );
    mocks.downloadPluginRepositoryPlugins.mockResolvedValueOnce({
      downloaded: ['balance2.py'],
      errors: [{ filename: 'extra.py', error: 'already exists', code: 'exists' }],
    });

    render(<PluginRepositoriesPage />);
    fireEvent.click(await screen.findByText('Repo A'));
    (await screen.findAllByRole('checkbox')).forEach(box => fireEvent.click(box));
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    expect(await screen.findByText(/overwrite existing plugins/i)).toBeInTheDocument();
    // Still there once the refresh has settled, rather than flashing away.
    await new Promise(resolve => { setTimeout(resolve, 120); });
    expect(screen.getByText(/overwrite existing plugins/i)).toBeInTheDocument();
  });

  it('overwrites only the files left ticked in the prompt', async () => {
    const twoPlugins = {
      ...REPO,
      plugins: [
        ...REPO.plugins,
        {
          filename: 'extra.py', label: 'Extra', description: null,
          runtime: 'minqlx', requires_qlsm_version: null, version_risk: null,
        },
      ],
    };
    mocks.getPluginRepositories.mockResolvedValue([twoPlugins]);
    mocks.downloadPluginRepositoryPlugins
      .mockRejectedValueOnce({
        downloaded: [],
        errors: [
          { filename: 'balance2.py', error: 'already exists', code: 'exists' },
          { filename: 'extra.py', error: 'already exists', code: 'exists' },
        ],
      })
      .mockResolvedValueOnce({ downloaded: ['extra.py'], errors: [] });

    render(<PluginRepositoriesPage />);
    fireEvent.click(await screen.findByText('Repo A'));
    (await screen.findAllByRole('checkbox')).forEach(box => fireEvent.click(box));
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    fireEvent.click(await screen.findByRole('checkbox', { name: 'balance2.py' }));
    fireEvent.click(screen.getByRole('button', { name: /overwrite selected/i }));

    await waitFor(() => {
      expect(mocks.downloadPluginRepositoryPlugins).toHaveBeenLastCalledWith(1, ['extra.py'], {}, true);
    });
    // The downloaded file is cleared from the list selection; the one left
    // unticked in the prompt stays selected, the same as after Cancel.
    await waitFor(() => {
      expect(screen.queryByText(/overwrite existing plugins/i)).not.toBeInTheDocument();
    });
    // Rows are matched by their rendered label text ('Balance'/'Extra'), not
    // filename -- the card renders `plugin.label || plugin.filename`, and
    // this fixture sets a label.
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes.find(box => box.closest('tr')?.textContent.includes('Balance'))).toBeChecked();
    expect(boxes.find(box => box.closest('tr')?.textContent.includes('Extra'))).not.toBeChecked();
  });

  it('cancel in the overwrite prompt keeps the selection and does not download again', async () => {
    mocks.downloadPluginRepositoryPlugins.mockRejectedValueOnce({
      downloaded: [], errors: [{ filename: 'balance2.py', error: 'already exists', code: 'exists' }],
    });

    await openAndCheckFirstPlugin();
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    expect(await screen.findByText(/overwrite existing plugins/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    await waitFor(() => {
      expect(screen.queryByText(/overwrite existing plugins/i)).not.toBeInTheDocument();
    });
    expect(mocks.downloadPluginRepositoryPlugins).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('shows the per-file reason instead of a generic message when every plugin fails for a non-exists error', async () => {
    mocks.downloadPluginRepositoryPlugins.mockRejectedValueOnce({
      downloaded: [], errors: [{ filename: 'balance2.py', error: 'boom', code: null }],
    });

    await openAndCheckFirstPlugin();
    fireEvent.click(screen.getByRole('button', { name: /download selected/i }));

    await waitFor(() => {
      expect(mocks.showError).toHaveBeenCalledWith(expect.stringContaining('balance2.py: boom'));
    });
    expect(mocks.showError).not.toHaveBeenCalledWith('Failed to download plugins.');
  });

  it('asks for a runtime only on a selected plugin that declares none, and sends it per file', async () => {
    mocks.getPluginRepositories.mockResolvedValue([{
      ...REPO,
      plugins: [
        ...REPO.plugins,
        {
          filename: 'no_runtime.py', label: 'No Runtime', description: null,
          runtime: null, requires_qlsm_version: null, version_risk: null,
        },
      ],
    }]);
    mocks.downloadPluginRepositoryPlugins.mockResolvedValueOnce({ downloaded: ['balance2.py', 'no_runtime.py'], errors: [] });

    render(<PluginRepositoriesPage />);
    fireEvent.click(await screen.findByText('Repo A'));
    const [balanceBox, noRuntimeBox] = await screen.findAllByRole('checkbox');

    fireEvent.click(balanceBox);
    // Every runtime-less row carries a picker regardless of selection; what is
    // gated is whether an unresolved runtime blocks the download.
    expect(screen.queryByText(/pick a runtime for/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /download selected/i })).not.toBeDisabled();

    fireEvent.click(noRuntimeBox);
    const download = screen.getByRole('button', { name: /download selected/i });
    expect(download).toBeDisabled();
    expect(screen.getByText(/pick a runtime for no_runtime\.py/i)).toBeInTheDocument();

    // RuntimePicker is a Headless UI Listbox: a button trigger plus portalled
    // options, not a <select>. It opens on userEvent, not fireEvent.click.
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Runtime for no_runtime.py' }));
    await user.click(await screen.findByRole('option', { name: 'minqlxtended' }));
    await waitFor(() => expect(download).not.toBeDisabled());
    fireEvent.click(download);

    await waitFor(() => {
      expect(mocks.downloadPluginRepositoryPlugins).toHaveBeenCalledWith(
        1, ['balance2.py', 'no_runtime.py'], { 'no_runtime.py': 'minqlxtended' }, false,
      );
    });
  });
});
