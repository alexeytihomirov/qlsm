import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// The component moved into addons/demo-management/ when demo management
// stopped being part of QLSM core, and it no longer has a default data
// source: the addon that owns it supplies one. So this passes `api` directly
// instead of mocking core's services/api, which no longer has these
// functions at all.
const mocks = vi.hoisted(() => ({
    listInstanceDemos: vi.fn(),
    downloadInstanceDemo: vi.fn(),
    downloadInstanceDemosBatch: vi.fn(),
    runAction: vi.fn(),
}));

const api = {
    list: (...a) => mocks.listInstanceDemos(...a),
    downloadOne: (...a) => mocks.downloadInstanceDemo(...a),
    downloadBatch: (...a) => mocks.downloadInstanceDemosBatch(...a),
    runAction: (...a) => mocks.runAction(...a),
};

vi.mock('@headlessui/react', () => {
    const Dialog = ({ open, children }) => (open ? <div role="dialog">{children}</div> : null);
    Dialog.Panel = ({ children }) => <div>{children}</div>;
    Dialog.Title = ({ children }) => <div>{children}</div>;
    const DialogBackdrop = () => <div />;
    return { Dialog, DialogBackdrop };
});

import ViewDemosModal from '../../../../../addons/demo-management/ui/ViewDemosModal';

const DEMOS = [
    { name: 'match1_map1_p0_alice.dm_91', size: 1024, mtime: 2000 },
    { name: 'match2_map2_p1_bob.dm_91', size: 2048, mtime: 1000 },
];

