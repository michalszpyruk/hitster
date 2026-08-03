"""songs.csv -> cards.html, a duplex-printable deck.

Print it from the browser (A4, margins "None", scale 100%, two-sided flipping on
the LONG edge). Sheets alternate front, back, front, back.

Usage:  python make_cards.py [--test-page]
"""
import csv, html, json, os, sys
import segno

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
    return f'<div class="card front">{qr.svg_inline(border=0)}</div>'


def back_html(song):
    if song is None:
        return '<div class="card back empty"></div>'
    return (f'<div class="card back">'
            f'<div class="artist">{html.escape(song["artist"])}</div>'
            f'<div class="year">{html.escape(str(song["year"]))}</div>'
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
        overflow: hidden; padding: 4mm; text-align: center; }
.front svg { width: 46mm; height: 46mm; display: block; }
.back .artist { font-size: 4.2mm; font-weight: 700; text-transform: uppercase;
                letter-spacing: 0.3mm; line-height: 1.2; }
.back .year   { font-size: 17mm; font-weight: 800; line-height: 1.1; margin: 3mm 0; }
.back .title  { font-size: 4mm; font-style: italic; line-height: 1.25; }
.back.empty   { border-style: dotted; border-color: #eee; }
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
