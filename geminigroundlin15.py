from google import genai

from google.genai import types

import datetime

import json

import os

from coinbase.rest import RESTClient

from coinbaseutil2 import BlobbyTrader 

from claudeutil import ClaudeTrader, compare_recommendations, get_consensus_action

from pytrends.request import TrendReq

import pandas as pd





# Initialize pytrends with desired language and timezone

# hl='en-US' for English (US), tz=360 for GMT-6 (Central Time)

pytrends = TrendReq(hl='en-US', tz=360)

def googleTrendsRequest(keyword):
    """Fetches Google Trends data for a given keyword."""
    try:
        pytrends.build_payload([keyword], cat=0, timeframe='now 4-H', geo='', gprop='')
        interest_over_time_df = pytrends.interest_over_time()
        if not interest_over_time_df.empty:
            print(f"Google Trends data for {keyword}:")
            print(interest_over_time_df)
        else:
            print(f"No Google Trends data found for {keyword}")
    except Exception as e:
        print(f"Error fetching Google Trends data for {keyword}: {e}")

coinsToBuy = []

coinsToSell = []

coinsToHold = []

# LLM comparison mode: 'gemini', 'claude', or 'compare'
LLM_MODE = os.environ.get('LLM_MODE', 'compare')
REQUIRE_CONSENSUS = os.environ.get('REQUIRE_CONSENSUS', 'true').lower() == 'true'









def sendRecommendationRequest():

    response = client.models.generate_content(

    model="models/gemini-2.5-pro",

    contents="What 3 cryptocurrency meme coins listed on the coinbase exchange would a sophisticated trading bot designed for short-term appreciation recommend buying right now?  Once you have the top choices, number them and show me which of the coins chosen show the most positive social media trends in the last 4 hours. Put 3 plus signs around these choices at the end of your response.",

    config=config,

)

    return response



def sendCoinCheckRequest(coin):

    followUpResponse = client.models.generate_content(

    model="models/gemini-2.5-pro",

    contents='Would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the meme coin with symbol' + extracted_content + 'right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, follwed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket',

    config=config,

)

    return followUpResponse





def sendTrendCheckRequest(coin):

    followUpResponse = client.models.generate_content(

    model="models/gemini-2.5-pro",

    contents='Based on analysis  of recent data from Google Trends,, would a sophisticated trading bot designed for short-term appreciation recommend buying, selling, or holding the meme coin with symbol' + extracted_content + 'right now? Conclude your analysis with a left angle bracket, followed by two asterisks, followed by the name of the coin being analyzed, followed by a dash, followed by the string PRS, followed by another dash, follwed by the recommendation expressed as either the keyword BUY, SELL, or HOLD, followed by two asterisks, followed by a right angle bracket',

    config=config,

)

    return followUpResponse





def get_text_between_strings(main_string, start_string, end_string):

    """Extracts the text between two specified strings in a given main string.



    Args:

        main_string (str): The string to search within.

        start_string (str): The string marking the beginning of the desired text.

        end_string (str): The string marking the end of the desired text.



    Returns:

        str or None: The extracted text, or None if the start or end string is not found.

    """

    start_index = main_string.find(start_string)

    if start_index == -1:

        return None  # Start string not found



    # Adjust start_index to point after the start_string

    start_of_content = start_index + len(start_string)



    end_index = main_string.find(end_string, start_of_content)

    if end_index == -1:

        return None  # End string not found after the start string



    return main_string[start_of_content:end_index]



def get_text_after_delimiter(text_string, delimiter):

    """

    Extracts all text after the first occurrence of a specified delimiter.



    Args:

        text_string (str): The input string.

        delimiter (str): The delimiter to split the string by.



    Returns:

        str: The text after the delimiter, or an empty string if the delimiter

             is not found or if there's no text after it.

    """

    parts = text_string.split(delimiter, 1)  # Split only at the first occurrence

    if len(parts) > 1:

        return parts[1]

    else:

        return ""

