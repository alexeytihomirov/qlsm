import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import ServerLogArchivePicker from '../ServerLogArchivePicker';
import { CURRENT_SERVER_LOG } from '../../../utils/serverLogArchives';

const FILES = [
    CURRENT_SERVER_LOG,
    'server.log-20260729-093000',
    'server.log-20260728-091500.gz',
    'server.log-20260630-091500.gz',
];

describe('ServerLogArchivePicker', () => {
    it('shows the LIVE badge when the current log is selected', () => {
        render(
            <ServerLogArchivePicker files={FILES} selectedFile={CURRENT_SERVER_LOG} onSelect={() => {}} />
        );
        expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('shows the ARCHIVED badge with the date when an archive is selected', () => {
        render(
            <ServerLogArchivePicker
                files={FILES}
                selectedFile="server.log-20260729-093000"
                onSelect={() => {}}
            />
        );
        expect(screen.getByText('ARCHIVED')).toBeInTheDocument();
        expect(screen.getByText('Jul 29')).toBeInTheDocument();
    });

    it('renders month group headers and archive entries when opened', async () => {
        const user = userEvent.setup();
        render(
            <ServerLogArchivePicker files={FILES} selectedFile={CURRENT_SERVER_LOG} onSelect={() => {}} />
        );
        await user.click(screen.getByRole('button'));
        expect(screen.getByText('July 2026')).toBeInTheDocument();
        expect(screen.getByText('June 2026')).toBeInTheDocument();
        expect(screen.getByText('Jul 28')).toBeInTheDocument();
    });

    it('calls onSelect with the raw filename', async () => {
        const user = userEvent.setup();
        const onSelect = vi.fn();
        render(
            <ServerLogArchivePicker files={FILES} selectedFile={CURRENT_SERVER_LOG} onSelect={onSelect} />
        );
        await user.click(screen.getByRole('button'));
        await user.click(screen.getByText('Jul 28'));
        expect(onSelect).toHaveBeenCalledWith('server.log-20260728-091500.gz');
    });

    it('shows the occurrence-qualified label for a same-day archive, matching the dropdown', async () => {
        const user = userEvent.setup();
        const sameDayFiles = [
            CURRENT_SERVER_LOG,
            'server.log-20260729-140000',
            'server.log-20260729-093000',
        ];
        render(
            <ServerLogArchivePicker
                files={sameDayFiles}
                selectedFile="server.log-20260729-093000"
                onSelect={() => {}}
            />
        );

        // The trigger must show the disambiguated label for the selected
        // (older, second) same-day archive, not the bare date shared by both.
        const trigger = screen.getByRole('button');
        expect(within(trigger).getByText('Jul 29 (2)')).toBeInTheDocument();
        expect(within(trigger).queryByText('Jul 29', { exact: true })).not.toBeInTheDocument();

        await user.click(trigger);
        expect(screen.getByRole('option', { name: 'Jul 29' })).toBeInTheDocument();
        expect(screen.getByRole('option', { name: 'Jul 29 (2)' })).toBeInTheDocument();
        // "Jul 29 (2)" now renders twice (trigger + its own option) — both
        // legitimate, since the trigger reflects the current selection.
        expect(screen.getAllByText('Jul 29 (2)')).toHaveLength(2);
    });

    it('shows Archived and never renders the raw filename when selectedFile is unparseable', () => {
        const rawFilename = 'server.log-notarealdate-garbage.gz';
        render(
            <ServerLogArchivePicker
                files={[CURRENT_SERVER_LOG, rawFilename]}
                selectedFile={rawFilename}
                onSelect={() => {}}
            />
        );
        expect(screen.getByText('Archived')).toBeInTheDocument();
        expect(screen.queryByText(rawFilename)).not.toBeInTheDocument();
        expect(document.body.textContent).not.toContain(rawFilename);
    });

    it('renders without crashing and shows Current/LIVE when there are no archive files', () => {
        render(<ServerLogArchivePicker files={[]} selectedFile={CURRENT_SERVER_LOG} onSelect={() => {}} />);
        expect(screen.getByText('LIVE')).toBeInTheDocument();
        expect(screen.getByText('Current')).toBeInTheDocument();
    });

    it('renders without crashing when files contains only the current log', () => {
        render(
            <ServerLogArchivePicker
                files={[CURRENT_SERVER_LOG]}
                selectedFile={CURRENT_SERVER_LOG}
                onSelect={() => {}}
            />
        );
        expect(screen.getByText('LIVE')).toBeInTheDocument();
        expect(screen.getByText('Current')).toBeInTheDocument();
    });
});
