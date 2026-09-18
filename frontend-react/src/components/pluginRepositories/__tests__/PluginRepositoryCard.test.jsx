import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import PluginRepositoryCard from '../PluginRepositoryCard';

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock('../../NotificationProvider', () => ({
  useNotification: () => ({ showSuccess, showError }),
}));

const downloadPluginRepositoryPlugins = vi.fn();
const installPluginRepositoryAddon = vi.fn();
vi.mock('../../../services/api', () => ({
  downloadPluginRepositoryPlugins: (...args) => downloadPluginRepositoryPlugins(...args),
  installPluginRepositoryAddon: (...args) => installPluginRepositoryAddon(...args),
}));

const repo = {
  id: 7,
  name: 'Repo',
  url: 'https://example.com',
  last_synced_at: null,
  plugins: [{ filename: 'afkplus.py', label: 'AFK Plus', runtime: 'minqlx' }],
};

async function downloadAfkplus() {
  render(<PluginRepositoryCard repo={repo} onSync={vi.fn()} onDelete={vi.fn()} syncing={false} />);
  fireEvent.click(screen.getByRole('button', { name: /1 plugin/i }));
  fireEvent.click(screen.getByRole('checkbox', { name: /afk plus|afkplus/i }));
  fireEvent.click(screen.getByRole('button', { name: /^download/i }));
  await waitFor(() => expect(downloadPluginRepositoryPlugins).toHaveBeenCalled());
}

describe('PluginRepositoryCard download feedback', () => {
  beforeEach(() => vi.clearAllMocks());

  it('names the hosts the pool is being pushed to', async () => {
    downloadPluginRepositoryPlugins.mockResolvedValue({
      downloaded: ['afkplus.py'], errors: [],
      push: { queued: [{ id: 1, name: 'alpha' }, { id: 2, name: 'beta' }], skipped: [] },
    });
    await downloadAfkplus();
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith('Downloaded 1 plugin(s). Pushing to alpha, beta.'));
    expect(showError).not.toHaveBeenCalled();
  });

  it('says so when no active host could take the push', async () => {
    downloadPluginRepositoryPlugins.mockResolvedValue({
      downloaded: ['afkplus.py'], errors: [], push: { queued: [], skipped: [] },
    });
    await downloadAfkplus();
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith('Downloaded 1 plugin(s). No active host to push to.'));
  });

  it('warns about skipped hosts with their reason', async () => {
    downloadPluginRepositoryPlugins.mockResolvedValue({
      downloaded: ['afkplus.py'], errors: [],
      push: { queued: [{ id: 1, name: 'alpha' }], skipped: [{ id: 2, name: 'beta', reason: 'busy' }] },
    });
    await downloadAfkplus();
    await waitFor(() => expect(showError).toHaveBeenCalledWith(
      'Not pushed to beta (busy). Run Check for Updates on those hosts later.',
    ));
  });
});

describe('PluginRepositoryCard plugin list', () => {
  it('shows the filename next to the friendly name', () => {
    render(<PluginRepositoryCard repo={repo} onSync={vi.fn()} onDelete={vi.fn()} syncing={false} />);
    fireEvent.click(screen.getByRole('button', { name: /1 plugin/i }));
    expect(screen.getByText('AFK Plus')).toBeInTheDocument();
    expect(screen.getByText('afkplus.py')).toBeInTheDocument();
  });
});

const repoWithAddon = {
  ...repo,
  addons: [{
    id: 'demo-addon', zip: 'demo-addon.zip', label: 'Demo Addon', description: null,
    version: '1.2.0', sha256: null, requires_qlsm_version: null, version_risk: null,
  }],
};

describe('PluginRepositoryCard addons', () => {
  beforeEach(() => vi.clearAllMocks());

  it('installs an addon and reports the backend message', async () => {
    installPluginRepositoryAddon.mockResolvedValue({
      data: { id: 'demo-addon', pending_restart: true },
      message: '"Demo Addon" installed. Restart QLSM to activate it.',
    });
    const onDownloaded = vi.fn();
    render(<PluginRepositoryCard
      repo={repoWithAddon} onSync={vi.fn()} onDelete={vi.fn()} syncing={false}
      onDownloaded={onDownloaded}
    />);
    fireEvent.click(screen.getByRole('button', { name: /1 plugin.*1 addon/i }));
    fireEvent.click(screen.getByRole('button', { name: /install/i }));

    await waitFor(() => expect(installPluginRepositoryAddon).toHaveBeenCalledWith(7, 'demo-addon'));
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith(expect.stringContaining('Restart QLSM')));
    expect(onDownloaded).toHaveBeenCalled();
  });

  it('labels the button Update and shows badges when the repo has a newer version', () => {
    const updates = {
      plugins: { 'afkplus.py': 'up_to_date' },
      addons: { 'demo-addon': { id: 'demo-addon', status: 'update_available', installed_version: '1.0.0', available_version: '1.2.0' } },
    };
    render(<PluginRepositoryCard
      repo={repoWithAddon} updates={updates} onSync={vi.fn()} onDelete={vi.fn()} syncing={false}
    />);
    fireEvent.click(screen.getByRole('button', { name: /1 plugin.*1 addon/i }));

    expect(screen.getByRole('button', { name: /update/i })).toBeInTheDocument();
    expect(screen.getByText('Update available')).toBeInTheDocument();
    expect(screen.getByText('Up to date')).toBeInTheDocument();
    expect(screen.getByText(/installed: 1\.0\.0/)).toBeInTheDocument();
  });

  it('shows the install error on failure', async () => {
    installPluginRepositoryAddon.mockRejectedValue({ error: { message: 'sha256 mismatch' } });
    render(<PluginRepositoryCard
      repo={repoWithAddon} onSync={vi.fn()} onDelete={vi.fn()} syncing={false}
    />);
    fireEvent.click(screen.getByRole('button', { name: /1 plugin.*1 addon/i }));
    fireEvent.click(screen.getByRole('button', { name: /install/i }));

    await waitFor(() => expect(showError).toHaveBeenCalledWith('sha256 mismatch'));
  });
});
