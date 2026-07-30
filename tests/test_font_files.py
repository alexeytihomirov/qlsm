"""Tests for shared font file validation rules."""
import os
import re

import pytest

from ui.font_files import (
    FONT_EXTENSIONS,
    MAX_FONT_FILE_SIZE,
    validate_font_content,
)

TTF_VALID = b'\x00\x01\x00\x00' + b'\x00' * 20
TTF_APPLE_VALID = b'true' + b'\x00' * 20
OTF_VALID = b'OTTO' + b'\x00' * 20
TTC_VALID = b'ttcf' + b'\x00' * 20
WOFF_VALID = b'wOFF' + b'\x00' * 20
WOFF2_VALID = b'wOF2' + b'\x00' * 20
PFB_VALID = b'\x80\x01' + b'\x00' * 20
AFM_VALID = b'StartFontMetrics 4.1\n'


def test_all_thirteen_extensions_present():
    assert FONT_EXTENSIONS == frozenset({
        '.ttf', '.otf', '.ttc', '.otc', '.woff', '.woff2',
        '.eot', '.fon', '.fnt', '.pfb', '.pfa', '.pfm', '.afm',
    })


@pytest.mark.parametrize('ext,content', [
    ('.ttf', TTF_VALID),
    ('.ttf', TTF_APPLE_VALID),
    ('.otf', OTF_VALID),
    ('.ttc', TTC_VALID),
    ('.otc', TTC_VALID),
    ('.woff', WOFF_VALID),
    ('.woff2', WOFF2_VALID),
    ('.pfb', PFB_VALID),
    ('.afm', AFM_VALID),
])
def test_accepts_valid_signature(ext, content):
    assert validate_font_content(ext, content) is None


@pytest.mark.parametrize('ext,content', [
    ('.ttf', b'not a font'),
    ('.otf', b'not a font'),
    ('.ttc', b'not a font'),
    ('.otc', b'not a font'),
    ('.woff', b'not a font'),
    ('.woff2', b'not a font'),
    ('.pfb', b'\x80\x02' + b'\x00' * 20),  # segment type 2, not 1
    ('.afm', b'not a metrics file'),
])
def test_rejects_invalid_signature(ext, content):
    error = validate_font_content(ext, content)
    assert error is not None
    assert ext in error or 'signature' in error.lower()


@pytest.mark.parametrize('ext,content', [
    ('.eot', b'anything'),
    ('.pfa', b'%!PS-AdobeFont-1.0\n'),
    ('.pfm', b'anything'),
    ('.fon', b'MZ' + b'\x00' * 20),
    ('.fnt', b'\x00\x02' + b'\x00' * 20),
])
def test_no_signature_check_for_unchecked_extensions(ext, content):
    """These 5 extensions pass on extension+size alone, no magic-byte check."""
    assert validate_font_content(ext, content) is None


def test_rejects_oversized_font():
    oversized = TTF_VALID + b'\x00' * MAX_FONT_FILE_SIZE
    error = validate_font_content('.ttf', oversized)
    assert error is not None
    assert '25MB' in error


def test_accepts_font_at_exact_size_limit():
    content = TTF_VALID + b'\x00' * (MAX_FONT_FILE_SIZE - len(TTF_VALID))
    assert len(content) == MAX_FONT_FILE_SIZE
    assert validate_font_content('.ttf', content) is None


def test_font_extensions_match_frontend():
    """The frontend keeps its own FONT_EXTENSIONS copy for the upload accept
    filter and file-type classification. The two lists must not drift, or the
    UI will offer (or reject) extensions the backend disagrees about.
    """
    js_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'frontend-react', 'src', 'components', 'fileManager', 'fileManagerUtils.js',
    )
    with open(js_path, encoding='utf-8') as f:
        source = f.read()

    match = re.search(r'export const FONT_EXTENSIONS = \[(.*?)\]', source, re.DOTALL)
    assert match, 'FONT_EXTENSIONS not found in fileManagerUtils.js'
    frontend_extensions = set(re.findall(r"'([^']+)'", match.group(1)))

    assert frontend_extensions == set(FONT_EXTENSIONS)
