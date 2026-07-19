"""T8: schema-enforced JSON trading votes (plan Phase 2).

One canonical vote schema for the whole panel:

    {symbol: str, action: 'BUY'|'SELL'|'HOLD', confidence: 0-1,
     abstain: bool, reasons: [str]}

An explicit ``abstain: true`` (the model declines to recommend) is a
FIRST-CLASS outcome, distinct from a parse failure — the 2026-07-18
evaluation's headline bug was a refusal being regex-scraped into a real BUY
(EVALUATION_LESSONS_LEARNED_2026-07-18.md §1.1). On the structured path that
class of bug is impossible by construction: a vote exists only if the
provider returned schema-valid JSON, the model did not abstain, and the
vote's symbol binds to the coin actually under analysis.

Provider adoption (probed live 2026-07-18, fixtures in
tests/fixtures/structured_output/):

  - gemini  — native (response_mime_type + response_schema; schema must not
              contain additionalProperties; compatible with google_search)
  - claude  — native (messages.create output_config json_schema; schema must
              not contain minimum/maximum on numbers)
  - openai  — native (response_format json_schema strict; full schema ok)
  - grok / perplexity — NOT adopted: they keep the delimiter-tag parser as a
              loudly-logged fallback path (see crypto_trading_bot.resolve_vote).
              Probes show both would support JSON natively; see the fixtures.

Failure mapping (consumed by T3's PanelDecision abstain machinery):

    no response / API error            -> abstain('error')      [legacy]
    empty text (e.g. token cap hit)    -> abstain('parse_failure')
    invalid JSON / schema violation    -> abstain('parse_failure')
    explicit abstain=true              -> abstain('refusal')
    symbol does not bind to the coin   -> abstain('symbol_mismatch')
    client never constructed (F1)      -> abstain('client_init_failure')
                                          [standing, registered by the bot's
                                          startup — not produced here]

None of these raise: resolve_structured_vote never lets a malformed
response escape as an exception (it fails closed to an Abstain instead).
"""

import copy
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

ACTIONS = ('BUY', 'SELL', 'HOLD')

# Canonical JSON schema for a vote. Provider quirks (probed 2026-07-18):
# OpenAI strict mode accepts it verbatim; Gemini rejects additionalProperties;
# Claude rejects minimum/maximum on numbers. Use the per-provider accessors.
VOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Ticker symbol of the coin being analyzed",
        },
        "action": {
            "type": "string",
            "enum": list(ACTIONS),
            "description": "Trading recommendation for the coin",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in the recommendation, 0 to 1",
        },
        "abstain": {
            "type": "boolean",
            "description": "true ONLY if declining to make a recommendation; "
                           "action is ignored when abstain is true",
        },
        "reasons": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short strings carrying the key points of the analysis",
        },
    },
    "required": ["symbol", "action", "confidence", "abstain", "reasons"],
    "additionalProperties": False,
}


def _strip_keys(node, keys):
    """Recursively remove the given keys from a schema dict (in place)."""
    if isinstance(node, dict):
        for key in keys:
            node.pop(key, None)
        for value in node.values():
            _strip_keys(value, keys)
    elif isinstance(node, list):
        for value in node:
            _strip_keys(value, keys)
    return node


def schema_for_gemini():
    """Gemini response_schema variant: the API 400s on additionalProperties
    ('Unknown name \"additional_properties\"' — verified live 2026-07-18)."""
    return _strip_keys(copy.deepcopy(VOTE_SCHEMA), ('additionalProperties',))


def schema_for_claude():
    """Claude output_config variant: the API 400s on minimum/maximum for
    number properties (verified live 2026-07-18). Confidence range is
    enforced client-side in parse_vote instead."""
    return _strip_keys(copy.deepcopy(VOTE_SCHEMA), ('minimum', 'maximum'))


