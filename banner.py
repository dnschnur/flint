"""Demoscene-style ANSI art banner for Flint."""

import math

BANNER_WIDTH = 78

LOGO = [
  '███████╗ ██╗      ██╗ ███╗   ██╗ ████████╗',
  '██╔════╝ ██║      ██║ ████╗  ██║ ╚══██╔══╝',
  '█████╗   ██║      ██║ ██╔██╗ ██║    ██║   ',
  '██╔══╝   ██║      ██║ ██║ ██╗██║    ██║   ',
  '██║      ███████╗ ██║ ██║  ████║    ██║   ',
  '╚═╝      ╚══════╝ ╚═╝ ╚═╝  ╚═══╝    ╚═╝   ',
]

BORDER_TOP  = '▓▒░' + '·:·:' * 18 + '░▒▓'   # 78 chars
BORDER_BOTTOM  = '░▒▓' + '·:·:' * 18 + '▓▒░'   # 78 chars, reversed gradient

SUBTITLE  = '·· RETIREMENT SIMULATOR · MONTE CARLO EDITION ··'
EXIT_HINT = 'Ctrl-C to stop'

LOGO_PADDING = (BANNER_WIDTH - max(len(line) for line in LOGO)) // 2


def _blue(hue_pos: float) -> tuple[int, int, int]:
  """Map hue_pos to a blue using the middle 50% of the lightness range (HSL 210°, s=1.0)."""
  lightness = 0.6 + 0.15 * math.sin(hue_pos * 2 * math.pi)  # Oscillates between 0.45 and 0.75
  hue, saturation = 7 / 12, 1.0  # 210°, S=1 anchors midpoint at RGB(0,128,255)
  chroma = (1 - abs(2 * lightness - 1)) * saturation
  secondary = chroma * (1 - abs((hue * 6) % 2 - 1))
  offset = lightness - chroma / 2
  r, g, b = 0 + offset, secondary + offset, chroma + offset
  return int(r * 255), int(g * 255), int(b * 255)


def print_banner(port: int) -> None:
  """Print a demoscene-style ANSI art banner with the server URL."""
  url   = f'▶ http://localhost:{port}'

  hue = 0.0

  def line(text='', pad=0):
    nonlocal hue
    padded = '  ' + ' ' * pad + text
    out = []
    for col, char in enumerate(padded):
      r, g, b = _blue(hue + col * 0.025)
      out.append(f'\x1b[38;2;{r};{g};{b}m{char}')
    hue += 0.08
    return ''.join(out) + '\x1b[0m'

  print()
  print(line(BORDER_TOP))
  print(line())
  for logo_row in LOGO:
    print(line(logo_row, LOGO_PADDING))
  print(line())
  print(line(BORDER_BOTTOM))
  print(line())
  print(line(SUBTITLE, (BANNER_WIDTH - len(SUBTITLE)) // 2))
  print(line())
  print(line(url,  (BANNER_WIDTH - len(url))  // 2))
  print(line(EXIT_HINT, (BANNER_WIDTH - len(EXIT_HINT)) // 2))
  print()
