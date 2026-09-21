import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/addons', () => ({
  addonRequest: vi.fn(),
  addonDownload: vi.fn(),
  saveBlob: vi.fn(),
}));

import { addonDownload, addonRequest, saveBlob } from '../../../services/addons';
import AddonTablePanel from '../AddonTablePanel';

const ADDON = { id: 'file-lister' };

// A table panel of the shape the tier-1 contract documents: a file list
// with per-row and bulk downloads.
const PANEL = {
  kind: 'table',
  load: 'GET instances/{instance_id}/demos',
  rows: 'demos',
  row_key: 'name',
  selectable: true,
  selection_key: 'filenames',
  empty: 'No demo files on this server yet.',
  columns: [
    { key: 'name', label: 'File' },
    { key: 'size', label: 'Size', format: 'bytes', align: 'right' },
    { key: 'mtime', label: 'Recorded', format: 'datetime', align: 'right' },
  ],
  row_actions: [
    { id: 'download', label: 'Download', route: 'GET instances/{instance_id}/demos/download?filename={name}', download: true },
  ],
  bulk_actions: [
    { id: 'download-batch', label: 'Download selected as ZIP', route: 'POST instances/{instance_id}/demos/download-batch', download: true },
  ],
};

const ROWS = [
  { name: 'a.dm_91', size: 4718592, mtime: 1757800000 },
  { name: 'b.dm_91', size: 1024, mtime: 1757700000 },
];

const renderPanel = () =>
  render(<AddonTablePanel addon={ADDON} panel={PANEL} scope="instance" scopeId={7} />);

beforeEach(() => {
  vi.clearAllMocks();
  addonRequest.mockResolvedValue({ demos: ROWS });
  addonDownload.mockResolvedValue({ blob: new Blob(['x']), filename: 'a.dm_91' });
});

describe('AddonTablePanel', () => {
  it('loads rows from the declared key with the scope filled in', async () => {
    renderPanel();
    expect(await screen.findByText('a.dm_91')).toBeInTheDocument();
    expect(addonRequest).toHaveBeenCalledWith('file-lister', 'GET', 'instances/7/demos');
  });

  it('formats sizes and dates rather than dumping raw numbers', async () => {
    renderPanel();
    expect(await screen.findByText('4.5 MB')).toBeInTheDocument();
    expect(screen.getByText('1 KB')).toBeInTheDocument();
    expect(screen.queryByText('4718592')).not.toBeInTheDocument();
  });

  it('shows the declared empty message when there is nothing', async () => {
    addonRequest.mockResolvedValue({ demos: [] });
    renderPanel();
    expect(await screen.findByText(/No demo files/)).toBeInTheDocument();
  });

  it('offers a retry when loading fails', async () => {
    addonRequest.mockRejectedValue({ response: { data: { error: { message: 'ssh down' } } } });
    renderPanel();
    expect(await screen.findByText('ssh down')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('substitutes the row value into a row action route', async () => {
    renderPanel();
    await screen.findByText('a.dm_91');
    await userEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'file-lister', 'GET', 'instances/7/demos/download?filename=a.dm_91',
      expect.objectContaining({ fallbackName: 'a.dm_91' }),
    ));
  });

  it('url-encodes a row value so a space cannot break the query string', async () => {
    addonRequest.mockResolvedValue({ demos: [{ name: 'my demo.dm_91', size: 1, mtime: 1 }] });
    renderPanel();
    await screen.findByText('my demo.dm_91');
    await userEvent.click(screen.getByRole('button', { name: 'Download' }));

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'file-lister', 'GET',
      'instances/7/demos/download?filename=my%20demo.dm_91',
      expect.anything(),
    ));
  });

  it('saves the downloaded blob under the name the server returned', async () => {
    const blob = new Blob(['bytes']);
    addonDownload.mockResolvedValue({ blob, filename: 'server-chosen.dm_91' });
    renderPanel();
    await screen.findByText('a.dm_91');
    await userEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);

    await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(blob, 'server-chosen.dm_91'));
  });

  it('posts the selection under the declared selection_key', async () => {
    renderPanel();
    await screen.findByText('a.dm_91');
    await userEvent.click(screen.getByLabelText('Select a.dm_91'));
    await userEvent.click(screen.getByRole('button', { name: /Download selected/ }));

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'file-lister', 'POST', 'instances/7/demos/download-batch',
      expect.objectContaining({ data: { filenames: ['a.dm_91'] } }),
    ));
  });

  it('keeps the bulk action disabled until something is selected', async () => {
    renderPanel();
    await screen.findByText('a.dm_91');
    expect(screen.getByRole('button', { name: /Download selected/ })).toBeDisabled();
  });

  it('select-all covers every row', async () => {
    renderPanel();
    await screen.findByText('a.dm_91');
    await userEvent.click(screen.getByLabelText('Select all'));
    await userEvent.click(screen.getByRole('button', { name: /Download selected/ }));

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'file-lister', 'POST', 'instances/7/demos/download-batch',
      expect.objectContaining({ data: { filenames: ['a.dm_91', 'b.dm_91'] } }),
    ));
  });

  it('surfaces a download failure message instead of failing silently', async () => {
    addonDownload.mockRejectedValue(new Error('Demo file not found on the remote host.'));
    renderPanel();
    await screen.findByText('a.dm_91');
    await userEvent.click(screen.getAllByRole('button', { name: 'Download' })[0]);

    expect(await screen.findByText('Demo file not found on the remote host.')).toBeInTheDocument();
    expect(saveBlob).not.toHaveBeenCalled();
  });

  it('renders no selection UI when the panel declares no bulk actions', async () => {
    render(<AddonTablePanel addon={ADDON} panel={{ ...PANEL, bulk_actions: [] }}
                            scope="instance" scopeId={7} />);
    await screen.findByText('a.dm_91');
    expect(screen.queryByLabelText('Select all')).not.toBeInTheDocument();
  });
});
