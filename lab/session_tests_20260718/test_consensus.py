"""Offline empirical test of process_coin_with_comparison consensus math.

Extracts the function source from crypto_trading_bot.py and execs it in a
stub namespace where get_llm_response returns scripted votes — no API calls.
"""
import re

src = open('/Users/joshhoffmansenn/coding/paul/tradbot/crypto_trading_bot.py').read()

# extract extract_recommendation + process_coin_with_comparison
def grab(name):
    m = re.search(rf'\ndef {name}\(.*?(?=\n\ndef |\n\nclass |\n\n\n)', src, re.S)
    assert m, name
    return m.group(0)

code = grab('extract_recommendation') + "\n" + grab('process_coin_with_comparison')

def run_case(name, llm_mode, compare_llms, primary, require_consensus, tiebreaker,
             votes, primary_text="primary says <**ETH-PRS-{}**>"):
    """votes: dict llm -> rec-or-None-or-'NORESP' (NORESP = call failed, resp None)"""
    ns = {
        'LLM_MODE': llm_mode,
        'COMPARE_LLMS': compare_llms,
        'PRIMARY_LLM': primary,
        'REQUIRE_CONSENSUS': require_consensus,
        'INTEGRATION_TIEBREAKER': tiebreaker,
        'LOG_INTEGRATION_ROUNDS': False,
        'print': lambda *a, **k: None,
        'claude_trader': True, 'openai_trader': True,
        'grok_trader': True, 'perplexity_trader': True,
    }
    def fake_get_llm_response(llm, coin, use_trend, peer_analysis=None, trends_data=None):
        v = votes.get(llm, 'NORESP')
        if v == 'NORESP':
            return None, None
        if v is None:
            return "some prose without a tag", None
        return f"analysis <**{coin}-PRS-{v}**>", v
    ns['get_llm_response'] = fake_get_llm_response
    exec(code, ns)
    ptext = None
    pv = votes.get(primary)
    if pv == 'NORESP':
        ptext = None
    elif pv is None:
        ptext = "some prose without a tag"
    else:
        ptext = f"analysis <**ETH-PRS-{pv}**>"
    action, consensus = ns['process_coin_with_comparison']('ETH', ptext)
    trade_fires = bool(action) and 'BUY' in action
    print(f"{name}\n  -> action={action!r} consensus={consensus!r} WOULD_BUY={trade_fires}")
    return action, consensus, trade_fires

C = ['gemini', 'claude', 'openai']

print("=== compare mode, require_consensus=True ===")
run_case("A1 all BUY", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':'BUY','openai':'BUY'})
run_case("A2 2 BUY + 1 HOLD (majority BUY)", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':'BUY','openai':'HOLD'})
run_case("A3 BUY + BUY + API-error (finding 1.1 shape)", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':'BUY','openai':'NORESP'})
run_case("A4 BUY + API-error + API-error (sub-quorum)", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':'NORESP','openai':'NORESP'})
run_case("A5 BUY + unparseable-prose + unparseable-prose", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':None,'openai':None})
run_case("A6 all unparseable prose", 'compare', C, 'gemini', True, 'gemini',
         {'gemini':None,'claude':None,'openai':None})

print("\n=== integrate mode (votes same across both rounds) ===")
run_case("B1 minority-primary BUY vs 2x HOLD, tiebreaker=primary=gemini (finding 1.2)",
         'integrate', C, 'gemini', True, 'gemini',
         {'gemini':'BUY','claude':'HOLD','openai':'HOLD'})
run_case("B2 same split, tiebreaker=claude (non-primary)",
         'integrate', C, 'gemini', True, 'claude',
         {'gemini':'BUY','claude':'HOLD','openai':'HOLD'})
run_case("B3 same split, tiebreaker=none",
         'integrate', C, 'gemini', True, 'none',
         {'gemini':'BUY','claude':'HOLD','openai':'HOLD'})
run_case("B4 split, tiebreaker LLM itself errored",
         'integrate', C, 'gemini', True, 'openai',
         {'gemini':'BUY','claude':'HOLD','openai':'NORESP'})
run_case("B5 integrate, require_consensus=False, tiebreaker=none",
         'integrate', C, 'gemini', False, 'none',
         {'gemini':'BUY','claude':'HOLD','openai':'HOLD'})
