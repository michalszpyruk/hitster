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


def main():
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
