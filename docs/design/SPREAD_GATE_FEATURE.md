# Spread/Liquidity Gate Feature (Cascade item — WS-5c)

## Status

Design spec — **not implemented**. Stub-level design only (this is
intentionally shorter than `PORTFOLIO_AWARENESS_FEATURE.md` /
`PROMPT_CONTRACT_V2_FEATURE.md` — the gate itself is deferred behind a data
prerequisite that is only now landing). Owner-gated per the same doctrine:
**design only; implementation starts only after Josh signs the decision
checklist at the end, and only after the activation criteria in (b) are met.**

Direction call-out (AGENTS.md fail-open hunt): this feature, once built, is
**strictly tightening** — it can only add a new reason to refuse a live BUY
the panel already approved. It never creates, enlarges, or unblocks a trade.

## Motivation

Coinbase fees run ~1.2%/side (~2.4% round trip, measured — the same
`DEFAULT_FEE_FLOOR_PCT` the analyzer already scores against,
tradeanalyzer.py:54). That fee floor assumes execution near the quoted
price. A wide bid/ask spread is a second, independent cost that stacks on
top of fees and is currently invisible to every gate: `historyutil.py`
accepts `bid_price`/`ask_price` parameters (historyutil.py:183-184,
221-222) but every recommendation record written today carries them as
`None` (`docs/RECORD_SCHEMA.md`: "write-only in `tradeanalyzer`... never
fabricated" — meaning nothing currently calls the write path with real
quotes). The bot has never measured, let alone gated on, spread.

This matters because Santiment-driven discovery (the santiment/hybrid
discovery path, `docs/design/` cross-ref: the 2026-07-21 polymarket/
santiment bypass fix) surfaces small-cap tickers by social/on-chain signal
first and liquidity never. Thinly-traded small-caps like ERA, LA, or OPN
are exactly the kind of coin that discovery is good at finding and a
spread gate is designed to catch: a coin can clear every consensus and fee
check and still be a structural loser once the spread is paid on entry
(and again, worse, on the exit this bot cannot yet execute — WS6).

## Activation criteria (data prerequisite, not yet met)

This feature cannot be designed past a sketch today because there is no
spread data to design against. Cycle 2's WS-5b (implemented concurrently
with this doc) wires real bid/ask capture + a derived `spread_pct` into
recommendation records as the shadow-data prerequisite — populating the
fields `historyutil.py` already has parameters for for the first time.

**Proposed activation floor** (owner decision — flagged, not asserted):
≥ **200** matured whatif recommendation records with populated
`spread_pct` (i.e. WS-5b has been running long enough in the whatif
cadence, `docs/RUNBOOK_whatif_cadence.md`, to produce a real distribution
across coins and liquidity tiers — not just BTC/ETH majors). Until that
floor is hit, any spread threshold is a guess dressed as a number. This
mirrors the evidence-gate shape in `PROMPT_CONTRACT_V2_FEATURE.md` §(e):
whatif-only, matured-record count as the trigger, owner reviews the
resulting distribution before a threshold is chosen.

## Design sketch

Two phases, in order — do not skip to phase 2:

1. **Analyzer shadow policy first (counterfactual, no gate).** Once WS-5b
   data exists, extend the analyzer (in the spirit of WS4's extensions) with
   a "would-have-blocked" counterfactual: for each matured BUY record,
   compute what a candidate spread threshold would have refused, and
   whether the refused trades were the ones that graded worse. This is
   pure analysis over existing records — no code on the money path, no
   flag, nothing live-adjacent. It answers the question a gate must answer
   before it exists: *does spread predict bad outcomes here, and at what
   threshold?*
2. **Fail-closed gate, placed as a decision-quality check.** Once (1)
   produces a threshold the owner accepts, the gate itself is a
   **decision-quality check** per `docs/INVARIANTS.md` §(c): it belongs in
   `gate_and_maybe_buy` (the shared, lock-free wiring used by both analysis
   loops), the same placement class as the edge gate
   (`EDGE_VS_FEE_GATING_FEATURE.md` §a) — **not** inside
   `maybe_execute_buy`'s ledger-lock span. Rationale, same as the edge
   gate's: the spread check needs no ledger and no lock — it is a read of
   the just-fetched quote, not a read-then-write over shared ledger state.
   Placing it under the lock (portfolio-guard style) would serialize an
   unrelated network call against every other run's buys for no benefit.
   Fail-closed semantics: missing/unfetchable spread data on a live buy
   attempt refuses the coin (same "could-not-verify ≠ fine" doctrine as
   every other money-path check in this repo) rather than silently
   skipping the check.

Not designed here (deferred to the real spec once activation criteria are
met): the exact threshold, whether it is a flat `spread_pct` cutoff or
notional-scaled, the reason-code string, and the test plan. Those need the
counterfactual data this doc explicitly says doesn't exist yet.

## Non-goals (explicit, v1 and beyond until revisited)

- **No order-book depth modeling.** This is a top-of-book bid/ask spread
  check only — no attempt to model slippage from walking the book at
  larger size.
- **No DEX.** Spread on DEX pools (AMM slippage curves, not a bid/ask
  quote) is a structurally different problem and out of scope; this gate
  is Coinbase-order-book shaped.
- **No retroactive gating of past records.** WS-5b's shadow data is for
  the counterfactual analysis in (1); it does not reach back and re-grade
  history.
- **No live enablement before the counterfactual in (1) is run and
  reviewed.** A threshold chosen without evidence is exactly the mistake
  `PROMPT_CONTRACT_V2_FEATURE.md`'s promotion gate exists to prevent.

## Decision checklist for owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Treat WS-5b's bid/ask/spread capture as a hard prerequisite — no gate design work beyond this stub until it's landed and running? | **Yes.** |
| 2 | Activation floor of ≥200 matured whatif records with populated `spread_pct` before even drafting a threshold? | **Yes, as a starting proposal** — raise if the owner wants more coin/liquidity-tier diversity than 200 records guarantees. |
| 3 | Phase 1 is an analyzer counterfactual (no gate, no flag) before any code touches the money path? | **Yes** — same "measure before you gate" discipline as prompt contract v2. |
| 4 | Gate placement in `gate_and_maybe_buy` (decision-quality, lock-free), not `maybe_execute_buy` (ledger-locked)? | **Yes** — per `docs/INVARIANTS.md` §(c); the check needs no ledger read-then-write. |
| 5 | Fail-closed on missing/unfetchable spread data for a live buy? | **Yes** — consistent with every other money-path check in this repo. |
| 6 | Defer order-book depth modeling and DEX spread entirely (not just for v1 — revisit only if the owner asks)? | **Yes.** |
