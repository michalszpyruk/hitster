"""Pull tracks from public Spotify playlists -> playlist_new.csv.

The Web API is no good for this: /playlists/{id}/tracks answers 403 and /items
answers "Valid user authentication required" for a client-credentials app. The public
embed page carries the whole track list in its __NEXT_DATA__ payload and needs no
login or quota at all -- it even works on Spotify's own editorial playlists.

It is an undocumented page, so it may change without notice. It fails loudly rather
than silently: no payload means an immediate error, not an empty deck.

Note the embed returns at most 100 tracks per playlist, and carries NO release date,
so the year column comes out blank and must be filled in by hand. That is not laziness
-- Spotify's own release_date is the remaster year and dates "Nie spoczniemy" to 2025.

Usage:  python fetch_playlist.py <playlist-url-or-id> [more urls...]
"""
import csv, json, os, re, sys
import requests

from fetch_songs import norm

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
DECK = 'songs.csv'
OUT = 'playlist_new.csv'
MAX_PER_PLAYLIST = 100   # the embed payload is capped here


VERSION_TAG = re.compile(
    r'\b(remaster(ed)?|live|mix|remix|version|edit|mono|stereo|ost|soundtrack|'
    r'reedycja|wydanie|feat\.?|19\d\d|20\d\d)\b', re.I)


def clean_title(title):
    """Readable title with version noise removed, for printing on the card.

    "Cykady na Cykladach - 2011 Remaster" -> "Cykady na Cykladach", but
    "W Kinie W Lublinie - Kochaj Mnie" is left alone: that tail is part of the name.
    """
    t = title.strip()
    for _ in range(3):
        stripped = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*$',
                          lambda m: '' if VERSION_TAG.search(m.group(0)) else m.group(0), t)
        parts = stripped.rsplit(' - ', 1)
        if len(parts) == 2 and VERSION_TAG.search(parts[1]):
            stripped = parts[0]
        if stripped == t or not stripped.strip():
            break
        t = stripped
    return t.strip() or title.strip()


def base_title(title):
    """Strip version noise so "Whisky - 2003 Remaster" matches plain "Whisky".

    Only trailing " - ..." segments and bracketed groups that actually look like
    version tags are removed -- blindly cutting at " - " would mangle real titles.
    """
    t = title
    for _ in range(3):                       # titles can carry more than one tag
        t = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*$',
                   lambda m: '' if VERSION_TAG.search(m.group(0)) else m.group(0), t)
        parts = t.rsplit(' - ', 1)
        if len(parts) == 2 and VERSION_TAG.search(parts[1]):
            t = parts[0]
    return norm(t)


def playlist_id(s):
    m = re.search(r'playlist[/:]([A-Za-z0-9]{22})', s) or re.fullmatch(r'([A-Za-z0-9]{22})', s.strip())
    if not m:
        sys.exit(f'not a playlist link or id: {s}')
    return m.group(1)


def fetch(pid):
    """Return (playlist_name, [{track_id, artist, title}, ...])."""
    r = requests.get(f'https://open.spotify.com/embed/playlist/{pid}', headers=UA, timeout=30)
    r.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  r.text, re.S)
    if not m:
        sys.exit(f'{pid}: no __NEXT_DATA__ payload -- Spotify changed the embed page.')
    entity = json.loads(m.group(1))['props']['pageProps']['state']['data']['entity']
    rows = []
    for t in entity.get('trackList') or []:
        tid = (t.get('uri') or '').split(':')[-1]
        if len(tid) == 22 and t.get('title'):
            rows.append({'track_id': tid,
                         'artist': (t.get('subtitle') or '').strip(),
                         'title': t['title'].strip()})
    return entity.get('name') or pid, rows


def merge():
    """Append rows from playlist_new.csv that have a year into songs.csv.

    Rows with a blank year are skipped, not defaulted. Neither Spotify (4/13 correct
    on a spot check) nor MusicBrainz (3/10) can date this catalogue, so a missing
    year means nobody knows it yet -- and a card with a wrong year breaks the game
    more quietly than no card at all.
    """
    with open(DECK, encoding='utf-8') as f:
        deck = list(csv.DictReader(f))
        fields = list(deck[0])
    have = {r['track_id'] for r in deck}
    added, skipped = 0, 0
    for r in csv.DictReader(open(OUT, encoding='utf-8')):
        if not r['year'].strip():
            skipped += 1
            continue
        if r['track_id'] in have:
            continue
        deck.append({**{k: '' for k in fields}, 'track_id': r['track_id'],
                     'artist': r['artist'], 'title': r['title'], 'year': r['year'].strip()})
        have.add(r['track_id'])
        added += 1
    with open(DECK, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(deck)
    print(f'{DECK}: +{added} cards (now {len(deck)}). {skipped} skipped for having no year.')


def main(args):
    if not args:
        sys.exit(__doc__)
    if args[0] == '--merge':
        return merge()

    have_ids, have_titles = set(), set()
    if os.path.exists(DECK):
        with open(DECK, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                have_ids.add(r['track_id'])
                have_titles.add(base_title(r['title']))

    new, seen, seen_titles = [], set(), set()
    for arg in args:
        pid = playlist_id(arg)
        name, rows = fetch(pid)
        kept = 0
        for r in rows[:MAX_PER_PLAYLIST]:
            if r['track_id'] in have_ids or r['track_id'] in seen:
                continue
            bt = base_title(r['title'])
            # Two ids for one song: a remaster in the deck and the original here, or
            # the same track twice in a playlist. Same artist means it really is a
            # duplicate; a different artist means a cover, which is worth keeping.
            key = (norm(r['artist']), bt)
            if bt in have_titles or key in seen_titles:
                continue
            seen.add(r['track_id'])
            seen_titles.add(key)
            r['check'] = ''
            r['year'] = ''
            new.append(r)
            kept += 1
        print(f'{name}: {len(rows)} tracks, {kept} new')

    with open(OUT, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, ['track_id', 'artist', 'title', 'year', 'check'])
        w.writeheader()
        w.writerows(new)
    dups = sum(1 for r in new if r['check'])
    print(f'\n{OUT}: {len(new)} new tracks ({dups} flagged as possible duplicates).')
    print('Fill in the year column, then merge into songs.csv.')


if __name__ == '__main__':
    main(sys.argv[1:])
