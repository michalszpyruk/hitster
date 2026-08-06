"""Mark songs whose year could not be web-confirmed with a trailing '**'.

Usage: python mark_unverified.py <track_id> [<track_id> ...]
"""
import csv, sys


def main(args):
    ids = set(args)
    rows = list(csv.DictReader(open('songs.csv', encoding='utf-8')))
    seen = set()
    for r in rows:
        if r['track_id'] in ids and r['year'].endswith('*') and not r['year'].endswith('**'):
            r['year'] += '*'
            seen.add(r['track_id'])
    with open('songs.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    missing = ids - seen
    if missing:
        print(f'  (not found or already **: {missing})')
    print(f'marked {len(seen)} as unverified (**)')


if __name__ == '__main__':
    main(sys.argv[1:])
