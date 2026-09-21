import React, { Suspense } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/addons', () => ({
  addonRequest: vi.fn(),
  addonDownload: vi.fn(),
  saveBlob: vi.fn(),
  getAddonState: vi.fn(),
  updateAddonState: vi.fn(),
}));

// The built-in modals reach the core API; stub it so a bundled addon panel
// that (wrongly) fell through to core would be visible as a failed assertion
// rather than a passing test.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), request: vi.fn() },
  listInstanceDemos: vi.fn(),
  downloadInstanceDemo: vi.fn(),
  downloadInstanceDemosBatch: vi.fn(),
}));

import { addonDownload, addonRequest } from '../../../services/addons';
import * as coreApi from '../../../services/api';
import {
  BUNDLED_ADDON_COMPONENTS, resolveBundledComponent, rendersOwnModal,
} from '../bundledPanels';

const INSTANCE = { id: 3, name: 'sD test server', port: 27960 };

beforeEach(() => vi.clearAllMocks());

// The bundled components are React.lazy, so every mount has to wait for a
// dynamic import. Under a full parallel run that can exceed the default 1s
// findBy timeout, so renders go through Suspense with a generous wait.
const LAZY_WAIT = { timeout: 15000 };
const renderLazy = (element) => render(<Suspense fallback={null}>{element}</Suspense>);

describe('resolveBundledComponent', () => {
  it('resolves a known component for a bundled addon', () => {
    const addon = { id: 'demo-management', source: 'bundled' };
    const entry = { component: 'bundled:demos-modal' };
    expect(resolveBundledComponent(addon, entry)).toBe(
      BUNDLED_ADDON_COMPONENTS['demo-management:demos-modal']);
  });

  it('refuses to hand a core component to an installed addon', () => {
    // An uploaded .zip must not be able to borrow core's build.
    const addon = { id: 'demo-management', source: 'installed' };
    expect(resolveBundledComponent(addon, { component: 'bundled:demos-modal' })).toBeNull();
  });

  it('returns null for an unknown component name', () => {
    const addon = { id: 'demo-management', source: 'bundled' };
    expect(resolveBundledComponent(addon, { component: 'bundled:nope' })).toBeNull();
  });

  it('ignores a plain file component', () => {
    const addon = { id: 'x', source: 'bundled' };
    expect(resolveBundledComponent(addon, { component: 'ui/panel.js' })).toBeNull();
  });

  it('detects the whole-dialog render mode', () => {
    expect(rendersOwnModal({ renders: 'modal' })).toBe(true);
    expect(rendersOwnModal({ renders: 'panel' })).toBe(false);
    expect(rendersOwnModal({})).toBe(false);
  });
});

describe('demo-management bundled modal', () => {
  const Modal = BUNDLED_ADDON_COMPONENTS['demo-management:demos-modal'];
  const DEMOS = [
    { name: 'a.dm_91', size: 4718592, mtime: 1757800000 },
    { name: 'b.packer.log', size: 691, mtime: 1757700000 },
  ];

  it('renders the same screen as the built-in one', async () => {
    addonRequest.mockResolvedValue({ demos: DEMOS, instance_name: 'sD test server' });
    renderLazy(<Modal isOpen onClose={() => {}} entity={INSTANCE} />);

    // The things the generic table panel did not have.
    expect(await screen.findByPlaceholderText(/filter by filename/i, {}, LAZY_WAIT)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /refresh/i })).toBeInTheDocument();
    expect(screen.getByText(/download selected/i)).toBeInTheDocument();
    expect(screen.getByText('a.dm_91')).toBeInTheDocument();
    expect(screen.getByText(/recorded/i)).toBeInTheDocument();
  });

  it('lists through the addon endpoint, not the core one', async () => {
    addonRequest.mockResolvedValue({ demos: DEMOS, instance_name: 'sD test server' });
    renderLazy(<Modal isOpen onClose={() => {}} entity={INSTANCE} />);

    await waitFor(() => expect(addonRequest).toHaveBeenCalledWith(
      'demo-management', 'GET', 'instances/3/demos'), LAZY_WAIT);
    expect(coreApi.listInstanceDemos).not.toHaveBeenCalled();
  });

  it('downloads one file through the addon endpoint', async () => {
    addonRequest.mockResolvedValue({ demos: DEMOS, instance_name: 'sD test server' });
    addonDownload.mockResolvedValue({ blob: new Blob(['x']), filename: 'a.dm_91' });
    renderLazy(<Modal isOpen onClose={() => {}} entity={INSTANCE} />);
    await screen.findByText('a.dm_91', {}, LAZY_WAIT);

    await userEvent.click(screen.getByRole('button', { name: 'Download a.dm_91' }));

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'demo-management', 'GET', 'instances/3/demos/download?filename=a.dm_91',
      expect.objectContaining({ fallbackName: 'a.dm_91' }),
    ));
    expect(coreApi.downloadInstanceDemo).not.toHaveBeenCalled();
  });

  it('downloads a selection through the addon endpoint', async () => {
    addonRequest.mockResolvedValue({ demos: DEMOS, instance_name: 'sD test server' });
    addonDownload.mockResolvedValue({ blob: new Blob(['x']), filename: 'demos.zip' });
    renderLazy(<Modal isOpen onClose={() => {}} entity={INSTANCE} />);
    await screen.findByText('a.dm_91', {}, LAZY_WAIT);

    await userEvent.click(screen.getByLabelText('Select a.dm_91'));
    await userEvent.click(screen.getByRole('button', { name: /download selected/i }));

    await waitFor(() => expect(addonDownload).toHaveBeenCalledWith(
      'demo-management', 'POST', 'instances/3/demos/download-batch',
      expect.objectContaining({ data: { filenames: ['a.dm_91'] } }),
    ));
    expect(coreApi.downloadInstanceDemosBatch).not.toHaveBeenCalled();
  });
});
