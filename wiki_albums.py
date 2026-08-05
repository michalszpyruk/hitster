"""Date cards from Polish Wikipedia album tracklists -> report, or --apply.

The per-song approach (wiki_years.py) only reaches songs famous enough to have their
own article -- about a third of the deck. But nearly every notable Polish ALBUM has an
article, with an infobox year and a full tracklist. Walking an artist's discography and
finding the earliest studio album containing a track dates it directly, and it scales:
one artist's pages settle every card by that artist at once.

Compilations are skipped. Their tracklists are full of old songs and their year is the
reissue's, which is the same trap that made Spotify useless for this catalogue.

Usage:  python wiki_albums.py [--apply]
"""
import csv, json, os, re, sys, time
import collections

from wiki_years import page_text
from fetch_songs import norm
from fetch_playlist import clean_title

DECK = 'songs.csv'
CACHE = 'wiki_albums_cache.json'
PAUSE = 0.2
COMPILATION_HINT = ('kompilacyjny', 'kompilacja', 'składanka', 'best of', 'złota kolekcja',
                    'the very best', 'największe przeboje', 'antologia', 'koncertowy')


def clean_track(t):
    """Strip the wiki decorations around a tracklist entry."""
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('„', '').replace('”', '').replace('"', '').replace("''", '')
    return norm(t.split('(')[0])


def album_pages(artist, cache):
    key = f'pages|{norm(artist)}'
    if key in cache:
        return cache[key]
    seen = []
    for page in (f'Dyskografia {artist}', artist):
        txt = page_text(page)
        time.sleep(PAUSE)
        if not txt:
            continue
        for m in re.findall(r'\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]', txt):
            m = m.strip()
            if any(k in m.lower() for k in ('kategoria', 'plik', 'image', 'dyskografia')):
                continue
            if m not in seen:
                seen.append(m)
    cache[key] = seen[:60]
    return cache[key]


def album_info(page, cache):
    """(year, [normalised track titles]) for a studio album article, else (None, [])."""
    key = f'album|{page}'
    if key in cache:
        y, tr = cache[key]
        return y, tr
    txt = page_text(page)
    time.sleep(PAUSE)
    result = (None, [])
    box = re.search(r'\{\{\s*([^\n|}]+infobox[^\n|}]*)', txt, re.I)
    if box and 'album' in box.group(1).lower():
        head = txt[:1500].lower()
        if not any(h in head for h in COMPILATION_HINT):
            y = re.search(r'\|\s*wydany\s*=[^\n]*?(\d{4})', txt)
            tracks = re.findall(r'^\s*#\s*(.+)$', txt, re.M)
            tracks = [clean_track(t) for t in tracks]
            tracks = [t for t in tracks if 2 < len(t) < 60]
            if y and tracks:
                result = (int(y.group(1)), tracks)
    cache[key] = list(result)
    return result


def main():
    apply = '--apply' in sys.argv
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    from verify_discogs import cache_key, PINNED
    dis = json.load(open('discogs_cache.json', encoding='utf-8'))

    with open(DECK, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])
    todo = [r for r in rows if r['track_id'] and r['year'].endswith('*')
            and not r['year'].endswith('**')
            and (r['artist'], r['title']) not in PINNED]

    by = collections.defaultdict(list)
    for r in todo:
        by[r['artist'].split(',')[0].strip()].append(r)
    print(f'{len(todo)} unverified cards across {len(by)} artists')

    hits, misses = [], 0
    try:
        for i, (artist, cards) in enumerate(sorted(by.items(), key=lambda x: -len(x[1])), 1):
            pages = album_pages(artist, cache)
            # earliest studio album containing each track
            best = {}
            for page in pages:
                y, tracks = album_info(page, cache)
                if not y:
                    continue
                tset = set(tracks)
                for r in cards:
                    t = norm(clean_title(r['title']))
                    if t in tset and (r['track_id'] not in best or y < best[r['track_id']][0]):
                        best[r['track_id']] = (y, page)
            for r in cards:
                if r['track_id'] in best:
                    y, page = best[r['track_id']]
                    hits.append((r, int(r['year'].rstrip('*')), y, page))
                else:
                    misses += 1
            if i % 20 == 0:
                print(f'  {i}/{len(by)} artists, {len(hits)} dated…', flush=True)
    finally:
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    changed = 0
    if apply:
        for r, ours, y, page in hits:
            d = dis.get(cache_key(r['artist'], r['title']))
            sure = d is not None and abs(d - y) <= 1
            new = str(y) if sure else f'{y}*'
            if r['year'] != new:
                changed += 1
            r['year'] = new
        with open(DECK, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fields)
            w.writeheader()
            w.writerows(rows)

    print(f'\nfound on a studio-album tracklist: {len(hits)}   not found: {misses}')
    for r, ours, y, page in sorted(hits, key=lambda x: -abs(x[1] - x[2]))[:30]:
        flag = '' if ours == y else f'  (was {ours})'
        print(f'   {y}  {r["artist"][:22]:<22} {r["title"][:28]:<28} [{page[:26]}]{flag}')
    if apply:
        print(f'\napplied, {changed} years changed')
    else:
        print('\n(report only -- re-run with --apply)')


if __name__ == '__main__':
    sys.exit(main())
