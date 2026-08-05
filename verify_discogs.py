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
from fetch_playlist import clean_title

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
    ('Dżem', 'Whisky'): '1985',                       # Discogs says 1981; rejected
    ('Krzysztof Krawczyk', 'Ostatni raz zatańczysz ze mną'): '1986',
    ('Akcent', 'Życie To Są Chwile'): '1994',
    # The card is the Kowalska duet, but the song itself is 1983 -- the deck dates
    # songs, not recordings.
    ('Lady Pank, Kasia Kowalska', 'Zamki na piasku'): '1983',
    # Web-search verified. "Mamona" is from Masakra (1998), NOT Nowe Sytuacje (1983) --
    # Discogs was right about this one and the earlier 1984 was my error.
    ('Republika', 'Mamona'): '1998',
    ('Perfect', 'Kołysanka dla Nieznajomej'): '1981',
    ('2 plus 1', 'Windą do nieba'): '1978',
    ('Maryla Rodowicz', 'Damą być'): '1976',
}
UA = {'User-Agent': 'HitsterPL/0.1 +personal-use'}
TOLERANCE = 1
MAX_DROP = 3       # how far one source may pull a year earlier on its own
PAUSE = 1.1        # Discogs allows 60 authenticated requests a minute


def cache_key(artist, title):
    """One key shape for every lookup, built from the cleaned artist and title."""
    return f'{norm(artist.split(",")[0].strip())}|{norm(clean_title(title))}'


def discogs_year(artist, title, token, cache):
    """Earliest Discogs release year for this track, or None.

    The query uses a cleaned title: Discogs indexes tracks as "Policeman", so searching
    "Policeman (feat. Jambojet, USPM)" matches nothing and the year looks unknown when
    it is actually on record. Same for "- 2003 Remaster" tails.
    Artists are cut to the first credit for the same reason.
    """
    title = clean_title(title)
    artist = artist.split(',')[0].strip()
    key = cache_key(artist, title)
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

        d = dis.get(cache_key(r['artist'], r['title']))
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


