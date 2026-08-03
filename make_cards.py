"""songs.csv -> cards.html, a duplex-printable deck.

Print it from the browser (A4, margins "None", scale 100%, two-sided flipping on
the LONG edge). Sheets alternate front, back, front, back.

Usage:  python make_cards.py [--test-page]
"""
import csv, html, json, os, sys, zlib
import segno

PALETTES = 7

COLS, ROWS = 3, 4          # 65 mm cards on A4: 195 mm x 260 mm of the 210 x 297 sheet
PER_SHEET = COLS * ROWS
SRC = 'songs.csv'
OUT = 'cards.html'


def back_order(page, cols=COLS):
    """Mirror each row so a long-edge duplex flip lands the answer on its own QR.

    Front cell (r, c) ends up over back cell (r, cols-1-c) once the sheet is turned
    over. Padding to a full grid first keeps the final partial sheet aligned too.
    """
    padded = list(page) + [None] * (-len(page) % cols)
    return [padded[i:i + cols][::-1] for i in range(0, len(padded), cols)]


def front_html(song):
    qr = segno.make(f'https://open.spotify.com/track/{song["track_id"]}', error='m')
    # omitsize gives a viewBox instead of fixed width/height attributes. Without it the
    # SVG has no viewBox, so CSS resizes the canvas while the code stays 33px, tiny and
    # stuck in the top-left corner.
    return (f'<div class="card front">'
            f'<div class="qr">{qr.svg_inline(border=0, omitsize=True)}</div>'
            f'<div class="flag">HITSTER PL</div>'
            f'</div>')


def palette_class(track_id):
    """Scatter cards across the palettes with no relation to the year.

    crc32, not the built-in hash(): hash() is salted per process, so a card would
    change colour on every rebuild and a reprinted card would not match the deck.
    """
    return 'c%d' % (zlib.crc32(track_id.encode()) % PALETTES)


def split_year(year):
    """("1984*") -> ("1984", "*"). A trailing star marks a year nobody has confirmed."""
    y = str(year).strip()
    return (y[:-1], '*') if y.endswith('*') else (y, '')


def back_html(song):
    if song is None:
        return '<div class="card back empty"></div>'
    year, unsure = split_year(song['year'])
    return (f'<div class="card back {palette_class(song["track_id"])}">'
            f'<div class="artist">{html.escape(song["artist"])}</div>'
            f'<div class="year">{html.escape(year)}'
            f'<span class="unsure">{unsure}</span></div>'
            f'<div class="title">{html.escape(song["title"])}</div>'
            f'</div>')


CSS = """
@page { size: A4 portrait; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Helvetica Neue", Arial, sans-serif; -webkit-print-color-adjust: exact; }
.sheet { width: 210mm; height: 297mm; display: flex; align-items: center;
         justify-content: center; page-break-after: always; }
.grid { display: grid; grid-template-columns: repeat(3, 65mm); grid-template-rows: repeat(4, 65mm); }
.card { width: 65mm; height: 65mm; border: 0.2mm dashed #bbb;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        overflow: hidden; text-align: center; }

/* Front: white over red, the Polish flag. The QR keeps a white margin on every
   side -- red butted against the code eats its quiet zone and costs scans. */
.front { padding: 0; background: #fff; justify-content: space-between; }
.front .qr { flex: 1; display: flex; align-items: center; justify-content: center;
             width: 100%; line-height: 0; }
.front .qr svg { width: 44mm; height: 44mm; display: block; }
.front .flag { width: 100%; height: 9mm; background: #d4213d; color: #fff;
               font-size: 3.1mm; font-weight: 700; letter-spacing: 0.9mm;
               display: flex; align-items: center; justify-content: center; }

/* Back: gradients assigned by track id, all dark enough to carry white text. */
.back { padding: 5mm; color: #fff; background: #23272e;
        text-shadow: 0 0.25mm 0.7mm rgba(0,0,0,.5); }
.back .artist { font-size: 4.2mm; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.35mm; line-height: 1.25; margin-bottom: 5mm; }
.back .year   { font-size: 18mm; font-weight: 800; line-height: 1; letter-spacing: -0.4mm; }
/* Unconfirmed year: visible enough to notice, quiet enough not to fight the number. */
.back .unsure { font-size: 8mm; opacity: .6; vertical-align: super; margin-left: 0.5mm; }
.back .title  { font-size: 4mm; font-style: italic; line-height: 1.3; margin-top: 5mm; }
.back.c0 { background: linear-gradient(155deg, #5e380f, #8f5f16); }
.back.c1 { background: linear-gradient(155deg, #6f2610, #b34e1c); }
.back.c2 { background: linear-gradient(155deg, #5a1668, #b01f6a); }
.back.c3 { background: linear-gradient(155deg, #0f3557, #1d6f92); }
.back.c4 { background: linear-gradient(155deg, #262063, #4e3cab); }
.back.c5 { background: linear-gradient(155deg, #11402c, #2a7d52); }
.back.c6 { background: linear-gradient(155deg, #4a1526, #a32f4e); }
.back.empty { background: #fff; border-style: dotted; border-color: #eee; }
@media screen { body { background: #666; } .sheet { background: #fff; margin: 8px auto; } }
"""


def main():
    test_only = '--test-page' in sys.argv
    with open(SRC, encoding='utf-8') as f:
        songs = [r for r in csv.DictReader(f) if r['track_id']]
    if not songs:
        sys.exit(f'{SRC} has no rows with a track_id -- run fetch_songs.py first.')

    pages = [songs[i:i + PER_SHEET] for i in range(0, len(songs), PER_SHEET)]
    if test_only:
        pages = pages[:1]

    out = [f'<!doctype html><meta charset="utf-8"><title>Hitster PL</title><style>{CSS}</style>']
    for page in pages:
        out.append('<div class="sheet"><div class="grid">'
                   + ''.join(front_html(s) for s in page) + '</div></div>')
        out.append('<div class="sheet"><div class="grid">'
                   + ''.join(back_html(s) for row in back_order(page) for s in row)
                   + '</div></div>')
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))

    # The app reveals the answer from this file, not from Spotify -- Spotify's
    # release_date is the remaster year and would show 2025 for a 1977 song.
    if not test_only:
        os.makedirs('docs', exist_ok=True)
        deck = {s['track_id']: {'a': s['artist'], 't': s['title'], 'y': s['year']}
                for s in songs}
        with open(os.path.join('docs', 'deck.json'), 'w', encoding='utf-8') as f:
            json.dump(deck, f, ensure_ascii=False, separators=(',', ':'))
        print(f'docs/deck.json: {len(deck)} tracks for the scanner app.')

    n = sum(len(p) for p in pages)
    print(f'{OUT}: {n} cards on {len(pages)} sheet(s) = {len(pages) * 2} printed sides.')
    print('Print A4, margins None, scale 100%, two-sided flip on the LONG edge.')
    if test_only:
        print('Test page only -- check a card measures 65 mm before printing the rest.')


if __name__ == '__main__':
    main()
