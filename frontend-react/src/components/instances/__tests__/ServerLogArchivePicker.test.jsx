import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});
