import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import SettingsPage from '../SettingsPage';

const mocks = vi.hoisted(() => ({
  getApiKey: vi.fn(),
  regenerateApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  getVultrKeySetting: vi.fn(),
  setVultrKeySetting: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  getApiKey: mocks.getApiKey,
  regenerateApiKey: mocks.regenerateApiKey,
  revokeApiKey: mocks.revokeApiKey,
  getVultrKeySetting: mocks.getVultrKeySetting,
  setVultrKeySetting: mocks.setVultrKeySetting,
}));

vi.mock('../../components/NotificationProvider', () => ({
  useNotification: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

describe('SettingsPage Vultr key field', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getApiKey.mockResolvedValue(null);
    mocks.getVultrKeySetting.mockResolvedValue({ key: null });
    mocks.setVultrKeySetting.mockResolvedValue({ key: 'new-vultr-key' });
  });

  it('saves the Vultr key and shows a success notification', async () => {
    render(<SettingsPage />);
    const input = await screen.findByLabelText(/vultr api key/i);
    fireEvent.change(input, { target: { value: 'new-vultr-key' } });
    fireEvent.click(screen.getByRole('button', { name: /save vultr key/i }));

    await waitFor(() => {
      expect(mocks.setVultrKeySetting).toHaveBeenCalledWith('new-vultr-key');
      expect(mocks.showSuccess).toHaveBeenCalled();
    });
  });
});
