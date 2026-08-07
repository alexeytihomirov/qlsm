import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import BackupRestorePage from '../BackupRestorePage';

const mocks = vi.hoisted(() => ({
  exportBackup: vi.fn(),
  importBackup: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  exportBackup: mocks.exportBackup,
  importBackup: mocks.importBackup,
}));

vi.mock('../../components/NotificationProvider', () => ({
  useNotification: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

describe('BackupRestorePage export', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.exportBackup.mockResolvedValue({ blob: new Blob(['x']), filename: 'qlsm-backup-test.qlsmbak' });
    window.URL.createObjectURL = vi.fn(() => 'blob:mock-url');
    window.URL.revokeObjectURL = vi.fn();
  });

  it('exports directly when a password is entered', async () => {
    render(<BackupRestorePage />);
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'secret123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'secret123' } });
    fireEvent.click(screen.getByRole('button', { name: /export backup/i }));

    await waitFor(() => {
      expect(mocks.exportBackup).toHaveBeenCalledWith('secret123');
    });
  });

  it('requires the risk checkbox before exporting with no password', async () => {
    render(<BackupRestorePage />);
    const exportButton = screen.getByRole('button', { name: /export backup/i });
    fireEvent.click(exportButton);

    // Risk modal appears; export must not have been called yet.
    expect(await screen.findByText(/i understand the risk/i)).toBeInTheDocument();
    expect(mocks.exportBackup).not.toHaveBeenCalled();

    const checkbox = screen.getByRole('checkbox', { name: /i understand the risk/i });
    const confirmButton = screen.getByRole('button', { name: /continue/i });
    expect(confirmButton).toBeDisabled();

    fireEvent.click(checkbox);
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mocks.exportBackup).toHaveBeenCalledWith(null);
    });
  });

  it('rejects mismatched password confirmation without calling the API', async () => {
    render(<BackupRestorePage />);
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'secret123' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'different' } });
    fireEvent.click(screen.getByRole('button', { name: /export backup/i }));

    await waitFor(() => {
      expect(mocks.showError).toHaveBeenCalled();
    });
    expect(mocks.exportBackup).not.toHaveBeenCalled();
  });
});
