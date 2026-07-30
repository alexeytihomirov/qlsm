import { describe, it, expect } from 'vitest';
import {
    CURRENT_SERVER_LOG,
    parseArchiveDate,
    formatArchiveLabel,
    groupArchivesByMonth,
} from '../serverLogArchives';

describe('parseArchiveDate', () => {
    it('parses an uncompressed archive name', () => {
        const d = parseArchiveDate('server.log-20260729-093000');
        expect(d.getFullYear()).toBe(2026);
        expect(d.getMonth()).toBe(6); // July
        expect(d.getDate()).toBe(29);
    });

    it('parses a compressed archive name', () => {
        const d = parseArchiveDate('server.log-20260728-091500.gz');
        expect(d.getFullYear()).toBe(2026);
        expect(d.getMonth()).toBe(6); // July
        expect(d.getDate()).toBe(28);
    });

    it('returns null for the current log', () => {
        expect(parseArchiveDate(CURRENT_SERVER_LOG)).toBeNull();
    });

    it('returns null for unparseable names', () => {
        expect(parseArchiveDate('server.log.1')).toBeNull();
        expect(parseArchiveDate('garbage')).toBeNull();
    });

    it('returns null for an out-of-range day instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20260732-093000')).toBeNull();
    });

    it('returns null for an out-of-range month instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20261301-093000')).toBeNull();
    });

    it('returns null for Feb 29 in a non-leap year instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20260229-093000')).toBeNull();
    });

    it('returns null for an out-of-range hour instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20260729-253000')).toBeNull();
    });

    it('returns null for an out-of-range minute instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20260729-097000')).toBeNull();
    });

    it('returns null for an out-of-range second instead of rolling over', () => {
        expect(parseArchiveDate('server.log-20260729-093099')).toBeNull();
    });

    // DST spring-forward: local clocks skip 02:00-02:59 on Mar 8 2026 in
    // timezones that observe it (e.g. America/Vancouver). The archive
    // timestamp is the *host's* local time and is parsed in the *viewer's*
    // timezone, so a filename landing in that gap is a legitimate archive,
    // not a malformed one. It must still parse — asserting a specific hour
    // here would bake in whatever normalization the local Date constructor
    // applies, so we only assert it resolves to a real Date. Do not
    // "simplify" parseArchiveDate back to a round-trip-against-Date check;
    // that reintroduces this bug (see Fix round 2 in task-5-report.md).
    it('parses a timestamp that falls in a DST spring-forward gap', () => {
        expect(parseArchiveDate('server.log-20260308-020000')).toBeInstanceOf(Date);
        expect(parseArchiveDate('server.log-20260308-023000')).toBeInstanceOf(Date);
        expect(parseArchiveDate('server.log-20260308-025959')).toBeInstanceOf(Date);
    });
});

describe('formatArchiveLabel', () => {
    it('formats as short month and day', () => {
        expect(formatArchiveLabel('server.log-20260729-093000', 0)).toBe('Jul 29');
    });

    it('disambiguates same-day archives', () => {
        expect(formatArchiveLabel('server.log-20260729-140000', 1)).toBe('Jul 29 (2)');
    });

    it('falls back to the raw filename when unparseable', () => {
        expect(formatArchiveLabel('weird.log', 0)).toBe('weird.log');
    });
});

describe('groupArchivesByMonth', () => {
    it('groups archives by month, newest first', () => {
        const groups = groupArchivesByMonth([
            'server.log',
            'server.log-20260729-093000',
            'server.log-20260728-091500.gz',
            'server.log-20260630-091500.gz',
        ]);
        expect(groups).toHaveLength(2);
        expect(groups[0].label).toBe('July 2026');
        expect(groups[0].items.map(i => i.label)).toEqual(['Jul 29', 'Jul 28']);
        expect(groups[1].label).toBe('June 2026');
    });

    it('excludes the current log from groups', () => {
        const groups = groupArchivesByMonth([CURRENT_SERVER_LOG]);
        expect(groups).toEqual([]);
    });

    it('drops unparseable names instead of throwing', () => {
        const groups = groupArchivesByMonth(['server.log-bogus', 'server.log-20260729-093000']);
        expect(groups).toHaveLength(1);
        expect(groups[0].items).toHaveLength(1);
    });

    it('numbers same-day archives newest first', () => {
        const groups = groupArchivesByMonth([
            'server.log-20260729-093000',
            'server.log-20260729-140000',
        ]);
        expect(groups[0].items.map(i => i.label)).toEqual(['Jul 29', 'Jul 29 (2)']);
    });

    it('drops an out-of-range date instead of fabricating a phantom month group', () => {
        const groups = groupArchivesByMonth([
            'server.log-20260729-093000',
            'server.log-20260732-093000',
        ]);
        expect(groups).toHaveLength(1);
        expect(groups[0].label).toBe('July 2026');
        expect(groups[0].items.map(i => i.label)).toEqual(['Jul 29']);
    });
});
