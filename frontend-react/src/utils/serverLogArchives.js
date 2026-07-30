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

const DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

function isLeapYear(year) {
    return (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
}

// month is 1-based here, matching the raw digits parsed from the filename.
function daysInMonth(year, month) {
    if (month === 2 && isLeapYear(year)) return 29;
    return DAYS_IN_MONTH[month - 1];
}

export function parseArchiveDate(filename) {
    const match = ARCHIVE_RE.exec((filename || '').trim());
    if (!match) return null;

    const [, y, mo, d, h, mi, s] = match;
    const year = Number(y);
    const month = Number(mo);
    const day = Number(d);
    const hour = Number(h);
    const minute = Number(mi);
    const second = Number(s);

    // Range-check the parsed integers directly, before constructing a Date.
    // The Date constructor normalizes out-of-range components (e.g. day 32
    // rolls into the next month) instead of producing an Invalid Date — but
    // it also normalizes otherwise-valid local times that fall in a DST
    // spring-forward gap (e.g. 02:30 becomes 03:30 on the day clocks skip
    // forward). A round-trip check against the constructed Date can't tell
    // those two cases apart, so it would either fabricate a phantom archive
    // or silently hide a real one depending on the viewer's timezone.
    // Validating the integers first avoids relying on normalization at all.
    if (month < 1 || month > 12
        || day < 1 || day > daysInMonth(year, month)
        || hour > 23 || minute > 59 || second > 59) {
        return null;
    }

    const date = new Date(year, month - 1, day, hour, minute, second);
    return Number.isNaN(date.getTime()) ? null : date;
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
