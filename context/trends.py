"""Google Trends integration for context gathering."""

from typing import Optional

try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False
    TrendReq = None


def get_trends_context(keyword: str, timeframe: str = 'now 7-d') -> Optional[str]:
    """Fetch Google Trends data for a given keyword.
    
    Args:
        keyword: The keyword to search for trends
        timeframe: Timeframe for trends data (default: 'now 7-d' for last 7 days)
        
    Returns:
        Formatted string with trends data for LLM context, or None if no data
    """
    if not PYTRENDS_AVAILABLE:
        print("Warning: pytrends not installed. Install with: pip install pytrends")
        return None
    
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload([keyword], cat=0, timeframe=timeframe, geo='', gprop='')
        interest_df = pytrends.interest_over_time()
        
        if interest_df.empty:
            print(f"No Google Trends data found for '{keyword}'")
            return None
        
        # Calculate statistics
        recent_values = interest_df[keyword].tail(10).tolist()
        avg_interest = interest_df[keyword].mean()
        max_interest = interest_df[keyword].max()
        min_interest = interest_df[keyword].min()
        current_value = recent_values[-1] if recent_values else 0
        
        # Determine trend direction
        if len(recent_values) >= 2:
            trend_direction = "increasing" if recent_values[-1] > avg_interest else "decreasing"
        else:
            trend_direction = "stable"
        
        # Format for LLM context
        context = f"""---BEGIN GOOGLE TRENDS DATA---
Keyword: {keyword}
Timeframe: {timeframe}
Trend direction: {trend_direction}
Current interest level: {current_value}
Average interest: {avg_interest:.1f}
Maximum interest: {max_interest}
Minimum interest: {min_interest}
Recent data points: {recent_values}
Total data points: {len(interest_df)}
---END GOOGLE TRENDS DATA---"""
        
        return context
        
    except Exception as e:
        print(f"Error fetching Google Trends data for '{keyword}': {e}")
        return None


def get_related_queries(keyword: str) -> Optional[str]:
    """Fetch related queries for a keyword from Google Trends.
    
    Args:
        keyword: The keyword to search for related queries
        
    Returns:
        Formatted string with related queries, or None if no data
    """
    if not PYTRENDS_AVAILABLE:
        return None
    
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload([keyword], cat=0, timeframe='now 7-d', geo='', gprop='')
        related = pytrends.related_queries()
        
        if not related or keyword not in related:
            return None
        
        top_queries = related[keyword].get('top')
        rising_queries = related[keyword].get('rising')
        
        context_parts = []
        
        if top_queries is not None and not top_queries.empty:
            top_list = top_queries.head(5)['query'].tolist()
            context_parts.append(f"Top related queries: {', '.join(top_list)}")
        
        if rising_queries is not None and not rising_queries.empty:
            rising_list = rising_queries.head(5)['query'].tolist()
            context_parts.append(f"Rising queries: {', '.join(rising_list)}")
        
        if context_parts:
            return "\n".join(context_parts)
        
        return None
        
    except Exception as e:
        print(f"Error fetching related queries for '{keyword}': {e}")
        return None
