// The colors a `live_status_columns` cell may ask for (addons/README.md).
//
// A fixed palette of names rather than a CSS value: the cell is third-party
// content rendered inside a table core owns, so an addon picks *which* of
// core's colors, never the color itself. It also has to be a closed list for
// a practical reason -- Tailwind only emits classes it can see in the source,
// so a class name built from an addon's response would not exist at runtime.
//
// The names follow Quake Live's ^N color codes, since the first use is a rank
// tier shown in its in-game color. The dark theme uses the game colors; the
// light theme uses darker shades of the same hues, because white, yellow and
// cyan vanish on a light background.
const ADDON_CELL_COLORS = new Map([
  ['white', 'text-theme-primary'],
  ['yellow', 'text-[#a16207] dark:text-[#ffff44]'],
  ['cyan', 'text-[#0e7490] dark:text-[#44ffff]'],
  ['blue', 'text-[#2563eb] dark:text-[#6688ff]'],
  ['magenta', 'text-[#c026d3] dark:text-[#ff44ff]'],
  ['green', 'text-[#15803d] dark:text-[#44ff44]'],
]);

/** The palette name if `value` is one, else null. */
export const addonCellColor = (value) => (
  typeof value === 'string' && ADDON_CELL_COLORS.has(value) ? value : null
);

/** Classes for a palette name; '' for null or anything not in the palette. */
export const addonCellColorClass = (name) => ADDON_CELL_COLORS.get(name) || '';