describe('ViewDemosModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.listInstanceDemos.mockResolvedValue({ demos: DEMOS, instance_name: 'test-inst' });
        mocks.downloadInstanceDemo.mockResolvedValue(new Blob(['x']));
        mocks.downloadInstanceDemosBatch.mockResolvedValue(new Blob(['zip']));
        mocks.runAction.mockResolvedValue({});
        window.URL.createObjectURL = vi.fn(() => 'blob:mock-url');
        window.URL.revokeObjectURL = vi.fn();
    });

    const instance = { id: 1, name: 'test-inst', port: 27960 };

    it('lists demos returned by the API', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);

        await waitFor(() => expect(mocks.listInstanceDemos).toHaveBeenCalledWith(1));
        expect(await screen.findByText('match1_map1_p0_alice.dm_91')).toBeInTheDocument();
        expect(screen.getByText('match2_map2_p1_bob.dm_91')).toBeInTheDocument();
    });

    it('filters rows by filename substring', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.change(screen.getByPlaceholderText('Filter by filename...'), {
            target: { value: 'bob' },
        });

        expect(screen.queryByText('match1_map1_p0_alice.dm_91')).not.toBeInTheDocument();
        expect(screen.getByText('match2_map2_p1_bob.dm_91')).toBeInTheDocument();
    });

    it('selecting a row enables the batch download button with the right count', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        const batchButton = screen.getByRole('button', { name: /download selected/i });
        expect(batchButton).toBeDisabled();

        fireEvent.click(screen.getByLabelText('Select match1_map1_p0_alice.dm_91'));

        expect(batchButton).not.toBeDisabled();
        expect(screen.getByRole('button', { name: /download selected \(1\)/i })).toBeInTheDocument();
    });

    it('"select all" only selects currently filtered rows', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.change(screen.getByPlaceholderText('Filter by filename...'), {
            target: { value: 'bob' },
        });
        fireEvent.click(screen.getByLabelText('Select all demos'));

        fireEvent.click(screen.getByRole('button', { name: /download selected/i }));
        await waitFor(() => expect(mocks.downloadInstanceDemosBatch).toHaveBeenCalledWith(
            1, ['match2_map2_p1_bob.dm_91'],
        ));
    });

    it('clicking a row download button downloads only that file', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.click(screen.getByLabelText('Download match1_map1_p0_alice.dm_91'));

        await waitFor(() => expect(mocks.downloadInstanceDemo).toHaveBeenCalledWith(
            1, 'match1_map1_p0_alice.dm_91',
        ));
        expect(mocks.downloadInstanceDemosBatch).not.toHaveBeenCalled();
    });

    it('shows an error message when batch download fails without crashing', async () => {
        mocks.downloadInstanceDemosBatch.mockRejectedValueOnce({ error: { message: 'boom' } });
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.click(screen.getByLabelText('Select match1_map1_p0_alice.dm_91'));
        fireEvent.click(screen.getByRole('button', { name: /download selected \(1\)/i }));

        expect(await screen.findByText('boom')).toBeInTheDocument();
    });

    describe('match groups (contributed by another addon)', () => {
        const GROUPED_DEMOS = [
            { name: 'pack.qlmatch', size: 100, mtime: 3000 },
            { name: 'm1_aerowalk.replay.json.gz', size: 10, mtime: 3000 },
            { name: 'standalone.dm_91', size: 1, mtime: 1000 },
        ];
        const GROUP = {
            group_id: 'm1',
            label: 'aerowalk — m1',
            addon_id: 'qlmatch-packer',
            member_names: ['pack.qlmatch', 'm1_aerowalk.replay.json.gz'],
            qlmatch_name: 'pack.qlmatch',
            actions: [
                {
                    id: 'qlmatch-packer.rebuild-sidecar',
                    label: 'Rebuild sidecar',
                    icon: 'refresh-cw',
                    action: {
                        route: 'instances/{instance_id}/matches/pack.qlmatch/rebuild-sidecar',
                        method: 'POST',
                        confirm: 'Regenerate the replay sidecar from the existing pack?',
                    },
                    bulk: {
                        route: 'instances/{instance_id}/matches/rebuild-sidecar-batch',
                        method: 'POST',
                        selection_key: 'filenames',
                    },
                },
            ],
        };

        beforeEach(() => {
            mocks.listInstanceDemos.mockResolvedValue({
                demos: GROUPED_DEMOS, matches: [GROUP], instance_name: 'test-inst',
            });
        });

        it('clusters a match pack with its sidecar under one label instead of two flat rows', async () => {
            render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);

            expect(await screen.findByText('aerowalk — m1')).toBeInTheDocument();
            expect(screen.getByText('pack.qlmatch')).toBeInTheDocument();
            expect(screen.getByText('m1_aerowalk.replay.json.gz')).toBeInTheDocument();
            expect(screen.getByText('standalone.dm_91')).toBeInTheDocument();
        });

        it('running a row action confirms, resolves {instance_id}, and posts to the contributing addon', async () => {
            window.confirm = vi.fn(() => true);
            render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
            await screen.findByText('aerowalk — m1');

            fireEvent.click(screen.getByLabelText('Rebuild sidecar for aerowalk — m1'));

            await waitFor(() => expect(mocks.runAction).toHaveBeenCalledWith(
                'qlmatch-packer', 'POST', 'instances/1/matches/pack.qlmatch/rebuild-sidecar',
            ));
            expect(window.confirm).toHaveBeenCalledWith('Regenerate the replay sidecar from the existing pack?');
        });

        it('does not call the action when the confirm dialog is declined', async () => {
            window.confirm = vi.fn(() => false);
            render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
            await screen.findByText('aerowalk — m1');

            fireEvent.click(screen.getByLabelText('Rebuild sidecar for aerowalk — m1'));

            await waitFor(() => expect(window.confirm).toHaveBeenCalled());
            expect(mocks.runAction).not.toHaveBeenCalled();
        });

        it('selecting a match group offers a bulk action that posts every selected qlmatch filename', async () => {
            window.confirm = vi.fn(() => true);
            render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
            await screen.findByText('aerowalk — m1');

            fireEvent.click(screen.getByLabelText('Select match aerowalk — m1'));
            fireEvent.click(screen.getByRole('button', { name: /rebuild sidecar \(1\)/i }));

            await waitFor(() => expect(mocks.runAction).toHaveBeenCalledWith(
                'qlmatch-packer', 'POST', 'instances/1/matches/rebuild-sidecar-batch',
                { filenames: ['pack.qlmatch'] },
            ));
        });

        it('shows an error without crashing when a match action fails', async () => {
            window.confirm = vi.fn(() => true);
            mocks.runAction.mockRejectedValueOnce({ error: { message: 'ssh failed' } });
            render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} api={api} />);
            await screen.findByText('aerowalk — m1');

            fireEvent.click(screen.getByLabelText('Rebuild sidecar for aerowalk — m1'));

            expect(await screen.findByText('ssh failed')).toBeInTheDocument();
        });
    });
});
