"""Resolve seed.csv (artist, title, year) to Spotify track IDs -> songs.csv.

The year in seed.csv is authoritative. Spotify's release_date is useless for the
Polish back catalogue (it reports the newest remaster: "Nie spoczniemy" comes back
as 2025 for a 1977 song), and MusicBrainz only agreed with the truth 3 times out of
10 on a spot check. So both are recorded as reference columns, and MusicBrainz is
used for exactly one narrow job: if it knows of a release EARLIER than the seed year,
the seed year is probably too late and the row gets flagged for review.

Usage:  python fetch_songs.py
"""
import csv, json, os, re, sys, time, unicodedata
import requests

MARKET = 'PL'
SEED = 'seed.csv'
OUT = 'songs.csv'
MB_CACHE = 'mb_cache.json'
SP_CACHE = 'spotify_cache.json'
UA = {'User-Agent': 'HitsterPL/0.1 (personal project; https://github.com/)'}
# Spotify answers 429 with a Retry-After measured in *hours* once a development-mode
# app exhausts its quota (observed: 5940s). Sleeping that out would look like a hang,
# so past this point we save progress and quit instead.
MAX_BACKOFF = 60


class RateLimited(Exception):
    """Spotify locked us out for longer than we are willing to wait."""


def norm(s):
    """Fold case, strip Polish diacritics and punctuation, for comparing titles.

    NFKD handles the accented vowels, but 'ł' is a distinct letter with no
    decomposition -- without mapping it by hand it gets stripped as punctuation, so
    "Małgośka" would stop matching a source that spells it "Malgoska".
    """
    s = s.lower().replace('ł', 'l')
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '', s)


def artist_matches(seed, found):
    """Is `found` (Spotify's spelling) the same act as `seed` (ours)?

    Substring matching is needed because Spotify credits "Niemen" where the seed says
    "Czesław Niemen" -- but applying it to short names is dangerous, since "Hey" or
    "Kult" is a substring of plenty of unrelated bands. So substrings only count once
    the shorter name is long enough to be distinctive.
    """
    a, b = norm(seed), norm(found)
    if a == b:
        return True
    return min(len(a), len(b)) >= 5 and (a in b or b in a)


def load_env(path='.env'):
    env = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


def spotify_token(env):
    r = requests.post('https://accounts.spotify.com/api/token',
                      data={'grant_type': 'client_credentials'},
                      auth=(env['SPOTIFY_CLIENT_ID'], env['SPOTIFY_CLIENT_SECRET']),
                      timeout=30)
    r.raise_for_status()
    return r.json()['access_token']


def get(url, headers, params, tries=4):
    """GET with a bounded 429 back-off."""
    for _ in range(tries):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code != 429:
            return r
        wait = int(r.headers.get('Retry-After', 2))
        if wait > MAX_BACKOFF:
            raise RateLimited(f'Spotify asked us to wait {wait}s (~{wait // 60} min)')
        time.sleep(wait + 1)
    return r


def find_track(headers, artist, title):
    """Return (track_id, spotify_year, exact_title_match) or (None, None, False).

    Tries the fielded query first because it is far more precise, then falls back
    to a loose query -- Spotify's field search misses when the seed spelling of the
    artist differs slightly from theirs (e.g. "Czesław Niemen" vs "Niemen").
    """
    queries = [f'artist:{artist} track:{title}', f'{artist} {title}']
    best = (None, None, False)
    for q in queries:
        r = get('https://api.spotify.com/v1/search', headers,
                {'q': q, 'type': 'track', 'limit': 10, 'market': MARKET})
        if r.status_code != 200:
            continue
        for t in r.json().get('tracks', {}).get('items') or []:
            if t.get('is_playable') is False:
                continue
            names = [a['name'] for a in t.get('artists', [])]
            if not any(artist_matches(artist, n) for n in names):
                continue
            year = (t.get('album', {}).get('release_date') or '')[:4] or None
            exact = norm(t['name']) == norm(title)
            if exact:
                return t['id'], year, True
            if best[0] is None:
                best = (t['id'], year, False)
    return best


