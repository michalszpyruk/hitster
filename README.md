# Hitster PL

A personal-use Hitster clone for Polish music: a printed deck with a QR code on the front and
artist / title / year on the back, plus a phone app that scans a card, plays the track through
Spotify, and keeps the answer hidden until you tap Reveal.

## Why the year comes from a hand-curated list

Spotify's `release_date` is the *newest remaster*, not the original release, and for the Polish
back catalogue it is wildly wrong:

| Song | Truth | Spotify says | MusicBrainz says |
|---|---|---|---|
| Czerwone Gitary – Nie spoczniemy | 1977 | **2025** | 1991 |
| Perfect – Autobiografia | 1981 | 2003 | 1982 |
| Maanam – Kocham Cię, Kochanie Moje | 1980 | 1995 | 1991 |

MusicBrainz was exact on only 3 of 10 spot-checked Polish songs, and Spotify 4 of 13. Since the
entire game is "place the song on a timeline", the year has to be trustworthy — so `seed.csv`
holds curated years and is the source of truth. MusicBrainz is used for one narrow job: if it
knows of a release *earlier* than the seed year, the row is flagged for review.

## The year on a card is the SINGLE / first release

Not the album. *Patointeligencja* is 2019 (single), not 2020 (album); *Kombinat* is 1982, not
1983. This matches how Hitster dates songs and how people remember hearing them.

Two consequences worth remembering before "fixing" anything:

- A card sitting one or two years *before* its album is normal, not an error. That is why
  `audit_years.py` uses `TOLERANCE = 1` and only treats an *earlier* album as evidence —
  nothing can be released before its own release, but plenty is re-released after.
- Because of that tolerance, an off-by-one year is invisible to every automated check here.
  Those only get caught by someone who knows the song. Kombi's *Słodkiego miłego życia*
  (1983 → 1984) and *Black and White* (1984 → 1985) were both found that way.

## A `*` after the year means unconfirmed

`1966*` prints with a small superscript star on the card and shows in the app's Reveal.
It means nobody has verified that year — not that it is wrong.

A year is left clean only when Spotify places the track on an original-looking album 0–2
years after it. Currently 114 of 195 cards are starred, because for pre-1990 Polish music
Spotify carries only compilations, so there is nothing to check against.

Fix them as you notice them: edit `songs.csv` (and `seed.csv`, so a regeneration does not
bring the old value back), drop the `*`, and re-run `make_cards.py`. Everything that does
arithmetic on a year strips the star first — `test_cards.py` covers that.

## Verifying years with Discogs

```bash
python verify_discogs.py            # report only
python verify_discogs.py --apply    # clear the star from confirmed years
```

Measured against 15 songs with known years, Discogs is the only source that works:

| Source | Exact |
|---|---|
| **Discogs** | **10/15** (13/15 within a year) |
| Spotify `release_date` | 4/13 — tracks resolve to compilations |
| MusicBrainz | 3/10 — thin Polish coverage |
| Wikidata | ~1/4 — dated Kombii's *Pokolenie* to **1955** |

It is collector-maintained and catalogues original Polish pressings, which is exactly what
Spotify lacks. Running it took the deck from 114 confirmed years to 191.

The rule:

- **within 1 year** → confirmed, star cleared
- **Discogs earlier** → our year is probably too late; reported but *never* applied
  automatically, because the `track` search sometimes matches a different song by the
  same artist on an older release
- **Discogs later** → Discogs is missing the original pressing; the star stays and the
  year is left alone

Needs `DISCOGS_TOKEN` in `.env` (discogs.com → Settings → Developers → Generate token).
Results cache in `discogs_cache.json`, so re-runs are free. The API allows 60 requests a
minute, so a full pass over the deck takes about six minutes.

## Auditing the deck

```bash
python audit_years.py    # flags suspicious cards, never edits songs.csv
```

It reports three things, in descending order of how much they matter:

- `ALBUM-EARLIER` — our year is later than an original-looking album. Strong evidence we are wrong.
- `EXTRA-ARTIST` + `FAR-LATER` together — the track is a modern remake or duet, not the original
  recording. *Nie spoczniemy* resolving to BIAŁO CZERWONE GITARY (2025) is unguessable in play.
- `EXTRA-ARTIST` alone — noisy. Niemen & Akwarele and Republika & Ciechowski are original credits.

Results cache in `album_cache.json`, so re-running is free.

## Pipeline

```
seed.csv           artist, title, year   (curated, edit this)
  -> fetch_songs.py                      resolves Spotify track IDs, flags suspect years
songs.csv          + track_id            (review the `check` column, then edit freely)
  -> make_cards.py
cards.html         print this            docs/deck.json  the app's answer key
```

## Printing

```bash
python make_cards.py --test-page   # one sheet first
python make_cards.py               # the whole deck
```

Open `cards.html`, print with **A4, margins: None, scale 100%, two-sided flipping on the LONG
edge**. Sheets alternate front/back; each back is column-mirrored so the answer lands behind its
own QR. Print the test page first and confirm a card measures 65 mm — printer margins vary and
usually need one calibration pass.

## The app

Static PWA in `docs/`. To run it:

1. Push this repo to GitHub and enable **Pages** on the `/docs` folder (HTTPS is required for
   camera access).
2. In the [Spotify dashboard](https://developer.spotify.com/dashboard), add your Pages URL as a
   **Redirect URI** (exactly, including the trailing `/`) and enable the Web API.
3. Open the Pages URL on the iPhone, **Share → Add to Home Screen**.
4. Open Spotify on the phone and press play once, so Spotify Connect has a live device.
5. Launch the app from the home screen, connect Spotify, scan a card.

Requires **Spotify Premium** — the app starts a specific track via the Web API, which Spotify
only permits for Premium accounts. There is no free fallback: 30-second `preview_url` clips were
removed from the API for apps registered after November 2024.

## Regenerating song data

```bash
python fetch_songs.py    # writes songs.new.csv if songs.csv already exists, never clobbers edits
python test_cards.py     # duplex alignment, artist matching, year-flag logic
```

**Expect to run `fetch_songs.py` more than once.** A development-mode Spotify app has a small
quota, and once it runs out Spotify replies `429` with a `Retry-After` measured in hours
(observed: 5940 seconds). The script refuses to sleep that long — it saves progress and exits,
so re-running after the limit clears resumes instead of restarting.

Both caches (`mb_cache.json` for MusicBrainz, `spotify_cache.json` for track lookups) are what
make that resumable. Delete them only if you want a genuinely fresh run.
# hitster
