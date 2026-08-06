"""Apply web-verified years to songs.csv and seed.csv, and record them.

Every year here came from reading a source that states it outright, so they are
recorded in websearch_fixes.json and treated as settled: no automated pass may
overwrite one. Usage: python apply_years.py '<artist>|<title>|<year>' ...
"""
import csv, json, os, sys

STORE = 'websearch_fixes.json'


def main(args):
    fixes = {}
    for a in args:
        artist, title, year = a.split('|')
        fixes[(artist.strip(), title.strip())] = year.strip()
    store = json.load(open(STORE, encoding='utf-8')) if os.path.exists(STORE) else {}
    for (a, t), y in fixes.items():
        store[f'{a}|{t}'] = y
    json.dump(store, open(STORE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    seen = set()
    for path in ('songs.csv', 'seed.csv'):
        rows = list(csv.DictReader(open(path, encoding='utf-8')))
        for r in rows:
            k = (r['artist'].strip(), r['title'].strip())
            if k in fixes and r['year'] != fixes[k]:
                if path == 'songs.csv':
                    print(f"  {r['artist'][:24]:<24} {r['title'][:30]:<30} {r['year']:<8} -> {fixes[k]}")
                    seen.add(k)
                r['year'] = fixes[k]
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    missing = [k for k in fixes if k not in seen]
    if missing:
        print(f'  (already at that year or no such card: {missing})')
    print(f'{len(store)} web-verified years on record')


if __name__ == '__main__':
    main(sys.argv[1:])