def mb_earliest_year(artist, title, cache):
    """Earliest first-release year MusicBrainz knows for this recording, or None.

    Only a lower bound: MusicBrainz frequently lacks the original Polish pressing,
    so a value LATER than the seed year proves nothing and is ignored by the caller.
    """
    key = f'{norm(artist)}|{norm(title)}'
    if key in cache:
        return cache[key]
    r = requests.get('https://musicbrainz.org/ws/2/recording', headers=UA, timeout=30,
                     params={'query': f'artist:"{artist}" AND recording:"{title}"',
                             'fmt': 'json', 'limit': 100})
    time.sleep(1.1)  # MusicBrainz allows 1 request/second, and enforces it.
    years = []
    if r.status_code == 200:
        for rec in r.json().get('recordings', []):
            if norm(rec.get('title', '')) != norm(title):
                continue
            credits = [c['artist']['name'] for c in rec.get('artist-credit', [])
                       if isinstance(c, dict) and 'artist' in c]
            if not any(norm(artist) == norm(n) for n in credits):
                continue
            d = rec.get('first-release-date') or ''
            if len(d) >= 4 and d[:4].isdigit():
                years.append(int(d[:4]))
    cache[key] = min(years) if years else None
    return cache[key]


def flag(seed_year, mb_year, track_id, exact):
    """Reasons this row needs a human look. Empty string means it is fine."""
    reasons = []
    if not track_id:
        reasons.append('NO-SPOTIFY-MATCH')
    elif not exact:
        reasons.append('FUZZY-TITLE')
    # MusicBrainz found something released before the seed year -> seed likely too late.
    if mb_year and seed_year > mb_year + 2:
        reasons.append(f'YEAR?-mb{mb_year}')
    return ' '.join(reasons)


def load_cache(path):
    return json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}


def save_caches(mb, sp):
    json.dump(mb, open(MB_CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(sp, open(SP_CACHE, 'w', encoding='utf-8'), ensure_ascii=False)


def main():
    env = load_env()
    headers = {'Authorization': 'Bearer ' + spotify_token(env)}
    mb_cache, sp_cache = load_cache(MB_CACHE), load_cache(SP_CACHE)

    with open(SEED, encoding='utf-8') as f:
        seed = list(csv.DictReader(f))

    rows, seen, stopped = [], set(), None
    try:
        for i, s in enumerate(seed, 1):
            artist, title = s['artist'].strip(), s['title'].strip()
            key = f'{norm(artist)}|{norm(title)}'
            if key in seen:
                print(f'  [{i}/{len(seed)}] duplicate, skipped: {artist} - {title}')
                continue
            seen.add(key)

            if key in sp_cache:
                track_id, sp_year, exact = sp_cache[key]
            else:
                track_id, sp_year, exact = find_track(headers, artist, title)
                sp_cache[key] = [track_id, sp_year, exact]
            mb_year = mb_earliest_year(artist, title, mb_cache)
            seed_year = int(s['year'])
            note = flag(seed_year, mb_year, track_id, exact)
            rows.append({'track_id': track_id or '', 'artist': artist, 'title': title,
                         'year': seed_year, 'spotify_year': sp_year or '',
                         'mb_year': mb_year or '', 'check': note})
            print(f'  [{i}/{len(seed)}] {artist} - {title} -> {track_id or "MISS"} {note}',
                  flush=True)
    except RateLimited as e:
        stopped = e
    finally:
        save_caches(mb_cache, sp_cache)

    if stopped:
        # Everything resolved so far is cached, so re-running resumes rather than restarts.
        print(f'\nStopped: {stopped}.')
        print(f'Progress for {len(rows)}/{len(seed)} songs is cached -- just re-run '
              f'fetch_songs.py once the limit clears. No work is lost.')
        return 1

    # songs.csv is hand-edited after the first run; never overwrite that work.
    out = OUT
    if os.path.exists(OUT):
        out = 'songs.new.csv'
        print(f'\n{OUT} exists (probably hand-edited) -- writing {out} instead.')
    with open(out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['track_id', 'artist', 'title', 'year',
                               'spotify_year', 'mb_year', 'check'])
        w.writeheader()
        w.writerows(rows)

    usable = [r for r in rows if r['track_id']]
    flagged = [r for r in rows if r['check']]
    print(f'\n{out}: {len(rows)} rows, {len(usable)} playable, {len(flagged)} need review')
    for r in flagged:
        print(f'  {r["check"]:<22} {r["artist"]} - {r["title"]} (seed {r["year"]})')


if __name__ == '__main__':
    sys.exit(main())
