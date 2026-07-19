"""Offline empirical tests of extract_recommendation (crypto_trading_bot.py).

The module can't be imported (top-level script triggers live API clients),
so we exec just the function's source.
"""
import re, sys

src = open('/Users/joshhoffmansenn/coding/paul/tradbot/crypto_trading_bot.py').read()
m = re.search(r'\ndef extract_recommendation\(.*?\n(?=\ndef |\nclass |\n\n\n)', src, re.S)
assert m, "extract_recommendation not found"
ns = {}
exec(m.group(0), ns)
f = ns['extract_recommendation']

CASES = [
    # (name, input, expected)
    ("normal BUY", "Analysis... upward momentum.\n<**SOL-PRS-BUY**>", "BUY"),
    ("normal HOLD", "Mixed signals.\n<**ETH-PRS-HOLD**>", "HOLD"),
    ("refusal quoting format in backticks (finding 1.1)",
     "I can't provide a real-time buy/sell/hold recommendation for ETH. "
     "The requested format (`<**ETH-PRS-BUY**>`, `<**ETH-PRS-SELL**>`, or `<**ETH-PRS-HOLD**>`) "
     "implies certainty I don't have.", None),
    ("refusal quoting format WITHOUT backticks",
     "I can't recommend. The format would be <**ETH-PRS-BUY**> for a buy, "
     "but I won't issue one.", "BUY"),  # documents residual risk
    ("last occurrence wins",
     "If bullish I'd say <**ETH-PRS-BUY**>. But given the data: <**ETH-PRS-HOLD**>", "HOLD"),
    ("discussion then real tag",
     "The options are BUY, SELL, or HOLD. My recommendation: <**BONK-PRS-SELL**>", "SELL"),
    ("empty string", "", None),
    ("None input", None, None),
    ("no tag at all", "I recommend holding ETH for now.", None),
    ("partial tag missing close", "<**ETH-PRS-BUY", None),
    ("lowercase keyword", "<**eth-prs-buy**>", None),
    ("tag inside triple-backtick code block",
     "Example output:\n```\n<**ETH-PRS-BUY**>\n```\nBut I decline to recommend.", "BUY"),  # residual risk: fenced blocks not stripped
    ("bold-wrapped tag variant", "**<**ETH-PRS-HOLD**>**", "HOLD"),
    ("whitespace inside tag", "<** ETH-PRS-BUY **>", None),
]

fails = 0
for name, inp, want in CASES:
    got = f(inp)
    ok = got == want
    fails += (not ok)
    print(f"{'PASS' if ok else 'FAIL'}: {name!r} -> {got!r} (expected {want!r})")
print(f"\n{len(CASES)-fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
