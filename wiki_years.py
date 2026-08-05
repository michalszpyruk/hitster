"""Third opinion on card years, from Polish Wikipedia -> report, or --apply.

Wikipedia is different in kind from the other two sources. Discogs and Spotify report
when some *pressing* came out, which is why they only ever err late. A pl.wikipedia
song article states when the *song* was released, in a structured infobox field:

    |wykonawca = [[2 plus 1]]
    |album     = [[Teatr na drodze]]
    |wydany    = [[1978 w muzyce|1978]]

So it can legitimately move a year in either direction. The catch is coverage: only
about a third of the deck's songs have an article at all.

Two guards against matching the wrong page, which is what made a naive search useless:
the page title must BE the song title (optionally "... (singel)"), and the infobox
performer must match the card's artist.

Usage:  python wiki_years.py [--apply]
"""
import csv, json, os, re, sys, time
import requests

from fetch_songs import norm, artist_matches
from fetch_playlist import clean_title

API = 'https://pl.wikipedia.org/w/api.php'
UA = {'User-Agent': 'HitsterPL/0.1 (personal hobby project; asparagus.mike@gmail.com)'}
DECK = 'songs.csv'
CACHE = 'wiki_cache.json'
SUFFIXES = ('', '(singel)', '(piosenka)', '(utwór)')
PAUSE = 0.3


def page_text(title):
    try:
        r = requests.get(API, headers=UA, timeout=30,
                         params={'action': 'query', 'prop': 'revisions', 'rvprop': 'content',
                                 'rvslots': 'main', 'titles': title, 'format': 'json'})
        if r.status_code != 200:
            return ''
        for p in r.json().get('query', {}).get('pages', {}).values():
            if 'revisions' in p:
                return p['revisions'][0]['slots']['main']['*']
    except Exception:
        pass
    return ''


def wiki_year(artist, title, cache):
    """(year, page) from a song article whose performer matches, else (None, None)."""
    key = f'{norm(artist)}|{norm(title)}'
    if key in cache:
        return tuple(cache[key])
    first = artist.split(',')[0].strip()
    clean = clean_title(title)
    result = (None, None)
    for suffix in SUFFIXES:
        page = f'{clean} {suffix}'.strip()
        txt = page_text(page)
        time.sleep(PAUSE)
        # Only a song/single article. An album infobox dates the record, not the song:
        # "Nie domykajmy drzwi" resolves to a 1990 compilation for a 1972 song.
        box = re.search(r'\{\{\s*([^\n|}]+infobox[^\n|}]*)', txt, re.I)
        kind = box.group(1).strip().lower() if box else ''
        if not kind or 'album' in kind:
            continue
        perf = re.search(r'\|\s*wykonawca\s*=\s*([^\n]+)', txt)
        if perf:
            names = re.findall(r'\[\[([^\]|]+)', perf.group(1)) or [perf.group(1)]
            if not any(artist_matches(first, n.strip()) for n in names):
                continue          # an article about a different act's song of that name
        m = re.search(r'\|\s*wydany\s*=[^\n]*?(\d{4})', txt)
        if m:
            result = (int(m.group(1)), page)
            break
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
    cards = [r for r in rows if r['track_id'] and r['year'].endswith('*')]
    print(f'checking {len(cards)} starred cards against pl.wikipedia…')

    agreed, wiki_only, none = [], [], 0
    try:
        for i, r in enumerate(cards, 1):
            if (r['artist'], r['title']) in PINNED:
                continue
            y, page = wiki_year(r['artist'], r['title'], cache)
            if y is None:
                none += 1
                continue
            ours = int(r['year'].rstrip('*'))
            d = dis.get(cache_key(r['artist'], r['title']))
            # Never later, for the same reason as everywhere else: a "singel" article
            # often documents a re-release ("Nie ma fal" is a 2015 song with a 2018
            # single page). Only an earlier year is evidence.
            if y > ours:
                wiki_only.append((r, ours, y, dis.get(cache_key(r['artist'], r['title'])), page))
                continue
            if d is not None and abs(d - y) <= 1:
                # Two independent sources, one of which describes the song rather than
                # a pressing. Strong enough to set the year and drop the star.
                agreed.append((r, ours, y, d, page))
                if apply:
                    r['year'] = str(y)
            else:
                wiki_only.append((r, ours, y, d, page))
            if i % 50 == 0:
                print(f'  {i}/{len(cards)}…', flush=True)
    finally:
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
        if apply:
            with open(DECK, 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fields)
                w.writeheader()
                w.writerows(rows)

    print(f'\nconfirmed by Wikipedia + Discogs: {len(agreed)}')
    for r, ours, y, d, page in sorted(agreed, key=lambda x: -abs(x[1] - x[2]))[:30]:
        mark = '' if ours == y else f'  (was {ours})'
        print(f'   {y}  {r["artist"][:22]:<22} {r["title"][:28]:<28}{mark}')
    print(f'\nWikipedia only, Discogs disagrees or missing ({len(wiki_only)}) -- needs a human:')
    for r, ours, y, d, page in sorted(wiki_only, key=lambda x: -abs(x[1] - x[2]))[:25]:
        print(f'   ours {ours} / wiki {y} / discogs {d}   {r["artist"][:20]:<20} {r["title"][:26]}')
    print(f'\nno Wikipedia article: {none}')
    if not apply:
        print('\n(report only -- re-run with --apply)')


if __name__ == '__main__':
    sys.exit(main())
