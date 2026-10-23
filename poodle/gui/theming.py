"""
Colours and text size for Poodle's GUI.

style.qss carries no literal colours: it is written against the @tokens below,
and sets font-size on the universal selector, which overrides whatever
QApplication.setFont() says. Both are therefore resolved here, and a change
means reapplying the whole stylesheet; Qt then restyles every open window at
once. Widgets that paint themselves, or that brush their own model items, read
their colours from color() and redraw on palette_changed.

BASE_SIZE is the size style.qss is written in, so scaled() turns any other
measurement from that file into the current scale.
"""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from poodle import config
import os
import re


BASE_SIZE = 13      # the size style.qss is written in
MIN_SIZE = 9
MAX_SIZE = 32
STEP = 1

DEFAULT_PALETTE = 'cobalt'

# Every token style.qss uses, from the darkest ground to the accents.
PALETTES = {
    'cobalt': {
        'label':       'Cobalt',
        'base':        '#16395b',   # window background
        'mantle':      '#102c47',   # control bars, table background, pressed
        'raised':      '#1c4874',   # column headers, hovered tab, drop zone
        'surface':     '#23527f',   # buttons, borders, gridlines
        'surface_alt': '#2e6799',   # button borders, hovered button
        'surface_hi':  '#3b7cb3',   # selection
        'overlay':     '#6ea6d6',   # hover borders, placeholder text
        'text':        '#eaf3fb',
        'subtext':     '#b7d0e6',
        'accent':      '#ffc857',   # selected tab, focus, group labels
        'accent_soft': '#9bd4ff',   # column header text
        'hover':       '#1d4a76',   # hovered table row
    },
    'mocha': {
        'label':       'Mocha',
        'base':        '#1e1e2e',
        'mantle':      '#181825',
        'raised':      '#24273a',
        'surface':     '#313244',
        'surface_alt': '#45475a',
        'surface_hi':  '#585b70',
        'overlay':     '#6c7086',
        'text':        '#cdd6f4',
        'subtext':     '#a6adc8',
        'accent':      '#cba6f7',
        'accent_soft': '#89b4fa',
        'hover':       '#2a2a3e',
    },
}

_QSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'style.qss')
_FONT_SIZE_RE = re.compile(r'(font-size:\s*)(\d+(?:\.\d+)?)(px)')
_TOKEN_RE = re.compile(r'@([a-z_]+)')

_template = ''
_size = BASE_SIZE
_palette = DEFAULT_PALETTE


class _Scale(QObject):
    """Signals carrying the new text size in pixels, and the new palette."""

    changed = Signal(int)
    palette_changed = Signal(str)


scale = _Scale()


def palette_name() -> str:
    return _palette


def color(token: str) -> QColor:
    """The current palette's colour for a style.qss token."""
    return QColor(PALETTES[_palette][token])


def size() -> int:
    return _size


def factor() -> float:
    return _size / BASE_SIZE


def scaled(pixels: int) -> int:
    """Convert a measurement written for BASE_SIZE to the current size."""
    return max(1, round(pixels * factor()))


def _stylesheet(size_px: int, palette: str) -> str:
    ratio = size_px / BASE_SIZE
    colors = PALETTES[palette]

    def resize(match):
        value = max(1, round(float(match.group(2)) * ratio))
        return f'{match.group(1)}{value}{match.group(3)}'

    def fill(match):
        # An unknown token is left in place, where it shows up rather than
        # silently painting the wrong thing.
        return colors.get(match.group(1), match.group(0))

    return _TOKEN_RE.sub(fill, _FONT_SIZE_RE.sub(resize, _template))


def apply_size(size_px: int, save: bool = True) -> int:
    """Set the text size for every window, and return the size applied."""
    global _size

    _size = max(MIN_SIZE, min(MAX_SIZE, int(size_px)))
    app = QApplication.instance()
    if app:
        app.setStyleSheet(_stylesheet(_size, _palette))
        # For anything the stylesheet's selectors miss. Pixels, not points,
        # so that it agrees with the stylesheet.
        font = QFont('Inter')
        font.setPixelSize(_size)
        app.setFont(font)
    if save:
        config.save_setting('FONT_SIZE', _size)
    scale.changed.emit(_size)

    return _size


def set_palette(name: str, save: bool = True) -> None:
    """Switch the GUI's colours to one of PALETTES."""
    global _palette

    if name not in PALETTES:
        raise KeyError(f'no such palette: {name}. Try {list(PALETTES)}')
    _palette = name
    if save:
        config.save_setting('THEME', name)
    apply_size(_size, save=False)      # repaints everything in the new colours
    scale.palette_changed.emit(name)


def load(size_px: int = None, palette: str = None) -> None:
    """Read style.qss and apply the colours and size stored for this database."""
    global _template, _palette

    if os.path.exists(_QSS_PATH):
        with open(_QSS_PATH) as rf:
            _template = rf.read()
    if size_px is None:
        # From the file, not config.FONT_SIZE: that was read at import, and a
        # size chosen earlier in this session would be missing from it.
        size_px = config.read_setting('FONT_SIZE', BASE_SIZE)
    if palette is None:
        palette = config.read_setting('THEME', DEFAULT_PALETTE)
    _palette = palette if palette in PALETTES else DEFAULT_PALETTE
    apply_size(size_px, save=False)
    scale.palette_changed.emit(_palette)


def larger() -> None:
    apply_size(_size + STEP)


def smaller() -> None:
    apply_size(_size - STEP)


def reset() -> None:
    apply_size(BASE_SIZE)
