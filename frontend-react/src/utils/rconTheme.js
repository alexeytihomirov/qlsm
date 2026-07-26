import { EditorView } from '@codemirror/view';

/**
 * Shared chrome for the RCON output surface. Exported so static one-line
 * previews can wear the same frame, gutter and font metrics as a live
 * CodeMirror viewer without mounting one — collapsing a target block then
 * swaps the content inside the rectangle instead of dropping the rectangle.
 */
export const RCON_FRAME_CLASS = 'rounded-lg border-2 border-theme-strong overflow-hidden';
export const RCON_SURFACE_BACKGROUND = 'rgba(0,0,0,0.4)';
export const RCON_FONT_FAMILY = "'JetBrains Mono', 'Fira Code', 'Source Code Pro', 'Cascadia Code', 'Consolas', monospace";
export const RCON_FONT_SIZE = '13.5px';
export const RCON_LINE_HEIGHT = '1.6';
// CodeMirror's own defaults for the pieces a replica has to line up with:
// .cm-content padding, .cm-line padding, and the line-number gutter.
export const RCON_CONTENT_PADDING = '8px 2px 8px 6px';
export const RCON_GUTTER = {
    background: '#0a0e14',
    borderRight: '1px solid rgba(255,255,255,0.08)',
    color: '#64748b',
    minWidth: '20px',
    padding: '8px 3px 8px 5px',
};
export const RCON_TEXT_COLOR = '#abb2bf';

/**
 * Custom CodeMirror theme for RCON/Terminal consoles.
 * Provides a dark, transparent background with specific styling for Quake Live colors.
 */
export const rconTheme = EditorView.theme({
    '&': {
        height: '100%',
        backgroundColor: 'transparent !important',
        fontSize: RCON_FONT_SIZE,
        fontFamily: RCON_FONT_FAMILY,
        lineHeight: RCON_LINE_HEIGHT,
    },
    '& .cm-scroller': {
        backgroundColor: 'transparent !important',
        overflow: 'auto',
    },
    '& .cm-content': {
        backgroundColor: 'transparent !important',
        caretColor: '#528bff',
        padding: '8px 0',
    },
    '& .cm-gutters': {
        backgroundColor: `${RCON_GUTTER.background} !important`,
        borderRight: RCON_GUTTER.borderRight,
        color: `${RCON_GUTTER.color} !important`,
    },
    '& .cm-gutter': {
        backgroundColor: `${RCON_GUTTER.background} !important`,
    },
    '& .cm-lineNumbers .cm-gutterElement': {
        color: `${RCON_GUTTER.color} !important`,
        opacity: '1 !important',
    },
    '& .cm-activeLineGutter': {
        backgroundColor: 'rgba(255, 255, 255, 0.05) !important',
    },
    '& .cm-activeLine': {
        backgroundColor: 'rgba(255, 255, 255, 0.03) !important',
    },
    '& .cm-line': {
        color: RCON_TEXT_COLOR, // Warm off-white matching oneDark foreground
    },
    // Search panel styling
    '& .cm-panels': { backgroundColor: '#1e1e1e', zIndex: '100' },
    '& .cm-panels-top': { borderBottom: '1px solid #444' },
    '& .cm-search input': {
        backgroundColor: '#333', color: '#fff', border: '1px solid #555',
        borderRadius: '3px', padding: '2px 6px'
    },
    '& .cm-search button': {
        backgroundColor: '#444', color: '#fff', border: '1px solid #555',
        borderRadius: '3px', padding: '2px 8px', marginLeft: '4px'
    },
    // Cursor styles for readOnly
    '& .cm-cursor': { borderLeftColor: '#528bff' },
    '& .cm-selectionBackground': { backgroundColor: 'rgba(82, 139, 255, 0.2) !important' },
    '&.cm-focused .cm-selectionBackground': { backgroundColor: 'rgba(82, 139, 255, 0.3) !important' },
});
