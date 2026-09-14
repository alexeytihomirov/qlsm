import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PluginRepositoriesPage from '../PluginRepositoriesPage';

const mocks = vi.hoisted(() => ({
  getPluginRepositories: vi.fn(),
  createPluginRepository: vi.fn(),
  syncPluginRepository: vi.fn(),
  deletePluginRepository: vi.fn(),
  downloadPluginRepositoryPlugins: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  getPluginRepositories: mocks.getPluginRepositories,
  createPluginRepository: mocks.createPluginRepository,
  syncPluginRepository: mocks.syncPluginRepository,
  deletePluginRepository: mocks.deletePluginRepository,
  downloadPluginRepositoryPlugins: mocks.downloadPluginRepositoryPlugins,
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
    fireEvent.click(screen.getByRole('button', { name: /^overwrite$/i }));

    await waitFor(() => {
      expect(mocks.downloadPluginRepositoryPlugins).toHaveBeenLastCalledWith(1, ['balance2.py'], null, true);
    });
    await waitFor(() => {
      expect(mocks.showSuccess).toHaveBeenCalledWith(expect.stringContaining('Downloaded 1'));
    });
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
});
