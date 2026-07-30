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

// Stub exposes just enough to flip to Time Range mode before an archive is
// selected, to drive the time+archive ordering test below.
vi.mock('../LogFilterControls', () => ({
    default: ({ filterMode, setFilterMode }) => (
        <div data-testid="filter-controls">
            <span data-testid="filter-mode">{filterMode}</span>
            <button onClick={() => setFilterMode('time')}>set-time-mode</button>
        </div>
    ),
}));

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

    it('never sends filter_mode "time" together with an archive filename after Time Range is selected before an archive', async () => {
        const instanceA = { id: 1, name: 'Instance A', port: 27960 };

        render(<ViewLogsModal isOpen={true} onClose={() => {}} instance={instanceA} />);

        await waitFor(() => expect(mocks.listInstanceServerLogArchives).toHaveBeenCalledWith(1));

        // Switch to Time Range first, then pick an archive — picking is not
        // Apply-gated, so this fires the refetch effect immediately with the
        // archive filename while `filterMode` is still 'time' in that render's
        // closure. The fallback effect that corrects `filterMode` itself runs
        // after the refetch effect, so it cannot be what prevents the bad request.
        fireEvent.click(screen.getByText('set-time-mode'));
        fireEvent.click(screen.getByText('select-archive'));

        // The corrected request — archive filename, downgraded to line mode — must land.
        await waitFor(() => {
            expect(mocks.fetchInstanceRemoteLogs).toHaveBeenCalledWith(
                1,
                expect.objectContaining({ filename: mocks.ARCHIVE_FILENAME, filterMode: 'lines' })
            );
        });

        // No call was ever made carrying the backend-rejected combination, checked
        // over the full accumulated call history.
        const badCall = mocks.fetchInstanceRemoteLogs.mock.calls.find(
            ([, opts]) => opts.filename === mocks.ARCHIVE_FILENAME && opts.filterMode === 'time'
        );
        expect(badCall).toBeUndefined();
    });

    // Covers only the pre-existing `setAvailableFiles` reset and crash-avoidance in
    // fetchLogFiles's catch branch. It does NOT discriminate the `setSelectedFile
    // (CURRENT_SERVER_LOG)` line added there in fix round 1: on a fresh mount,
    // selectedFile is already CURRENT_SERVER_LOG before the rejecting call fires,
    // so that line has nothing to correct in this scenario. See task-7-report.md's
    // "Fix round 1/5" section for why that line is currently unreachable under the
    // present effect wiring (kept intentionally as defensive code, per the
    // coordinator's fix round 2 instructions).
    it('shows Current/LIVE and does not crash when the archive list call rejects', async () => {
        mocks.listInstanceServerLogArchives.mockRejectedValueOnce(new Error('list failed'));
        const instanceA = { id: 1, name: 'Instance A', port: 27960 };

        render(<ViewLogsModal isOpen={true} onClose={() => {}} instance={instanceA} />);

        await waitFor(() => expect(mocks.listInstanceServerLogArchives).toHaveBeenCalledWith(1));
        await waitFor(() =>
            expect(screen.getByTestId('selected-file').textContent).toBe(CURRENT_SERVER_LOG)
        );
    });
});