def openai_response_format():
    """OpenAI Chat Completions response_format param (strict structured
    outputs). gpt-5.5 accepted the full schema incl. minimum/maximum and
    additionalProperties (verified live 2026-07-18)."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "trading_vote",
            "strict": True,
            "schema": copy.deepcopy(VOTE_SCHEMA),
        },
    }


def schema_instruction(coin_symbol):
    """The output-contract tail for structured-path analysis prompts.

    Replaces ONLY the old delimiter-tag instruction sentence ('Conclude your
    analysis with a left angle bracket, ...'); the analysis content of each
    prompt is unchanged (T8 hard line). Server-side schema enforcement does
    the real work — this tail tells the model what the fields mean.
    """
    return (
        'Provide your conclusion as a JSON object with these exact fields: '
        '"symbol" (string: the ticker symbol of the coin being analyzed, '
        f'here {coin_symbol}), '
        '"action" (string: exactly one of BUY, SELL, or HOLD), '
        '"confidence" (number between 0 and 1), '
        '"abstain" (boolean: set true ONLY if you decline to make a '
        'recommendation, in which case the action field is ignored), and '
        '"reasons" (array of short strings carrying the key points of your '
        'analysis). Respond with the JSON object only.'
    )


@dataclass
class Vote:
    """A validated structured vote."""
    symbol: str
    action: str            # 'BUY' | 'SELL' | 'HOLD'
    confidence: float      # 0..1
    abstain: bool
    reasons: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Abstain:
    """Marker returned in place of a vote string when a panelist did not
    produce a usable vote. `reason` feeds PanelDecision.abstains directly:
    'error' | 'parse_failure' | 'refusal' | 'symbol_mismatch' |
    'client_init_failure' (F1 standing abstain: the provider's client never
    constructed at startup; registered by crypto_trading_bot.main)."""
    reason: str


_FENCE_WRAPPER_RE = re.compile(r'\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z', re.DOTALL)

# --- reasons content hygiene (live-observed 2026-07-19: Claude emitted
# malformed JSON mid-stream, self-corrected, and its retry debris landed as
# syntactically-valid string elements INSIDE `reasons` while every typed field
# parsed clean; see docs/ACCEPTANCE_RESULTS_2026-07-19.md issue 1). Reasons
# are display text only (never persisted to history, never traded on), so we
# sanitize rather than reject — but if most of the array is debris the whole
# payload is suspect and we fail closed like any other schema violation.
MAX_REASONS = 12
MAX_REASON_LEN = 500
# Markers seen in real self-correction debris.
_REASON_ARTIFACT_MARKERS = ('__ERROR__', 'retrying:', '[REDACTED]')
# Bare schema keywords echoed as a "reason" (live-observed: literal "abstain").
_REASON_BARE_KEYWORDS = frozenset(
    {'symbol', 'action', 'confidence', 'abstain', 'reasons', 'true', 'false'})
_STRUCTURAL_ONLY_RE = re.compile(r'\A[\s{}\[\],:"\'`]*\Z')


def _is_junk_reason(r):
    """True if a (stripped, non-empty) reason string is parse debris rather
    than prose: artifact markers, pure JSON punctuation, unbalanced
    braces/brackets, control characters, or a bare schema keyword."""
    if _STRUCTURAL_ONLY_RE.match(r):
        return True
    if any(m in r for m in _REASON_ARTIFACT_MARKERS):
        return True
    if any(ord(c) < 32 for c in r):
        return True
    if r.count('{') != r.count('}') or r.count('[') != r.count(']'):
        return True
    if r.lower() in _REASON_BARE_KEYWORDS:
        return True
    return False


def _clean_reasons(reasons):
    """Sanitize a type-valid reasons list. Returns (cleaned, dropped_count).
    Cleaned entries are stripped, length-capped, and the list is count-capped;
    empty and junk entries count as dropped."""
    cleaned, dropped = [], 0
    for r in reasons:
        r = r.strip()
        if not r or _is_junk_reason(r):
            dropped += 1
            continue
        cleaned.append(r[:MAX_REASON_LEN])
    return cleaned[:MAX_REASONS], dropped


def parse_vote(text):
    """Parse and validate a JSON vote. Returns (Vote, None) on success or
    (None, error_detail) on any violation. Never raises.

    Validation is deliberately strict (fail closed on the money path): every
    field required, correct types, action in the enum (case-normalized),
    confidence within [0, 1] — the range is checked here because Claude's
    schema variant cannot carry minimum/maximum (see schema_for_claude).
    """
    if text is None:
        return None, 'no text'
    if not isinstance(text, str):
        return None, f'non-string payload ({type(text).__name__})'
    s = text.strip()
    # Defensive: unwrap a fenced ```json ... ``` block should a provider ever
    # wrap the payload (native structured output does not, but fail-safe).
    fence = _FENCE_WRAPPER_RE.match(s)
    if fence:
        s = fence.group(1).strip()
    if not s:
        return None, 'empty text'
    try:
        # First complete JSON object only: a self-correcting model can emit
        # "{good}...debris...{retry}" — raw_decode takes the leading object
        # and ignores the tail (the typed-field validation below still gates
        # everything that matters; an unterminated object still errors here).
        obj, _end = json.JSONDecoder().raw_decode(s)
    except ValueError as e:
        return None, f'invalid JSON: {e}'
    if not isinstance(obj, dict):
        return None, f'JSON is not an object ({type(obj).__name__})'

    missing = [k for k in VOTE_SCHEMA['required'] if k not in obj]
    if missing:
        return None, f'missing field(s): {", ".join(missing)}'

    symbol = obj['symbol']
    if not isinstance(symbol, str) or not symbol.strip():
        return None, f'symbol must be a non-empty string, got {symbol!r}'

    action = obj['action']
    if not isinstance(action, str):
        return None, f'action must be a string, got {action!r}'
    action = action.strip().upper()
    if action not in ACTIONS:
        return None, f'action must be one of {ACTIONS}, got {obj["action"]!r}'

    confidence = obj['confidence']
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None, f'confidence must be a number, got {confidence!r}'
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        return None, f'confidence must be within [0, 1], got {confidence}'

    abstain = obj['abstain']
    if not isinstance(abstain, bool):
        return None, f'abstain must be a boolean, got {abstain!r}'

    reasons = obj['reasons']
    if not isinstance(reasons, list) or any(not isinstance(r, str) for r in reasons):
        return None, f'reasons must be an array of strings, got {reasons!r}'
    cleaned, dropped = _clean_reasons(reasons)
    # Fail closed when debris dominates: a majority-junk reasons array means
    # the payload as a whole came from a corrupted emission.
    if reasons and dropped > len(reasons) // 2:
        return None, (f'reasons content corrupt: {dropped}/{len(reasons)} '
                      'entries were empty or parse debris')

    return Vote(symbol=symbol.strip(), action=action, confidence=confidence,
                abstain=abstain, reasons=cleaned), None


# Common full-name -> ticker aliases for symbol binding. Conservative and
# small on purpose: anything not resolvable here or by the structural rules
# below is a mismatch (fail closed), never a guess.
NAME_TO_TICKER = {
    'BITCOIN': 'BTC',
    'ETHEREUM': 'ETH',
    'ETHER': 'ETH',
    'SOLANA': 'SOL',
    'DOGECOIN': 'DOGE',
    'RIPPLE': 'XRP',
    'CARDANO': 'ADA',
    'LITECOIN': 'LTC',
    'POLKADOT': 'DOT',
    'AVALANCHE': 'AVAX',
    'CHAINLINK': 'LINK',
    'POLYGON': 'MATIC',
    'DOGWIFHAT': 'WIF',
    'SHIBAINU': 'SHIB',
    'PEPECOIN': 'PEPE',
}

_QUOTE_SUFFIXES = ('-USD', '/USD', '-USDT', '/USDT', '-USDC', '/USDC')
_PAREN_TICKER_RE = re.compile(r'\(([A-Z0-9]{2,10})\)$')


def bind_symbol(vote_symbol, coin_symbol):
    """True iff the symbol a model voted on binds to the coin under analysis.

    Accepted forms (all case-insensitive, whitespace-stripped):
      1. exact ticker match ('BTC' == 'btc')
      2. quote-pair suffix ('BTC-USD', 'BTC/USDT', ...)
      3. known full name ('Bitcoin', 'dogwifhat' -> WIF) via NAME_TO_TICKER
      4. 'Full Name (TICKER)' with the parenthesized ticker matching

    Everything else — including a different coin's ticker, an unknown full
    name, or a missing symbol — is a mismatch. Conservative by design: a
    mismatch becomes abstain('symbol_mismatch'), never a traded vote.
    """
    if not vote_symbol or not coin_symbol:
        return False
    coin = str(coin_symbol).strip().upper()
    raw = str(vote_symbol).strip().upper()
    if not coin or not raw:
        return False
    if raw == coin:
        return True
    for suffix in _QUOTE_SUFFIXES:
        if raw.endswith(suffix) and raw[:-len(suffix)].strip() == coin:
            return True
    compact = re.sub(r'[^A-Z0-9]', '', raw)
    if NAME_TO_TICKER.get(compact) == coin:
        return True
    paren = _PAREN_TICKER_RE.search(raw)
    if paren and paren.group(1) == coin:
        return True
    return False


def resolve_structured_vote(provider, response_text, coin_symbol, log=print):
    """Map a structured-path provider response to a vote or an Abstain.

    Returns 'BUY'/'SELL'/'HOLD' (str), or an Abstain, or None when there was
    no response at all (response_text is None -> the caller's legacy 'error'
    mapping). Never raises — every malformed shape fails closed to
    abstain('parse_failure').
    """
    try:
        if response_text is None:
            return None  # API error path: caller records abstain('error')
        if not str(response_text).strip():
            log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: empty response "
                "text (token cap or no visible output) -> abstain(parse_failure)")
            return Abstain('parse_failure')
        vote, err = parse_vote(response_text)
        if vote is None:
            log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: schema violation "
                f"({err}) -> abstain(parse_failure)")
            return Abstain('parse_failure')
        if vote.abstain:
            log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: model explicitly "
                f"abstained (confidence={vote.confidence:.2f}, "
                f"reasons={vote.reasons}) -> abstain(refusal)")
            return Abstain('refusal')
        if not bind_symbol(vote.symbol, coin_symbol):
            log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: vote symbol "
                f"{vote.symbol!r} does not bind to the coin under analysis "
                "-> abstain(symbol_mismatch)")
            return Abstain('symbol_mismatch')
        log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: {vote.action} "
            f"(confidence={vote.confidence:.2f}, symbol={vote.symbol!r} ok)")
        return vote.action
    except Exception as e:  # pragma: no cover - defensive fail-closed
        try:
            log(f"[STRUCTURED VOTE] {provider}/{coin_symbol}: unexpected "
                f"resolution error ({type(e).__name__}: {e}) -> abstain(parse_failure)")
        except Exception:
            pass
        return Abstain('parse_failure')
