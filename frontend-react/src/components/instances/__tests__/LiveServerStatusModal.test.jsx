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

    it('stacks multiple sources inside one cell when the response carries entries', async () => {
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            data: {
                '76561197993968023': {
                    entries: [
                        { display: '1357', title: 'duel, 310 games', icon_url: 'logos/qlstats.svg' },
                        { display: '1387', title: 'Skilled', icon_url: 'logos/slipgate.svg' },
                    ],
                },
            },
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

        expect(await screen.findByText('1357')).toBeInTheDocument();
        expect(screen.getByText('1387')).toBeInTheDocument();
    });

    it('tints a value with the palette color the addon names, and ignores any other', async () => {
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            data: {
                '76561197993968023': {
                    entries: [
                        { display: 'Gold III', color: 'yellow' },
                        { display: '1387', color: 'text-red-500' },
                    ],
                },
            },
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

        expect(await screen.findByText('Gold III')).toHaveClass('dark:text-[#ffff44]');
        expect(screen.getByText('1387')).not.toHaveClass('text-red-500');
    });

    it('keeps a multi-word value on one line and widens the drawer to fit the column', async () => {
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            data: { '76561197993968023': { entries: [{ display: 'Platinum IV', color: 'cyan' }] } },
            configured: true,
        });

        const { container } = render(
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

        // Before the addon answers there is no column, so the drawer keeps its normal width.
        expect(container.ownerDocument.querySelector('.drawer-panel')).toHaveClass('w-[500px]');
        const value = await screen.findByText('Platinum IV');
        expect(value.closest('td')).toHaveClass('whitespace-nowrap');
        expect(container.ownerDocument.querySelector('.drawer-panel')).toHaveClass('w-[630px]');
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

    it('survives a malformed cell instead of taking the drawer down', async () => {
        // `entries: [null]` used to reach JSX and throw "Cannot read
        // properties of null (reading 'title')", which unmounted the whole
        // Live Status drawer -- addon-driven content renders inside a
        // component core owns here, so a bad payload must stay a bad cell.
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            configured: true,
            data: {
                '76561197993968023': { entries: [null, { display: '1357' }] },
                '76561197960287930': 'not an object at all',
            },
        });

        render(
            <AddonsProvider>
                <LiveServerStatusModal
                    isOpen={true}
                    onClose={() => {}}
                    instance={baseInstance}
                    serverStatus={{
                        ...baseStatus,
                        players: [
                            { name: 'Player1', steam: '76561197993968023', team: 'free' },
                            { name: 'Player2', steam: '76561197960287930', team: 'free' },
                        ],
                    }}
                />
            </AddonsProvider>
        );

        expect(await screen.findByText('1357')).toBeInTheDocument();
        // the table as a whole is still there, with both rows
        expect(screen.getByText('Player1')).toBeInTheDocument();
        expect(screen.getByText('Player2')).toBeInTheDocument();
    });

    it('looks a player up under the same key the hook asked about', async () => {
        // The hook skips an empty `steam` and falls through to `steamid`; the
        // table used to do the same with `||` but the hook used `??`, so a
        // player with steam: '' was requested under no key and read under
        // another, and the cell stayed a dash forever.
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            data: { '76561197993968023': { display: '2181' } },
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
                        players: [{ name: 'Player1', steam: '', steamid: '76561197993968023', team: 'free' }],
                    }}
                />
            </AddonsProvider>
        );

        expect(await screen.findByText('2181')).toBeInTheDocument();
    });

    it('does not turn an escaping icon_url from the response into a request', async () => {
        // icon_url inside a cell comes from the addon's own JSON response, so
        // the manifest validator never sees it. The browser collapses dot
        // segments, so rendering it unchecked made
        // <img src="/api/addons/x/ui/../../../hosts/1/x"> a credentialed
        // same-origin GET on a core endpoint, once per player per poll.
        listAddons.mockResolvedValue([RATING_ADDON]);
        addonRequest.mockResolvedValue({
            configured: true,
            data: {
                '76561197993968023': {
                    entries: [{ display: '1357', icon_url: '../../../hosts/1/x' }],
                },
            },
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

        expect(await screen.findByText('1357')).toBeInTheDocument();
        const addonImages = screen.queryAllByRole('img')
            .filter((img) => img.getAttribute('src')?.includes('/api/addons/'));
        expect(addonImages).toEqual([]);
    });
});