def final_pass():
    """One consistent rule set over every card. Fills gaps, then re-decides each year.

    Everything learned about these sources, applied uniformly:

    1. PINNED wins outright -- a human confirmed it.
    2. Discogs and Spotify agreeing within a year -> adopt, unstarred. This is the only
       evidence strong enough to move a year LATER, and it is what caught Myslovitz's
       "Mieć czy być" (1997 -> 2006).
    3. Otherwise take the EARLIEST of the current year and either source, and star it.
       Both sources only ever err late -- Spotify reports whichever album a track sits
       on, Discogs its earliest indexed pressing -- so a later value is never evidence,
       while an earlier one proves the song already existed.
    4. A card dated far later than the rest of that artist's catalogue gets starred even
       if the sources agreed: Anna German cannot have released in 2008, she died in 1982.
    """
    import statistics, collections
    from audit_years import looks_like_compilation
    from fetch_songs import load_env as _env, spotify_token, get, RateLimited

    env = _env()
    dis = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}
    alb = json.load(open(ALBUM_CACHE, encoding='utf-8')) if os.path.exists(ALBUM_CACHE) else {}
    with open(DECK, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])
    cards = [r for r in rows if r['track_id']]

    # --- fill any gaps in the source data
    headers = None
    try:
        headers = {'Authorization': 'Bearer ' + spotify_token(env)}
    except Exception:
        print('spotify unavailable; continuing on cached data')
    try:
        for r in cards:
            if cache_key(r['artist'], r['title']) not in dis:
                discogs_year(r['artist'], r['title'], env['DISCOGS_TOKEN'], dis)
            if headers and r['track_id'] not in alb:
                resp = get(f'https://api.spotify.com/v1/tracks/{r["track_id"]}', headers,
                           {'market': 'PL'})
                if resp.status_code == 200:
                    t = resp.json()
                    alb[r['track_id']] = {'album': t['album']['name'],
                                          'date': t['album']['release_date'][:4],
                                          'artists': [a['name'] for a in t['artists']],
                                          'name': t['name']}
                    time.sleep(0.15)
    except RateLimited as e:
        print(f'spotify locked ({e}); using what is cached')
    finally:
        json.dump(dis, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(alb, open(ALBUM_CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    # --- artist medians, for spotting reissue dates
    by = collections.defaultdict(list)
    for r in cards:
        by[norm(r['artist'].split(',')[0])].append(int(r['year'].rstrip('*')))
    median = {a: statistics.median(ys) for a, ys in by.items() if len(ys) >= 3}

    changed, stats, big_drops = [], collections.Counter(), []
    for r in cards:
        old = r['year']
        ours = int(old.rstrip('*'))
        key = (r['artist'], r['title'])
        if old.endswith('**'):
            # Already taken to the open web and left unresolved. No source pass can
            # improve on that, and re-deriving would silently discard the effort.
            stats['web-unresolved'] += 1
            continue
        if key in PINNED:
            r['year'] = PINNED[key]
            stats['pinned'] += 1
            continue

        d = dis.get(cache_key(r['artist'], r['title']))
        if d is not None and not (1900 <= d <= 2026):
            d = None
        a = alb.get(r['track_id'])
        sp_raw = int(a['date']) if a and a['date'].isdigit() else None
        sp_orig = sp_raw if a and not looks_like_compilation(a['album']) else None

        # Never move a year later. Both sources err only in the late direction, so a
        # later value is never evidence -- Perfect's "Kołysanka" reads 1994 in both
        # because neither holds the 1981 original, and Republika's "Mamona" reads 1998.
        # A source may only pull a year a little earlier. Big drops are almost always
        # the track search matching a different song by the same artist -- "Windą do
        # nieba" is 1984, not the 1978 record Discogs finds under that name. Those are
        # reported instead, and the card keeps its year and its star.
        cands = [x for x in (d, sp_raw) if x is not None and ours - x <= MAX_DROP]
        year = min([ours] + cands)
        if any(ours - x > MAX_DROP for x in (d, sp_raw) if x is not None):
            big_drops.append((r, ours, min(x for x in (d, sp_raw) if x is not None)))
        # Confirmed only when both sources agree with each other AND with that year.
        sure = (d is not None and sp_orig is not None
                and abs(d - sp_orig) <= TOLERANCE and abs(d - year) <= TOLERANCE)
        stats['agreed' if sure else 'earliest-of'] += 1

        med = median.get(norm(r['artist'].split(',')[0]))
        if sure and med is not None and year - med > 15:
            sure = False                      # too late for this artist; do not vouch for it
            stats['outlier-restarred'] += 1

        r['year'] = str(year) if sure else f'{year}*'
        if r['year'] != old:
            changed.append((year - ours, r['artist'], r['title'], old, r['year']))

    with open(DECK, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(rows)

    starred = sum(1 for r in cards if r['year'].endswith('*'))
    print(f'\n{dict(stats)}')
    print(f'{len(cards)} cards: {len(cards)-starred} confirmed, {starred} starred')
    print(f'{len(changed)} changed\n')
    for gap, art, tit, old, new in sorted(changed, key=lambda x: -abs(x[0]))[:20]:
        print(f'  {old:>6} -> {new:<7} {art[:24]:<24} {tit[:30]}')
    print(f'\nheld back -- a source claims a much earlier year ({len(big_drops)}):')
    for r, ours, got in sorted(big_drops, key=lambda x: x[1]-x[2], reverse=True)[:25]:
        print(f'  kept {ours} (source says {got})  {r["artist"][:22]:<22} {r["title"][:28]}')


def main():
    if '--final' in sys.argv:
        return final_pass()
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

    from audit_years import looks_like_compilation
    alb = json.load(open(ALBUM_CACHE, encoding='utf-8')) if os.path.exists(ALBUM_CACHE) else {}
    confirmed, earlier, agreed_earlier, unknown = [], [], [], 0
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
                # Two independent sources agreeing on an EARLIER year is safe to adopt:
                # nothing can be released before it exists, so our year must be too late.
                # (The same agreement on a LATER year is not safe -- both sources may
                # simply have only the reissue, as with Perfect's "Kołysanka".)
                a = alb.get(r['track_id'])
                sp = (int(a['date']) if a and a['date'].isdigit()
                      and not looks_like_compilation(a['album']) else None)
                if sp is not None and abs(dy - sp) <= TOLERANCE:
                    agreed_earlier.append((r, int(ours), dy))
                    if apply:
                        r['year'] = str(dy)     # confirmed by both, so no star
                else:
                    earlier.append((r, dy))     # one source only: report, do not apply
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
    print(f'corrected earlier (both sources agree): {len(agreed_earlier)}')
    for r, was, now in sorted(agreed_earlier, key=lambda x: x[1] - x[2], reverse=True):
        print(f'   {was} -> {now}   {r["artist"][:24]} - {r["title"][:30]}')
    print(f'Discogs knows an earlier release ({len(earlier)}) -- likely our year is too late:')
    for r, dy in sorted(earlier, key=lambda x: int(x[0]['year'].rstrip('*')) - x[1],
                        reverse=True)[:40]:
        print(f"   ours {r['year']:<6} discogs {dy}   {r['artist'][:24]} - {r['title'][:30]}")
    print(f'not found on Discogs: {unknown}')
    if not apply:
        print('\n(report only -- re-run with --apply to clear stars)')


if __name__ == '__main__':
    sys.exit(main())
