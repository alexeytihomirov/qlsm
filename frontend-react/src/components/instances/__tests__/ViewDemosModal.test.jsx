import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
    listInstanceDemos: vi.fn(),
    downloadInstanceDemo: vi.fn(),
    downloadInstanceDemosBatch: vi.fn(),
}));

vi.mock('../../../services/api', () => ({
    listInstanceDemos: mocks.listInstanceDemos,
    downloadInstanceDemo: mocks.downloadInstanceDemo,
    downloadInstanceDemosBatch: mocks.downloadInstanceDemosBatch,
}));

vi.mock('@headlessui/react', () => {
    const Dialog = ({ open, children }) => (open ? <div role="dialog">{children}</div> : null);
    Dialog.Panel = ({ children }) => <div>{children}</div>;
    Dialog.Title = ({ children }) => <div>{children}</div>;
    const DialogBackdrop = () => <div />;
    return { Dialog, DialogBackdrop };
});

import ViewDemosModal from '../ViewDemosModal';

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
        window.URL.createObjectURL = vi.fn(() => 'blob:mock-url');
        window.URL.revokeObjectURL = vi.fn();
    });

    const instance = { id: 1, name: 'test-inst', port: 27960 };

    it('lists demos returned by the API', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);

        await waitFor(() => expect(mocks.listInstanceDemos).toHaveBeenCalledWith(1));
        expect(await screen.findByText('match1_map1_p0_alice.dm_91')).toBeInTheDocument();
        expect(screen.getByText('match2_map2_p1_bob.dm_91')).toBeInTheDocument();
    });

    it('filters rows by filename substring', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.change(screen.getByPlaceholderText('Filter by filename...'), {
            target: { value: 'bob' },
        });

        expect(screen.queryByText('match1_map1_p0_alice.dm_91')).not.toBeInTheDocument();
        expect(screen.getByText('match2_map2_p1_bob.dm_91')).toBeInTheDocument();
    });

    it('selecting a row enables the batch download button with the right count', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        const batchButton = screen.getByRole('button', { name: /download selected/i });
        expect(batchButton).toBeDisabled();

        fireEvent.click(screen.getByLabelText('Select match1_map1_p0_alice.dm_91'));

        expect(batchButton).not.toBeDisabled();
        expect(screen.getByRole('button', { name: /download selected \(1\)/i })).toBeInTheDocument();
    });

    it('"select all" only selects currently filtered rows', async () => {
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);
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
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.click(screen.getByLabelText('Download match1_map1_p0_alice.dm_91'));

        await waitFor(() => expect(mocks.downloadInstanceDemo).toHaveBeenCalledWith(
            1, 'match1_map1_p0_alice.dm_91',
        ));
        expect(mocks.downloadInstanceDemosBatch).not.toHaveBeenCalled();
    });

    it('shows an error message when batch download fails without crashing', async () => {
        mocks.downloadInstanceDemosBatch.mockRejectedValueOnce({ error: { message: 'boom' } });
        render(<ViewDemosModal isOpen={true} onClose={() => {}} instance={instance} />);
        await screen.findByText('match1_map1_p0_alice.dm_91');

        fireEvent.click(screen.getByLabelText('Select match1_map1_p0_alice.dm_91'));
        fireEvent.click(screen.getByRole('button', { name: /download selected \(1\)/i }));

        expect(await screen.findByText('boom')).toBeInTheDocument();
    });
});
