"""Verify card years against Discogs and clear the '*' from the ones it confirms.

Discogs is the only source that actually works for this catalogue. Measured against
15 songs with known years:

    Discogs     10/15 exact, 13/15 within a year
    Spotify      4/13   (tracks resolve to compilations)
    MusicBrainz  3/10   (thin Polish coverage)
    Wikidata    ~1/4    (most Polish songs have no item)

It is collector-maintained and catalogues original Polish pressings -- singles and LPs
with their real years -- which is exactly what Spotify lacks.

The rule, given the deck dates songs by SINGLE / first release:

  within 1 year   -> confirmed, star cleared
  Discogs earlier -> our year is probably too late; reported, never auto-applied
  Discogs later   -> Discogs is missing the original pressing; star kept, year untouched

Usage:  python verify_discogs.py [--apply]
        (without --apply it only reports, changing nothing)
"""
import csv, json, os, sys, time
import requests

from fetch_songs import load_env, norm

DECK = 'songs.csv'
CACHE = 'discogs_cache.json'
ALBUM_CACHE = 'album_cache.json'

# Years a human confirmed. No automated pass may overwrite these -- every one of them
# was found by someone noticing a wrong card, which is more evidence than any API gives.
PINNED = {
    ('Kombi', 'Słodkiego miłego życia'): '1984',
    ('Kombi', 'Black and White'): '1985',
    ('Kombii', 'Pokolenie'): '2004',
    ('Halina Frąckowiak', 'Bądź gotowy do drogi'): '1974',
    ('Ich Troje', 'A wszystko to bo ciebie kocham'): '1999',
    ('Myslovitz', 'Mieć czy być'): '2006',
}
UA = {'User-Agent': 'HitsterPL/0.1 +personal-use'}
TOLERANCE = 1
PAUSE = 1.1        # Discogs allows 60 authenticated requests a minute


def discogs_year(artist, title, token, cache):
    """Earliest Discogs release year for this track, or None."""
    key = f'{norm(artist)}|{norm(title)}'
    if key in cache:
        return cache[key]
    for attempt in range(3):
        r = requests.get('https://api.discogs.com/database/search', headers=UA, timeout=30,
                         params={'artist': artist, 'track': title, 'type': 'release',
                                 'per_page': 100, 'token': token})
        if r.status_code == 429:
            time.sleep(20)
            continue
        if r.status_code != 200:
            cache[key] = None
            return None
        years = [int(x['year']) for x in r.json().get('results', [])
                 if str(x.get('year', '')).isdigit()]
        cache[key] = min(years) if years else None
        time.sleep(PAUSE)
        return cache[key]
    cache[key] = None
    return None


def rewrite():
    """Reset every year from the sources: Discogs first, then Spotify, then keep ours.

    A year is left unstarred only when Discogs and Spotify agree with each other within
    a year. One source alone is adopted but stays starred -- Discogs was 10/15 exact on
    the spot check, good enough to use, not good enough to call verified.
    """
    from audit_years import looks_like_compilation
    dis = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    alb = json.load(open(ALBUM_CACHE, encoding='utf-8')) if os.path.exists(ALBUM_CACHE) else {}

    with open(DECK, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])

    changes, stats = [], {'discogs': 0, 'spotify': 0, 'kept': 0, 'pinned': 0}
    for r in rows:
        if not r['track_id']:
            continue
        ours = r['year'].rstrip('*')
        if (r['artist'], r['title']) in PINNED:
            r['year'] = PINNED[(r['artist'], r['title'])]
            stats['pinned'] += 1
            continue

        d = dis.get(f"{norm(r['artist'])}|{norm(r['title'])}")
        if d is not None and not (1950 <= d <= 2026):
            d = None                      # nonsense year, ignore the source
        a = alb.get(r['track_id'])
        sp = None
        if a and a['date'].isdigit() and not looks_like_compilation(a['album']):
            sp = int(a['date'])

        if d:
            new, src = d, 'discogs'
        elif sp:
            new, src = sp, 'spotify'
        else:
            new, src = int(ours) if ours.isdigit() else None, 'kept'
        if new is None:
            continue
        stats[src] += 1
        agreed = d is not None and sp is not None and abs(d - sp) <= 1
        r['year'] = f'{new}' if agreed else f'{new}*'
        if ours.isdigit() and new != int(ours):
            changes.append((new - int(ours), r['artist'], r['title'], ours, new, src))

    with open(DECK, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)

    starred = sum(1 for r in rows if r['year'].endswith('*'))
    print(f'sources: {stats}')
    print(f'{len(changes)} years changed; {starred} of {len(rows)} still starred\n')
    changes.sort(key=lambda x: -abs(x[0]))
    print('largest changes:')
    for gap, art, tit, old, new, src in changes[:30]:
        print(f'  {old:>5} -> {new}  ({gap:+3})  {art[:24]:<24} {tit[:28]:<28} [{src}]')


