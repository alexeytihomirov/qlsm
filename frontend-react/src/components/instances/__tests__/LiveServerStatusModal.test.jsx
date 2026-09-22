import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import LiveServerStatusModal from '../LiveServerStatusModal';

vi.mock('../../../hooks/useWorkshopPreview', () => ({
    useWorkshopPreview: vi.fn(),
}));
vi.mock('../../../services/addons', async () => {
    const actual = await vi.importActual('../../../services/addons');
    return { ...actual, listAddons: vi.fn().mockResolvedValue([]), addonRequest: vi.fn() };
});
vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: true }) }));

import { useWorkshopPreview } from '../../../hooks/useWorkshopPreview';
import { listAddons, addonRequest } from '../../../services/addons';
import { AddonsProvider } from '../../../contexts/AddonsContext';

const baseInstance = { id: 1, name: 'test-server', port: 27960 };
const baseStatus = {
    map: 'campgrounds',
    gametype: 'ca',
    factory: 'clanarena',
    state: 'in_progress',
    match_start_time: null,
    players: [],
    maxplayers: 16,
    red_score: 0,
    blue_score: 0,
    workshop_item_id: null,
};

describe('LiveServerStatusModal map preview', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        useWorkshopPreview.mockReturnValue({ previewUrl: null, loading: false });
        listAddons.mockResolvedValue([]);
    });

    it('renders a static preview image for a known standard map', () => {
        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'campgrounds' }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        expect(img.src).toContain('map-previews/standard/campgrounds.webp');
    });

    it('renders a static preview image by map filename for non-listed standard maps', () => {
        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'asylum', workshop_item_id: null }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        expect(img.src).toContain('map-previews/standard/asylum.webp');
    });

    it('prefers static standard preview even when workshop preview is available', () => {
        const workshopUrl = 'https://steamcdn.example.com/workshop_preview.jpg';
        useWorkshopPreview.mockReturnValue({ previewUrl: workshopUrl, loading: false });

        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'campgrounds', workshop_item_id: '2358556636' }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        expect(img.src).toContain('map-previews/standard/campgrounds.webp');
    });

    it('renders workshop preview when map is not a standard map and hook returns URL', () => {
        const workshopUrl = 'https://steamcdn.example.com/workshop_preview.jpg';
        useWorkshopPreview.mockReturnValue({ previewUrl: workshopUrl, loading: false });

        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'some_workshop_map', workshop_item_id: '2358556636' }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        expect(img.src).toBe(workshopUrl);
    });

    it('keeps previous preview while workshop preview is loading for new map', () => {
        useWorkshopPreview.mockReturnValue({ previewUrl: null, loading: false });

        const { rerender } = render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'campgrounds', workshop_item_id: null }}
            />
        );

        const firstImage = screen.getByRole('img', { name: /map preview/i });
        expect(firstImage.src).toContain('map-previews/standard/campgrounds.webp');

        useWorkshopPreview.mockReturnValue({ previewUrl: null, loading: true });
        rerender(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'some_workshop_map', workshop_item_id: '2358556636' }}
            />
        );

        const loadingImage = screen.getByRole('img', { name: /map preview/i });
        expect(loadingImage.src).toContain('map-previews/standard/campgrounds.webp');
    });

    it('falls back to placeholder when unknown map static preview is missing', () => {
        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'obscure_map', workshop_item_id: null }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        expect(img.src).toContain('map-previews/standard/obscure_map.webp');
        fireEvent.error(img);
        expect(img.src).toContain('map-previews/defaultmap.webp');
    });

    it('falls back to placeholder when image load fails', () => {
        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'campgrounds' }}
            />
        );

        const img = screen.getByRole('img', { name: /map preview/i });
        fireEvent.error(img);
        expect(img.src).toContain('map-previews/defaultmap.webp');
    });

    it('map name text remains visible', () => {
        render(
            <LiveServerStatusModal
                isOpen={true}
                onClose={() => {}}
                instance={baseInstance}
                serverStatus={{ ...baseStatus, map: 'campgrounds' }}
            />
        );

        expect(screen.getByText('campgrounds')).toBeInTheDocument();
    });
});

describe('LiveServerStatusModal addon-contributed player columns', () => {
    const RATING_ADDON = {
        id: 'player-ranks', name: 'Player Ranks', version: '1.0.0',
        loaded: true, ui_mountable: true, enabled: true,
        ui: {
            live_status_columns: [
                { id: 'rating', label: 'Rating', align: 'right', route: 'GET instances/{instance_id}/ranks' },
            ],
        },
    };

    beforeEach(() => {
        vi.clearAllMocks();
        useWorkshopPreview.mockReturnValue({ previewUrl: null, loading: false });
    });

    it('renders a configured column with per-player data', async () => {
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            data: { '76561197993968023': { display: '2181', title: 'duel, 13732 games' } },
            configured: true,
        });

        render(
            <AddonsProvider>
                <LiveServerStatusModal
                    isOpen={true}
                    onClose={() => {}}
                    instance={baseInstance}
                    serverStatus={{
                        ...baseStatus,
                        players: [{ name: 'Player1', steam: '76561197993968023', team: 'free' }],
                    }}
                />
            </AddonsProvider>
        );

        expect(await screen.findByText('Rating')).toBeInTheDocument();
        expect(await screen.findByText('2181')).toBeInTheDocument();
    });

    it('does not render a column the addon reports as unconfigured', async () => {
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({ data: {}, configured: false });

        render(
            <AddonsProvider>
                <LiveServerStatusModal
                    isOpen={true}
                    onClose={() => {}}
                    instance={baseInstance}
                    serverStatus={{
                        ...baseStatus,
                        players: [{ name: 'Player1', steam: '76561197993968023', team: 'free' }],
                    }}
                />
            </AddonsProvider>
        );

        await waitFor(() => expect(addonRequest).toHaveBeenCalled());
        expect(screen.queryByText('Rating')).not.toBeInTheDocument();
    });
});
