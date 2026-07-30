import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CURRENT_SERVER_LOG } from '../../../utils/serverLogArchives';

const mocks = vi.hoisted(() => ({
    fetchInstanceRemoteLogs: vi.fn(),
    listInstanceServerLogArchives: vi.fn(),
    ARCHIVE_FILENAME: 'server.log-20260728-091500.gz',
}));

vi.mock('../../../services/api', () => ({
    fetchInstanceRemoteLogs: mocks.fetchInstanceRemoteLogs,
    listInstanceServerLogArchives: mocks.listInstanceServerLogArchives,
}));

vi.mock('@headlessui/react', () => {
    const Dialog = ({ open, children }) => (open ? <div role="dialog">{children}</div> : null);
    Dialog.Panel = ({ children }) => <div>{children}</div>;
    Dialog.Title = ({ children }) => <div>{children}</div>;
    const DialogBackdrop = () => <div />;
    return { Dialog, DialogBackdrop };
});

// CodeMirrorEditor/ExpandedEditorModal pull in real @codemirror/view, which is
// unnecessary weight for tests that only exercise the archive-selection wiring.
vi.mock('../../CodeMirrorEditor', () => ({ default: () => <div data-testid="cm-editor" /> }));
vi.mock('../../ExpandedEditorModal', () => ({ default: () => null }));

// Not under test here (Task 6 covers it) — stub exposes just enough to select an
// archive and observe what filename the modal currently believes is selected.
vi.mock('../ServerLogArchivePicker', () => ({
    default: ({ selectedFile, onSelect }) => (
        <div>
            <span data-testid="selected-file">{selectedFile}</span>
            <button onClick={() => onSelect(mocks.ARCHIVE_FILENAME)}>select-archive</button>
        </div>
    ),
}));

vi.mock('../LogFilterControls', () => ({ default: () => <div data-testid="filter-controls" /> }));

import ViewLogsModal from '../ViewLogsModal';

describe('ViewLogsModal archive selection', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.fetchInstanceRemoteLogs.mockResolvedValue({ logs: 'a log line' });
        mocks.listInstanceServerLogArchives.mockResolvedValue({
            files: [CURRENT_SERVER_LOG, mocks.ARCHIVE_FILENAME],
        });
    });

    it('never fetches a previous instance archive filename after switching instances while open', async () => {
        const instanceA = { id: 1, name: 'Instance A', port: 27960 };
        const instanceB = { id: 2, name: 'Instance B', port: 27961 };

        const { rerender } = render(<ViewLogsModal isOpen={true} onClose={() => {}} instance={instanceA} />);

        await waitFor(() => expect(mocks.listInstanceServerLogArchives).toHaveBeenCalledWith(1));

        fireEvent.click(screen.getByText('select-archive'));
        await waitFor(() =>
            expect(screen.getByTestId('selected-file').textContent).toBe(mocks.ARCHIVE_FILENAME)
        );

        mocks.fetchInstanceRemoteLogs.mockClear();

        rerender(<ViewLogsModal isOpen={true} onClose={() => {}} instance={instanceB} />);

        // The corrected fetch for instance B, using the current log, must land.
        await waitFor(() => {
            expect(mocks.fetchInstanceRemoteLogs).toHaveBeenCalledWith(
                2,
                expect.objectContaining({ filename: CURRENT_SERVER_LOG })
            );
        });

        // No call was ever made for instance B carrying instance A's archive filename —
        // checked over the full accumulated call history, not just the latest call, so
        // a call that fired and was later "corrected" would still be caught here.
        const staleCall = mocks.fetchInstanceRemoteLogs.mock.calls.find(
            ([id, opts]) => id === 2 && opts.filename === mocks.ARCHIVE_FILENAME
        );
        expect(staleCall).toBeUndefined();
    });

    it('falls back to Current/LIVE when the archive list call rejects', async () => {
        mocks.listInstanceServerLogArchives.mockRejectedValueOnce(new Error('list failed'));
        const instanceA = { id: 1, name: 'Instance A', port: 27960 };

        render(<ViewLogsModal isOpen={true} onClose={() => {}} instance={instanceA} />);

        await waitFor(() => expect(mocks.listInstanceServerLogArchives).toHaveBeenCalledWith(1));
        await waitFor(() =>
            expect(screen.getByTestId('selected-file').textContent).toBe(CURRENT_SERVER_LOG)
        );
    });
});
