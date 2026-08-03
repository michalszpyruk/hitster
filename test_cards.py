"""Checks for the two things that fail silently. Run: python test_cards.py"""
from make_cards import back_order, palette_class, split_year, PALETTES, COLS
from fetch_songs import flag, norm, artist_matches


def test_duplex_alignment():
    """Every answer must land physically behind its own QR after a long-edge flip.

    Turning a portrait sheet over on its long edge mirrors it left-to-right, so the
    card printed at front (row, col) ends up against back (row, COLS-1-col).
    """
    for n in (12, 11, 7, 1):                       # full sheet, and partial last sheets
        page = list(range(n))
        rows = back_order(page, COLS)
        for i, card in enumerate(page):            # walk the fronts, in print order
            r, c = divmod(i, COLS)
            assert rows[r][COLS - 1 - c] == card, (
                f'n={n}: card {card} printed at front ({r},{c}) is not behind its own QR')
        assert sorted(x for row in rows for x in row if x is not None) == page, \
            f'n={n}: mirroring lost or duplicated a card'


def test_year_flag():
    # MusicBrainz knows of a 1980 release but the seed claims 1995 -> seed is too late.
    assert 'YEAR?' in flag(1995, 1980, 'id', True)
    # MusicBrainz only has a late compilation; that proves nothing, so stay quiet.
    assert flag(1980, 1991, 'id', True) == ''
    # Small disagreements are noise (pressing dates slip a year), not errors.
    assert flag(1983, 1982, 'id', True) == ''
    # Unresolvable or dubious matches always surface.
    assert 'NO-SPOTIFY-MATCH' in flag(1980, None, '', False)
    assert 'FUZZY-TITLE' in flag(1980, None, 'id', False)


def test_norm_folds_polish():
    assert norm('Małgośka') == norm('Malgoska')
    assert norm('Kocham Cię, Kochanie Moje') == norm('kocham cie kochanie moje')


def test_artist_matching():
    assert artist_matches('Czesław Niemen', 'Niemen')      # Spotify drops the first name
    assert artist_matches('Maanam', 'MAANAM')
    assert artist_matches('Kayah i Bregović', 'Kayah')
    assert not artist_matches('Hey', 'Heyah')              # short names must match exactly
    assert not artist_matches('Kult', 'Kultura')
    assert not artist_matches('Republika', 'Perfect')


def test_palette_is_stable_and_year_independent():
    """A card must keep its colour forever, or a reprint won't match the deck."""
    import subprocess, sys
    tid = '6CwbrtZnJNqef5CqSLqPdX'
    # Across separate processes: catches anyone swapping crc32 for salted hash().
    out = subprocess.run(
        [sys.executable, '-c',
         'from make_cards import palette_class; print(palette_class(%r))' % tid],
        capture_output=True, text=True, check=True).stdout.strip()
    assert out == palette_class(tid), 'palette changed between processes'

    ids = ['%022d' % i for i in range(400)]
    used = {palette_class(t) for t in ids}
    assert used == {f'c{i}' for i in range(PALETTES)}, f'palettes unused: {used}'
    # Spread should be roughly even -- no palette starved or dominant.
    counts = [sum(palette_class(t) == f'c{i}' for t in ids) for i in range(PALETTES)]
    assert max(counts) < 2 * min(counts), f'lopsided palette spread: {counts}'


def test_unconfirmed_year_marker():
    """A trailing '*' means "nobody has verified this" and must survive to the card."""
    assert split_year('1984') == ('1984', '')
    assert split_year('1984*') == ('1984', '*')
    assert split_year(' 1984* ') == ('1984', '*')
    assert split_year(1984) == ('1984', '')
    # Every consumer strips the star before doing arithmetic; if one forgets, it throws.
    for y in ('1984', '1984*'):
        assert int(y.rstrip('*')) == 1984


if __name__ == '__main__':
    test_unconfirmed_year_marker()
    test_palette_is_stable_and_year_independent()
    test_duplex_alignment()
    test_year_flag()
    test_norm_folds_polish()
    test_artist_matching()
    print('ok')
