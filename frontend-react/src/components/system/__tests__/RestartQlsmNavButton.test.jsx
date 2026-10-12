import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import AddonsContext from '../../../contexts/AddonsContext';
import RestartQlsmNavButton from '../RestartQlsmNavButton';

const mocks = vi.hoisted(() => ({
  getSystemInfo: vi.fn(),
  requestRestart: vi.fn(),
  waitForRestart: vi.fn(),
}));

vi.mock('../../../services/system', () => ({
  getSystemInfo: mocks.getSystemInfo,
  requestRestart: mocks.requestRestart,
  waitForRestart: mocks.waitForRestart,
}));

vi.mock('../../NotificationProvider', () => ({
  useNotification: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

function renderWith(addons) {
  return render(
    <MemoryRouter>
      <AddonsContext.Provider value={{ addons, loading: false, error: null, reload: () => {}, mounts: () => [] }}>
        <RestartQlsmNavButton />
      </AddonsContext.Provider>
    </MemoryRouter>,
  );
}

describe('RestartQlsmNavButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getSystemInfo.mockResolvedValue({ restart_supported: true, boot_id: 'a' });
  });

  it('renders nothing while no addon is waiting for a restart', () => {
    renderWith([{ id: 'a', pending_restart: false }]);
    expect(screen.queryByText(/restart/i)).not.toBeInTheDocument();
    expect(mocks.getSystemInfo).not.toHaveBeenCalled();
  });

  it('offers the restart, behind a confirmation, while an addon is pending', async () => {
    mocks.requestRestart.mockResolvedValue({});
    mocks.waitForRestart.mockResolvedValue(false);
    renderWith([{ id: 'a', pending_restart: false }, { id: 'b', pending_restart: true }]);

    fireEvent.click(await screen.findByRole('button', { name: /restart qlsm/i }));
    expect(mocks.requestRestart).not.toHaveBeenCalled();

    expect(await screen.findByRole('heading', { name: 'Restart QLSM?' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restart' }));
    await waitFor(() => expect(mocks.requestRestart).toHaveBeenCalledTimes(1));
  });

  it('points at the Addons page where a restart is not survivable', async () => {
    mocks.getSystemInfo.mockResolvedValue({ restart_supported: false });
    renderWith([{ id: 'b', pending_restart: true }]);

    const link = await screen.findByRole('link', { name: /restart required/i });
    expect(link).toHaveAttribute('href', '/addons');
    expect(screen.queryByRole('button', { name: /restart qlsm/i })).not.toBeInTheDocument();
  });
});