def process_coin_with_comparison(coin_symbol, gemini_rec, use_trend_check=False):
    """Process a coin recommendation with optional LLM comparison.
    
    Args:
        coin_symbol: The coin symbol to analyze
        gemini_rec: The recommendation from Gemini (BUY, SELL, HOLD)
        use_trend_check: If True, use trend check; otherwise use coin check
    
    Returns:
        str or None: The final action to take
    """
    if coin_symbol is None:
        return None
    
    if LLM_MODE == 'gemini':
        return gemini_rec
    
    # Get Claude's recommendation
    if claude_trader:
        try:
            if use_trend_check:
                claude_response = claude_trader.send_trend_check_request(coin_symbol)
            else:
                claude_response = claude_trader.send_coin_check_request(coin_symbol)
            
            if claude_response:
                print(f"\n--- Claude Response for {coin_symbol} ---")
                print(claude_response)
                
                # Parse Claude's recommendation
                claude_rec = get_text_between_strings(claude_response, "-PRS-", "**>")
                
                if LLM_MODE == 'claude':
                    return claude_rec
                
                # Compare mode
                comparison = compare_recommendations(gemini_rec, claude_rec)
                print(f"\n[COMPARISON] Gemini: {comparison['gemini']}, Claude: {comparison['claude']}, Agree: {comparison['agree']}")
                
                return get_consensus_action(comparison, REQUIRE_CONSENSUS)
        except Exception as e:
            print(f"Error getting Claude recommendation: {e}")
            if LLM_MODE == 'compare':
                print("Falling back to Gemini recommendation only")
                return gemini_rec
    
    return gemini_rec

def buy_something(coinToBuy):

        print("\n--- Getting coin Product Details BEFORE for: ",(coinToBuy+"-USD") )

        usd_product = trader.get_product_details(coinToBuy+"-USD")

        if usd_product:

                print(json.dumps(usd_product.to_dict(), indent=2))



        else:

            print("Could not retrieve  product details.")

        trader.market_order_buy(coinToBuy+'-USD', '25.00')



        print("\n--- Getting coin Product Details AFTER for: ",(coinToBuy+"-USD") )

        usd_product = trader.get_product_details(coinToBuy+"-USD")

        if usd_product:

                print(json.dumps(usd_product.to_dict(), indent=2))



        else:

            print("Could not retrieve  product details.")

# Configure the Gemini client
client = genai.Client()

# Initialize Claude client if in compare or claude mode
claude_trader = None
if LLM_MODE in ['compare', 'claude']:
    try:
        claude_trader = ClaudeTrader()
        print(f"Claude client initialized (mode: {LLM_MODE})")
    except Exception as e:
        print(f"Warning: Could not initialize Claude client: {e}")
        if LLM_MODE == 'claude':
            raise
        LLM_MODE = 'gemini'  # Fall back to Gemini only



# Define the grounding tool, gives us realtime searches 

grounding_tool = types.Tool(

    google_search=types.GoogleSearch()

)



# Configure generation settings

config = types.GenerateContentConfig(

    tools=[grounding_tool]

)



# The Values below should be derived from environment variables obviously



BLOBS2 = os.environ.get('COINBASE_API_KEY')

BLOBS1 = os.environ.get('COINBASE_API_SECRET')



coinsToExclude = {'PEPE'}







# Make the request

response = sendRecommendationRequest()

# Print the grounded response

print(response.text)

print ("--------------ABOVE IS CONTENT OF INITIAL GEMINI RESPONSE----")

print ("------WE DOUBLE CHECK THE INITIAL RESPONSE WITH NEW QUERIES")

print ("----------")

doPython=True  # This makes the thing do no actual trading, should be renamed

trader = BlobbyTrader(BLOBS2, BLOBS1)

my_string = response.text

# get the text following the first numbered recommendation

delimiter_char = "1."

result = get_text_after_delimiter(response.text, delimiter_char)

#print(f"Text after '{delimiter_char}': '{result}'")

start = "("

end = ")"

extracted_content = get_text_between_strings(result, start, end)

print(f"Extracted content: {extracted_content}")

if extracted_content:
    googleTrendsRequest(extracted_content)
    followUpResponse = sendTrendCheckRequest(extracted_content)
    print(followUpResponse.text)
    start = "<**"
    end = "-PRS-"
    followUp_coin1 = get_text_between_strings(followUpResponse.text, start, end)
    start = "-PRS-"
    end = "**>"
    followUp_rec1 = get_text_between_strings(followUpResponse.text, start, end)
    print("Trend check coin and rec1: ", followUp_coin1, followUp_rec1)
    
    # Use comparison if enabled
    final_action = process_coin_with_comparison(extracted_content, followUp_rec1, use_trend_check=True)
    
    doPython = True
    if doPython:
        if extracted_content not in coinsToExclude:
            if final_action and 'BUY' in final_action:
                buy_something(followUp_coin1)
