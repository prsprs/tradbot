# RUNBOOK — Scheduled what-if cadence

A runbook for the repo **owner** to run the bot on a schedule in **what-if
mode** so that a stream of consensus decisions accumulates in the real history,
which `tradeanalyzer.py` then scores benchmark-relative over time.

> **Nothing here installs a job for you.** The cron / launchd snippets are
> examples the owner installs by hand. This document creates no scheduled task.
> A scheduled what-if run places **no trades** — it only records what the panel
> *would* have decided, tagged `trading_mode='whatif'`.

---

## Why a what-if cadence

The analyzer grades a decision on its return over the window `[t_rec, now]`
minus BTC's return over the same window minus the round-trip fee floor. To grade
anything you first need *decisions to grade*. Live trading produces very few of
them (spend-capped, a handful of coins). A what-if cadence produces many, cheaply
and without risk: every scheduled run writes fresh `whatif` recommendation
records (and simulated ledger rows) that mature into scoreable samples 24h later.

Because what-if and live are scored **separately** by the analyzer, this data
never contaminates the live scorecard — it builds a parallel, higher-volume
what-if scorecard you can actually do statistics on.

---

## The command line

Scheduled runs happen on the owner's own machine against the owner's own data,
so they point `HISTORY_DIR` at the **real** history directory (unlike an agent's
runs, which must redirect to a scratch dir).

```bash
# Generation run (writes whatif recommendations + a simulated ledger row per coin)
cd /Users/<you>/coding/paul/tradbot
HISTORY_DIR="$PWD/history" ./venv/bin/python crypto_trading_bot.py \
    --trading-mode=whatif \
    --llm-mode=compare \
    --coins=BTC,ETH,SOL,DOGE \
    --skip-analyzer
```

- `--trading-mode=whatif` is the safety anchor: no `--live`, no
  `LIVE_TRADING_CONFIRMED=1`, so the double-lock can never arm. No order is ever
  placed.
