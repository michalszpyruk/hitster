"""Flag cards whose year disagrees with a plausible original album -> audit.csv.

Spotify's release_date is only useless when the track resolves to a compilation
("Złota Kolekcja", "The Best", "Singles Collection") -- those carry the compilation's
date. When a track sits on what looks like an original album, the date is usually
right, and a big disagreement with our year means our year is probably wrong.

That is how "Kombi - Pokolenie, 1985" was caught: the track is Kombii's "Pokolenie"
from C.D. (2004).

This only ever flags. It never edits songs.csv, because the heuristic is a hint and
the year on the card has to stay a human decision.

Usage:  python audit_years.py
"""
import csv, json, os, sys, time
import requests

from fetch_songs import load_env, spotify_token, get, artist_matches, RateLimited

DECK = 'songs.csv'
OUT = 'audit.csv'
CACHE = 'album_cache.json'
TOLERANCE = 1          # a year either way is normal pressing drift

# Anything whose album name looks like this carries the reissue's date, not the song's.
COMPILATION = ('best', 'greatest', 'złota', 'zlota', 'kolekcja', 'collection',
               'singles', 'hits', 'antologia', 'platynowa', 'gwiazdy', 'największe',
               'najwieksze', 'the very best', 'ballady', 'remaster', 'live',
               'koncert', 'zestaw', 'jubileusz', 'wszystkie')


def looks_like_compilation(album):
    a = album.lower()
    return any(w in a for w in COMPILATION)


def main():
    headers = {'Authorization': 'Bearer ' + spotify_token(load_env())}
    cache = json.load(open(CACHE, encoding='utf-8')) if os.path.exists(CACHE) else {}

    with open(DECK, encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r['track_id']]

    flagged, stopped = [], None
    try:
        for i, r in enumerate(rows, 1):
            tid = r['track_id']
            if tid not in cache:
                resp = get(f'https://api.spotify.com/v1/tracks/{tid}', headers,
                           {'market': 'PL'})
                if resp.status_code != 200:
                    continue
                t = resp.json()
                cache[tid] = {'album': t['album']['name'],
                              'date': t['album']['release_date'][:4],
                              'artists': [a['name'] for a in t['artists']],
                              'name': t['name']}
                time.sleep(0.15)
            c = cache[tid]
            reasons = []
            # A track credited to someone else is usually the wrong track entirely.
            # This is what "Kombi - Pokolenie" really was: the record says Kombii.
            if not any(artist_matches(r['artist'], a) for a in c['artists']):
                reasons.append('ARTIST-MISMATCH')
            # Extra credited performers on a solo-billed classic almost always mean a
            # modern duet or remix rather than the original recording -- the game would
            # play a 2025 remake of a 1973 song.
            elif len(c['artists']) > 1 and ',' not in r['artist'] and ' i ' not in r['artist']:
                reasons.append('EXTRA-ARTIST')
            if c['date'].isdigit() and not looks_like_compilation(c['album']):
                gap = int(c['date']) - int(r['year'])
                # Earlier than our year on an original-looking album is the strong
                # signal: nothing can be released before its own release. Later is
                # almost always just a reissue and says nothing.
                if gap < -TOLERANCE:
                    reasons.append(f'ALBUM-EARLIER-{c["date"]}')
                elif gap > 15:
                    reasons.append(f'FAR-LATER-{c["date"]}')
            if reasons:
                flagged.append({'track_id': tid, 'artist': r['artist'], 'title': r['title'],
                                'our_year': r['year'], 'album_year': c['date'],
                                'album': c['album'], 'why': ' '.join(reasons),
                                'spotify_artist': ', '.join(c['artists'])})
            if i % 25 == 0:
                print(f'  {i}/{len(rows)}…', flush=True)
    except RateLimited as e:
        stopped = e
    finally:
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False)

    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['track_id', 'artist', 'title', 'our_year', 'album_year',
                               'album', 'why', 'spotify_artist'])
        w.writeheader()
        w.writerows(flagged)
    if stopped:
        print(f'Stopped early: {stopped}. Progress cached -- re-run to continue.')
    print(f'\n{len(cache)}/{len(rows)} tracks checked, {len(flagged)} suspicious -> {OUT}')
    for r in sorted(flagged, key=lambda x: x['why']):
        print(f"  {r['why']:<22} ours={r['our_year']}  {r['artist']} - {r['title'][:30]}")
        print(f"      spotify: {r['spotify_artist'][:34]} | {r['album'][:34]} ({r['album_year']})")


if __name__ == '__main__':
    sys.exit(main())