def from_spotify():
    """Take Spotify's album date as the year wherever Spotify has one.

    Explicitly requested. Recorded here because the numbers argue against it: measured
    over the whole deck, Spotify's date is too late on 229 of 341 cards, with a median
    overshoot of +38 years for 1960s songs and +24 for the 1980s. `release_date` is a
    property of the album a track sits on, not of the song, and old Polish music exists
    on Spotify almost only as compilations and remasters.

    Human-confirmed years in PINNED still win -- those were corrections someone made
    deliberately, and silently reversing them is never what anyone means.
    """
    alb = json.load(open(ALBUM_CACHE, encoding='utf-8')) if os.path.exists(ALBUM_CACHE) else {}
    with open(DECK, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])

    changes, taken, kept = [], 0, 0
    for r in rows:
        if not r['track_id']:
            continue
        if (r['artist'], r['title']) in PINNED:
            r['year'] = PINNED[(r['artist'], r['title'])]
            continue
        ours = r['year'].rstrip('*')
        c = alb.get(r['track_id'])
        if c and c['date'].isdigit():
            new = int(c['date'])
            if ours.isdigit() and new != int(ours):
                changes.append((new - int(ours), r['artist'], r['title'], ours, new))
            r['year'] = str(new)          # accepted as given, so no star
            taken += 1
        else:
            kept += 1

    with open(DECK, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)
    print(f'took Spotify year for {taken} cards, kept {kept}, {len(changes)} changed')
    changes.sort(key=lambda x: -abs(x[0]))
    print('\nlargest shifts:')
    for gap, art, tit, old, new in changes[:20]:
        print(f'  {old} -> {new}  ({gap:+3})  {art[:24]:<24} {tit[:30]}')


def main():
    if '--spotify' in sys.argv:
        return from_spotify()
    if '--rewrite' in sys.argv:
        return rewrite()
    apply = '--apply' in sys.argv
    token = load_env()['DISCOGS_TOKEN']
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}

    with open(DECK, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])

    confirmed, earlier, unknown = [], [], 0
    try:
        for i, r in enumerate([x for x in rows if x['track_id']], 1):
            ours = r['year'].rstrip('*')
            if not ours.isdigit():
                continue
            dy = discogs_year(r['artist'], r['title'], token, cache)
            if dy is None:
                unknown += 1
            elif abs(dy - int(ours)) <= TOLERANCE:
                confirmed.append(r)
                if apply:
                    r['year'] = ours            # verified: drop the star
            elif dy < int(ours):
                earlier.append((r, dy))         # our year is probably too late
                if apply:
                    r['year'] = ours + '*'
            if i % 40 == 0:
                print(f'  {i}…', flush=True)
    finally:
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    if apply:
        with open(DECK, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fields)
            w.writeheader()
            w.writerows(rows)

    print(f'\nconfirmed by Discogs: {len(confirmed)}')
    print(f'Discogs knows an earlier release ({len(earlier)}) -- likely our year is too late:')
    for r, dy in sorted(earlier, key=lambda x: int(x[0]['year'].rstrip('*')) - x[1],
                        reverse=True)[:40]:
        print(f"   ours {r['year']:<6} discogs {dy}   {r['artist'][:24]} - {r['title'][:30]}")
    print(f'not found on Discogs: {unknown}')
    if not apply:
        print('\n(report only -- re-run with --apply to clear stars)')


if __name__ == '__main__':
    sys.exit(main())
