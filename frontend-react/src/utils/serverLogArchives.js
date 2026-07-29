/**
 * Helpers for the rotated server-log archives produced on QLDS hosts by
 * logrotate with `dateext` + `dateformat -%Y%m%d-%H%M%S`.
 *
 * `delaycompress` leaves the newest archive uncompressed, so the .gz suffix
 * is optional. Names that do not match are dropped rather than rendered, so a
 * stray file on the host can never break the picker.
 */

export const CURRENT_SERVER_LOG = 'server.log';

const ARCHIVE_RE = /^server\.log-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})(?:\.gz)?$/;

const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November', 'December'];

export function parseArchiveDate(filename) {
    const match = ARCHIVE_RE.exec((filename || '').trim());
    if (!match) return null;

    const [, y, mo, d, h, mi, s] = match;
    const date = new Date(
        Number(y), Number(mo) - 1, Number(d),
        Number(h), Number(mi), Number(s),
    );
    if (Number.isNaN(date.getTime())) return null;

    // The Date constructor normalizes out-of-range components (e.g. day 32
    // rolls into the next month) instead of producing an Invalid Date, which
    // would otherwise fabricate a phantom archive under the wrong day/month.
    // Reject anything that didn't round-trip exactly.
    if (date.getFullYear() !== Number(y)
        || date.getMonth() !== Number(mo) - 1
        || date.getDate() !== Number(d)
        || date.getHours() !== Number(h)
        || date.getMinutes() !== Number(mi)
        || date.getSeconds() !== Number(s)) {
        return null;
    }

    return date;
}

export function formatArchiveLabel(filename, occurrenceIndex = 0) {
    const date = parseArchiveDate(filename);
    if (!date) return filename;

    const base = `${MONTHS_SHORT[date.getMonth()]} ${date.getDate()}`;
    return occurrenceIndex > 0 ? `${base} (${occurrenceIndex + 1})` : base;
}

export function groupArchivesByMonth(filenames) {
    const parsed = (filenames || [])
        .filter((f) => f !== CURRENT_SERVER_LOG)
        .map((filename) => ({ filename, date: parseArchiveDate(filename) }))
        .filter((entry) => entry.date !== null)
        .sort((a, b) => b.date - a.date);

    // Number multiple archives from the same calendar day, newest first.
    const seenPerDay = new Map();
    const labelled = parsed.map((entry) => {
        const dayKey = `${entry.date.getFullYear()}-${entry.date.getMonth()}-${entry.date.getDate()}`;
        const occurrence = seenPerDay.get(dayKey) || 0;
        seenPerDay.set(dayKey, occurrence + 1);
        return { ...entry, label: formatArchiveLabel(entry.filename, occurrence) };
    });

    const groups = [];
    const indexByKey = new Map();

    labelled.forEach((entry) => {
        const key = `${entry.date.getFullYear()}-${entry.date.getMonth()}`;
        if (!indexByKey.has(key)) {
            indexByKey.set(key, groups.length);
            groups.push({
                key,
                label: `${MONTHS_LONG[entry.date.getMonth()]} ${entry.date.getFullYear()}`,
                items: [],
            });
        }
        groups[indexByKey.get(key)].items.push(entry);
    });

    return groups;
}
