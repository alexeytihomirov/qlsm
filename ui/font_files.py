"""Shared extension/validation rules for font files uploadable in the Plugins
tab's scripts/ tree.

Font files ride the same drafts/instance/preset scripts/ directory as
.py/.txt/.so plugin files (see draft_routes.py, preset_api_routes.py,
preset_import_validation.py). This module is the single place the byte-level
size and magic-byte checks live, so those three call sites don't each
duplicate the logic.
"""

FONT_EXTENSIONS = frozenset({
    '.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2',
    '.eot', '.fon', '.fnt', '.pfb', '.pfa', '.pfm', '.afm',
})

MAX_FONT_FILE_SIZE = 25 * 1024 * 1024  # 25MB


def _check_ttf(content):
    return content[:4] in (b'\x00\x01\x00\x00', b'true', b'typ1')


def _check_otf(content):
    return content[:4] == b'OTTO'


def _check_ttc(content):
    return content[:4] == b'ttcf'


def _check_woff(content):
    return content[:4] == b'wOFF'


def _check_woff2(content):
    return content[:4] == b'wOF2'


def _check_pfb(content):
    return content[:2] == b'\x80\x01'


def _check_afm(content):
    return content.startswith(b'StartFontMetrics')


FONT_MAGIC_CHECKS = {
    '.ttf': _check_ttf,
    '.otf': _check_otf,
    '.ttc': _check_ttc,
    '.otc': _check_ttc,
    '.woff': _check_woff,
    '.woff2': _check_woff2,
    '.pfb': _check_pfb,
    '.afm': _check_afm,
}


def validate_font_content(ext, content):
    """Validate a font file's size and (where possible) magic bytes.

    `ext` must already be confirmed to be in FONT_EXTENSIONS by the caller.
    Returns an error message string, or None if the content is valid.
    """
    if len(content) > MAX_FONT_FILE_SIZE:
        return f"File exceeds {MAX_FONT_FILE_SIZE // (1024 * 1024)}MB size limit"
    check = FONT_MAGIC_CHECKS.get(ext)
    if check is not None and not check(content):
        return f"Invalid {ext} file: does not match the expected {ext} signature"
    return None