else:
    print("Could not extract coin 1 from response")

# get the text following the second  numbered recommendation

delimiter_char = "2."

result = get_text_after_delimiter(response.text, delimiter_char)

#print(f"Text after '{delimiter_char}': '{result}'")

start = "("

end = ")"

extracted_content = get_text_between_strings(result, start, end)

print(f"Extracted content: {extracted_content}")

if extracted_content:
    googleTrendsRequest(extracted_content)
    followUpResponse = sendCoinCheckRequest(extracted_content)
    print(followUpResponse.text)
    start = "<**"
    end = "-PRS-"
    followUp_coin1 = get_text_between_strings(followUpResponse.text, start, end)
    start = "-PRS-"
    end = "**>"
    followUp_rec1 = get_text_between_strings(followUpResponse.text, start, end)
    print("coin and rec1: ", followUp_coin1, followUp_rec1)
    
    # Use comparison if enabled
    final_action = process_coin_with_comparison(extracted_content, followUp_rec1, use_trend_check=False)
    
    doPython = True
    if doPython:
        if extracted_content not in coinsToExclude:
            if final_action and 'BUY' in final_action:
                buy_something(followUp_coin1)
else:
    print("Could not extract coin 2 from response")

# get the text following the third  numbered recommendation

delimiter_char = "3."

result = get_text_after_delimiter(response.text, delimiter_char)

#print(f"Text after '{delimiter_char}': '{result}'")

start = "("

end = ")"

extracted_content = get_text_between_strings(result, start, end)

print(f"Extracted content: {extracted_content}")

if extracted_content:
    googleTrendsRequest(extracted_content)
    followUpResponse = sendCoinCheckRequest(extracted_content)
    print(followUpResponse.text)
    start = "<**"
    end = "-PRS-"
    followUp_coin1 = get_text_between_strings(followUpResponse.text, start, end)
    if followUp_coin1 is not None:
        start = "-PRS-"
        end = "**>"
        followUp_rec1 = get_text_between_strings(followUpResponse.text, start, end)
        print("coin and rec1: ", followUp_coin1, followUp_rec1)
        
        # Use comparison if enabled
        final_action = process_coin_with_comparison(extracted_content, followUp_rec1, use_trend_check=False)
        
        if final_action and 'BUY' in final_action:
            coinsToBuy.append(followUp_coin1)
        doPython = True
        if doPython:
            if extracted_content not in coinsToExclude:
                if final_action and 'BUY' in final_action:
                    buy_something(followUp_coin1)
    else:
        print("Could not extract coin 3 from response")

# get the text after the string that indicates the social media recommendation

delimiter_char = "+++"

result = get_text_after_delimiter(response.text, delimiter_char)

print(f"Text after '{delimiter_char}': '{result}'")

start = "("

end = ")"

extracted_content = get_text_between_strings(result, start, end)

print(f"Extracted content: {extracted_content}")

if extracted_content:
    googleTrendsRequest(extracted_content)
    followUpResponse = sendTrendCheckRequest(extracted_content)
    print(followUpResponse.text)
    start = "<**"
    end = "-PRS-"
    followUp_coin1 = get_text_between_strings(followUpResponse.text, start, end)
    start = "-PRS-"
    end = "**>"
    followUp_rec1 = get_text_between_strings(followUpResponse.text, start, end)
    print("Trend check coin and rec1: ", followUp_coin1, followUp_rec1)
    
    # Use comparison if enabled
    final_action = process_coin_with_comparison(extracted_content, followUp_rec1, use_trend_check=True)
    
    if final_action and 'BUY' in final_action:
        coinsToBuy.append(followUp_coin1)
    doPython = True
    if doPython:
        if extracted_content not in coinsToExclude:
            if final_action and 'BUY' in final_action:
                buy_something(followUp_coin1)
else:
    print("No social media recommendation found in response")

# Print summary
print("\n" + "="*50)
print(f"LLM MODE: {LLM_MODE}")
print(f"REQUIRE CONSENSUS: {REQUIRE_CONSENSUS}")
print(f"Coins to buy: {coinsToBuy}")
print("="*50)