- `--skip-analyzer` suppresses the bot's own startup history-summary on the
  *generation* run (you'll run the full analyzer separately, below). Drop the
  flag if you want the one-line summary in the cadence log too — it's harmless.
- Keep the coin set small and stable so the what-if scorecard compares like with
  like across runs.

### Scoring run (reads the accumulated data)

```bash
cd /Users/<you>/coding/paul/tradbot
HISTORY_DIR="$PWD/history" ./venv/bin/python tradeanalyzer.py
# full benchmark-relative scoring; writes analysis_live_*.csv / analysis_whatif_*.csv
# and updates analyzer_state.json (judged-flag persistence)
```

The scoring run needs read-only Coinbase access (current prices + BTC candles
for the benchmark window) via `cdp_api_key.json`. For a fast, network-free
structural summary instead, add `--offline`.

---

## Frequency recommendation and cost

The analyzer's default maturity is **24h** — a decision is `pending` until it is
24h old, then it becomes scoreable. A cadence of **every 6 hours (4×/day)** is
the sweet spot: it yields 4 fresh decisions per coin per day (enough to build a
sample within a week) without paying for calls faster than the market gives new
information.

### LLM-API cost per run (estimate)

A `--llm-mode=compare` run makes **one analysis call per coin per panelist**
(the panel is up to 5 models: gemini, claude, openai, grok, perplexity), plus a
one-time preflight probe (a few cents). Each analysis call is a few thousand
input tokens (the market-data block) and ~1–2k output tokens.

| Coins | Panel calls (×5) | Rough cost/run\* | Cost/day @ 4×/day |
|------:|-----------------:|-----------------:|------------------:|
|   1   |        5         |  ~$0.05–0.25     |   ~$0.20–1.00     |
|   4   |       20         |  ~$0.20–1.00     |   ~$0.80–4.00     |
|   8   |       40         |  ~$0.40–2.00     |   ~$1.60–8.00     |

\* Order-of-magnitude only. The table assumes the full 5-model panel. Actual
cost depends on the current model IDs (`modelregistry.py`), per-model pricing,
prompt size, and how much reasoning the reasoning models spend. Verify against a
couple of real runs before trusting the budget. To cut cost, shrink the panel
(`--llm-mode=gemini` for a single model) or the coin set, or lengthen the
interval.

> **Note:** the recommended live-cadence panel is the `gemini,claude,openai`
> trio (`--compare-llms=gemini,claude,openai`), which drops the two web-search
> models (grok, perplexity) and is correspondingly cheaper than the ×5 figures
> above — scale the per-run cost by roughly 3/5.

The **analyzer** itself costs **nothing** in LLM API terms — it makes no LLM
calls. Its only external calls are read-only Coinbase price/candle fetches (free).

---

## How the analyzer consumes the accumulating data

1. **Loads** every `recommendations*.json` in `HISTORY_DIR` (never a `*.bak-*`
   backup) plus the execution ledger `executions.json`.
2. **Accounts for every record** in exactly one category — nothing is dropped:
   `non_trading`, `excluded_unknown` (trading_mode unknown), `blocked` (a `NONE`
   panel block), `pending` (younger than maturity), `scored`, or
   `expired_unscorable` (mature but missing price/benchmark data).
3. **Scores live and what-if separately.** For each mature `BUY`/`SELL` it
   computes `coin_return − BTC_return − fee_floor`; a positive excess is a WIN.
   A `BUY` that rose but trailed BTC or didn't clear fees is a **LOSS**.
4. **Uses actual fees when available.** If an execution-ledger fill row joins the
   recommendation by `run_id`, the analyzer uses the real fee from the fill
   instead of the 2.4% assumption; otherwise it degrades to the assumed floor.
5. **Freezes judged decisions.** The first time a decision is scored, its outcome
   is written to `analyzer_state.json`. Re-runs reuse that frozen verdict, so a
   later market move never silently re-grades yesterday's decision.
6. **Reports panel behavior** from the `blocked` records: a block-reason
   histogram, the consensus-state distribution, and per-LLM vote/abstain
   patterns.

As the cadence runs, `pending` decisions roll into `scored` on their next
analyzer pass once they cross 24h, and the what-if scorecard grows.

---

## Example: cron (macOS/Linux)

`crontab -e`, then add (every 6 hours):

```cron
# Every 6 hours: what-if generation run, log appended.
0 */6 * * * cd /Users/<you>/coding/paul/tradbot && HISTORY_DIR="$PWD/history" ./venv/bin/python crypto_trading_bot.py --trading-mode=whatif --llm-mode=compare --coins=BTC,ETH,SOL,DOGE --skip-analyzer >> "$HOME/tradbot_whatif.log" 2>&1

# Daily at 07:15: scoring pass over the accumulated data.
15 7 * * * cd /Users/<you>/coding/paul/tradbot && HISTORY_DIR="$PWD/history" ./venv/bin/python tradeanalyzer.py >> "$HOME/tradbot_analysis.log" 2>&1
```

> On recent macOS, `cron` needs Full Disk Access granted to `/usr/sbin/cron` in
> System Settings → Privacy & Security, or it can't read the repo. `launchd`
> (below) is the more macOS-native choice.

---

## Example: launchd (macOS, native)

Save as `~/Library/LaunchAgents/com.<you>.tradbot.whatif.plist`, edit the paths,
then `launchctl load ~/Library/LaunchAgents/com.<you>.tradbot.whatif.plist`.
This runs the generation every 6 hours (`StartInterval` in seconds):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.<you>.tradbot.whatif</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/<you>/coding/paul/tradbot/venv/bin/python</string>
        <string>/Users/<you>/coding/paul/tradbot/crypto_trading_bot.py</string>
        <string>--trading-mode=whatif</string>
        <string>--llm-mode=compare</string>
        <string>--coins=BTC,ETH,SOL,DOGE</string>
        <string>--skip-analyzer</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/<you>/coding/paul/tradbot</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HISTORY_DIR</key>
        <string>/Users/<you>/coding/paul/tradbot/history</string>
    </dict>
    <key>StartInterval</key>
    <integer>21600</integer>
    <key>StandardOutPath</key>
    <string>/Users/<you>/tradbot_whatif.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/<you>/tradbot_whatif.err</string>
</dict>
</plist>
```

A second agent (e.g. `com.<you>.tradbot.analysis.plist`) can run
`tradeanalyzer.py` daily with `StartCalendarInterval`.

---

## Safety checklist before you install anything

- [ ] The command contains `--trading-mode=whatif` and **no** `--live`.
- [ ] `LIVE_TRADING_CONFIRMED` is **not** exported in the schedule's environment.
- [ ] `HISTORY_DIR` points at your real `history/` on purpose (owner data), and
      that directory is git-ignored (it is — see `.gitignore`).
- [ ] You reviewed the estimated per-run cost against your API budget.
- [ ] The first run was launched **by hand** and inspected before scheduling it.
