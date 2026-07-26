import { describe, expect, it } from 'vitest';

import {
  RCON_FONT_FAMILY, RCON_FONT_SIZE, RCON_GUTTER, RCON_LINE_HEIGHT, rconThemeSpec,
} from '../rconTheme';

describe('rconTheme', () => {
  // CodeMirror's base theme declares font-family: monospace and line-height:
  // 1.4 straight onto .cm-scroller. A direct declaration beats an inherited
  // one, so setting the font on '&' alone leaves the editor in the browser's
  // default monospace — invisible until some other surface (the collapsed
  // one-line preview) renders the same text in the intended font next to it.
  it('pins the font on .cm-scroller, not just the editor root', () => {
    expect(rconThemeSpec['& .cm-scroller']).toMatchObject({
      fontFamily: RCON_FONT_FAMILY,
      lineHeight: RCON_LINE_HEIGHT,
    });
  });

  it('drives every text surface from one set of metrics', () => {
    expect(rconThemeSpec['&']).toMatchObject({
      fontSize: RCON_FONT_SIZE,
      fontFamily: RCON_FONT_FAMILY,
      lineHeight: RCON_LINE_HEIGHT,
    });
    expect(rconThemeSpec['& .cm-gutters'].backgroundColor).toBe(`${RCON_GUTTER.background} !important`);
    expect(rconThemeSpec['& .cm-gutters'].borderRight).toBe(RCON_GUTTER.borderRight);
  });
});
