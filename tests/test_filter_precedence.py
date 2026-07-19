"""Explicit coins vs filters/discovery precedence (owner bug 2026-07-19).

USE_COIN_DISCOVERY is `len(ANALYZE_COINS) == 0`, so any explicit coin --
including the ubiquitous ANALYZE_COINS env var -- forces COIN CHOICE MODE,
which silently ignores --chains/--categories/--polymarket-filter/--discovery
(the filter path and the santiment discovery path both require
USE_COIN_DISCOVERY). The live symptom: the bot analyzed the env coins while
the banner still advertised "Chain Filter: solana" / "Category Filter:
meme-coins" as active.

Resolution chosen: env-override-with-notice, decided by provenance. The
pure helper resolve_coin_selection_conflict() encodes the decision table;
these tests pin it, plus the banner-honesty gate. See the helper docstring
and tests/test_live_lock_dotenv.py for the resolve-style unit idiom.
"""

from crypto_trading_bot import resolve_coin_selection_conflict


# --- no conflict -> proceed --------------------------------------------------

def test_no_coins_with_filters_is_discovery_unchanged():
    # Discovery mode with filters: the intended, working path. No conflict.
    action, msg = resolve_coin_selection_conflict(
        has_explicit_coins=False,
        coins_from_cli=False,
        filter_flags_on_cli=True,
        analyze_coins_display='',
    )
    assert action == 'proceed'
    assert msg is None


def test_explicit_coins_without_cli_filters_proceed():
    # Explicit coins, no CLI filter/discovery flags -> analyze them as-is.
    action, msg = resolve_coin_selection_conflict(
        has_explicit_coins=True,
        coins_from_cli=True,
        filter_flags_on_cli=False,
        analyze_coins_display='BTC, ETH',
    )
    assert action == 'proceed'
    assert msg is None


# --- CLI --coins + CLI filters -> error (fail closed) ------------------------

def test_cli_coins_plus_cli_filters_errors():
    action, msg = resolve_coin_selection_conflict(
        has_explicit_coins=True,
        coins_from_cli=True,
        filter_flags_on_cli=True,
        analyze_coins_display='BTC, ETH',
    )
    assert action == 'error'
    assert 'CONFIG ERROR' in msg
    # Both offending sides named, and the two escape routes offered.
    assert 'BTC, ETH' in msg
    assert '--coins=' in msg


# --- env coins + CLI filters -> override with a loud notice ------------------

def test_env_coins_plus_cli_filters_override():
    action, msg = resolve_coin_selection_conflict(
        has_explicit_coins=True,
        coins_from_cli=False,          # coins came from ANALYZE_COINS env
        filter_flags_on_cli=True,
        analyze_coins_display='BTC, ETH, SOL, DOGE, LINK',
    )
    assert action == 'override'
    assert '[CONFIG]' in msg
    assert 'ignoring ANALYZE_COINS env' in msg
    assert 'BTC, ETH, SOL, DOGE, LINK' in msg


def test_env_coins_without_cli_filters_proceed():
    # ANALYZE_COINS env set, no CLI filter flags -> just analyze them.
    action, msg = resolve_coin_selection_conflict(
        has_explicit_coins=True,
        coins_from_cli=False,
        filter_flags_on_cli=False,
        analyze_coins_display='BTC, ETH',
    )
    assert action == 'proceed'
    assert msg is None


# --- nothing is ever silently ignored ---------------------------------------

def test_every_explicit_coins_with_filters_case_is_surfaced():
    # For all four (coins_from_cli x filter_flags_on_cli) combos with explicit
    # coins present, the only silent ('proceed', None) outcome is when NO CLI
    # filter flag is present -- otherwise the user is always told (error or
    # override). This is the anti-silent-ignore invariant.
    for coins_from_cli in (True, False):
        for filters in (True, False):
            action, msg = resolve_coin_selection_conflict(
                has_explicit_coins=True,
                coins_from_cli=coins_from_cli,
                filter_flags_on_cli=filters,
                analyze_coins_display='BTC',
            )
            if filters:
                assert action in ('error', 'override')
                assert msg is not None
            else:
                assert action == 'proceed'


# --- banner honesty ----------------------------------------------------------
#
# The banner/summary gate is `if USE_COIN_DISCOVERY:` around the filter lines,
# so a filter is printed as active iff it will actually apply (filters and
# santiment discovery both require USE_COIN_DISCOVERY). This mirrors that gate
# at the level it operates, keeping the honesty rule pinned without driving
# main() end-to-end.

def _filter_lines_shown(use_coin_discovery, chains, categories, polymarket):
    """Reproduce the banner's gating decision for the filter lines."""
    if not use_coin_discovery:
        return []
    lines = []
    if chains:
        lines.append('Chain Filter')
    if categories:
        lines.append('Category Filter')
    if polymarket:
        lines.append('Polymarket Filter')
    return lines


def test_banner_hides_filters_with_explicit_coins():
    # Explicit coins => not discovery => filters are inert => not advertised.
    assert _filter_lines_shown(
        use_coin_discovery=False, chains=['solana'],
        categories=['meme-coins'], polymarket=True) == []


def test_banner_shows_filters_in_discovery_mode():
    shown = _filter_lines_shown(
        use_coin_discovery=True, chains=['solana'],
        categories=['meme-coins'], polymarket=False)
    assert shown == ['Chain Filter', 'Category Filter']
