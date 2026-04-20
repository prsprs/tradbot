"""Prompt templates for the multi-LLM advisory system."""

from typing import List, Optional


def get_word_limit_instructions(
    max_words: int,
    max_reasoning_points: int,
    verbose_mode: bool = False
) -> str:
    """Get word limit instructions for prompts.
    
    Args:
        max_words: Maximum words for the response
        max_reasoning_points: Maximum reasoning bullet points
        verbose_mode: If True, return empty string (no limits)
        
    Returns:
        Formatted instruction string
    """
    if verbose_mode:
        return ""
    
    return f"""
IMPORTANT: Keep your response concise.
- Maximum {max_words} words for your analysis
- Maximum {max_reasoning_points} key reasoning points
- Focus on the most important factors only"""


def get_yes_no_output_instructions() -> str:
    """Get output format instructions for Yes/No evaluation mode."""
    return """
Format your response exactly as follows:
<ANSWER>YES|NO|UNKNOWN</ANSWER>
<CONFIDENCE>0-100</CONFIDENCE>
<REASONING>Your brief explanation</REASONING>"""


def get_open_ended_output_instructions(choices: Optional[List[str]] = None) -> str:
    """Get output format instructions for open-ended questions.
    
    Args:
        choices: Optional list of choices for decision questions
        
    Returns:
        Formatted instruction string
    """
    if choices:
        choices_str = ", ".join(choices)
        return f"""
Your available choices are: {choices_str}

Conclude your response with your choice in this format:
<CHOICE>your_choice</CHOICE>
<CONFIDENCE>0-100</CONFIDENCE>
<REASONING>Your brief explanation</REASONING>"""
    
    return """
Conclude your response with:
<SUMMARY>Your key recommendation in one sentence</SUMMARY>
<CONFIDENCE>0-100</CONFIDENCE>
<REASONING>Your brief explanation</REASONING>"""


def get_prediction_output_instructions() -> str:
    """Get output format instructions for prediction questions."""
    return """
Conclude your response with your prediction:
<PREDICTION>LIKELY|UNLIKELY|UNCERTAIN</PREDICTION>
<CONFIDENCE>0-100</CONFIDENCE>
<REASONING>Your brief explanation</REASONING>"""


def get_base_prompt(
    user_prompt: str,
    choices: Optional[List[str]] = None,
    yes_no_eval: bool = False,
    context_section: str = "",
    file_context: str = "",
    max_words: int = 300,
    max_reasoning_points: int = 3,
    verbose_mode: bool = False
) -> str:
    """Build the base prompt for Round 1 analysis.
    
    Args:
        user_prompt: The user's question or decision
        choices: Optional list of choices
        yes_no_eval: Whether this is a yes/no evaluation
        context_section: Optional context (trends, etc.)
        file_context: Optional reference file content
        max_words: Maximum response words
        max_reasoning_points: Maximum reasoning points
        verbose_mode: If True, ignore word limits
        
    Returns:
        Complete prompt string
    """
    # Build context sections
    context_parts = []
    
    if file_context:
        context_parts.append(f"""The following reference files have been provided for context:

{file_context}
""")
    
    if context_section:
        context_parts.append(f"""Additional context:

{context_section}
""")
    
    full_context = "\n".join(context_parts) if context_parts else ""
    
    # Choose output instructions based on mode
    if yes_no_eval:
        output_instructions = get_yes_no_output_instructions()
    elif choices:
        output_instructions = get_open_ended_output_instructions(choices)
    else:
        output_instructions = get_open_ended_output_instructions()
    
    # Get word limit instructions
    word_limits = get_word_limit_instructions(max_words, max_reasoning_points, verbose_mode)
    
    # Build choices section
    choices_section = ""
    if choices:
        choices_section = f"\nAvailable choices: {', '.join(choices)}\n"
    
    prompt = f"""You are participating in a multi-AI analysis system. Your role is to provide 
an independent, well-reasoned response to the following question.

{full_context}

QUESTION:
{user_prompt}
{choices_section}
Please provide:
1. Your recommendation or prediction
2. Your confidence level (0-100)
3. Key reasoning points ({max_reasoning_points} bullet points maximum)
{word_limits}
{output_instructions}"""

    return prompt


def get_integration_prompt(
    user_prompt: str,
    own_response: str,
    peer_analyses: str,
    yes_no_eval: bool = False,
    choices: Optional[List[str]] = None,
    max_words: int = 200,
    verbose_mode: bool = False
) -> str:
    """Build the integration prompt for Round 2.
    
    Args:
        user_prompt: The original user question
        own_response: This LLM's Round 1 response
        peer_analyses: Formatted string of peer analyses
        yes_no_eval: Whether this is a yes/no evaluation
        choices: Optional list of choices
        max_words: Maximum words for response
        verbose_mode: If True, ignore word limits
        
    Returns:
        Complete integration prompt string
    """
    # Choose output instructions
    if yes_no_eval:
        output_instructions = get_yes_no_output_instructions()
        reflection_guidance = """After reviewing your peers' perspectives:
- Maintain, revise, or change your YES/NO/UNKNOWN answer
- Update your confidence level if warranted
- Note any compelling arguments from peers"""
    else:
        output_instructions = get_open_ended_output_instructions(choices)
        reflection_guidance = """After reviewing your peers' perspectives, you may:
- Maintain your original position with additional reasoning
- Revise your position based on compelling arguments
- Acknowledge uncertainty if perspectives are balanced"""
    
    # Word limits
    word_limit_text = ""
    if not verbose_mode:
        word_limit_text = f"""
IMPORTANT: Keep your reflection concise.
- Maximum {max_words} words
- Focus only on significant new insights from peer analyses
- Do not repeat your original reasoning"""
    
    prompt = f"""You previously analyzed this question:

{user_prompt}

Your initial response was:
{own_response}

Other AI systems provided these analyses:

---BEGIN PEER ANALYSES---
{peer_analyses}
---END PEER ANALYSES---

{reflection_guidance}

Provide your updated recommendation with reasoning.
{word_limit_text}
{output_instructions}"""

    return prompt


def get_summarization_prompt(
    user_prompt: str,
    all_responses: str,
    yes_no_eval: bool = False,
    consensus_info: str = "",
    max_words: int = 500
) -> str:
    """Build the summarization prompt for the final synthesis.
    
    Args:
        user_prompt: The original user question
        all_responses: All LLM responses formatted
        yes_no_eval: Whether this was a yes/no evaluation
        consensus_info: Information about consensus reached
        max_words: Maximum words for summary
        
    Returns:
        Complete summarization prompt string
    """
    yes_no_section = ""
    if yes_no_eval:
        yes_no_section = f"""
This was a YES/NO evaluation question.
{consensus_info}
"""

    prompt = f"""You are tasked with summarizing a multi-AI analysis session.

ORIGINAL QUESTION:
{user_prompt}
{yes_no_section}
LLM RESPONSES:
{all_responses}

Please produce a concise summary (maximum {max_words} words) that:
1. States the overall conclusion or majority position
2. Highlights 2-3 major themes from the analyses
3. Notes significant points of disagreement
4. Identifies any important caveats or uncertainties

Format your response as:

## Conclusion
[One sentence stating the overall finding]

## Key Themes
- [Theme 1]
- [Theme 2]
- [Theme 3 if applicable]

## Areas of Disagreement
[Brief description of where LLMs differed, if any]

## Caveats
[Important limitations or uncertainties noted]"""

    return prompt


def format_peer_analyses(responses: dict, exclude_llm: Optional[str] = None) -> str:
    """Format peer analyses for integration prompts.
    
    Args:
        responses: Dict mapping LLM names to their responses
        exclude_llm: Optional LLM name to exclude (the one receiving the prompt)
        
    Returns:
        Formatted string of peer analyses
    """
    parts = []
    for llm_name, response in responses.items():
        if exclude_llm and llm_name == exclude_llm:
            continue
        parts.append(f"[{llm_name.upper()}]:\n{response}")
    
    return "\n\n".join(parts)


def format_all_responses(responses: dict) -> str:
    """Format all LLM responses for summarization.
    
    Args:
        responses: Dict mapping LLM names to their responses
        
    Returns:
        Formatted string of all responses
    """
    parts = []
    for llm_name, response in responses.items():
        parts.append(f"--- {llm_name.upper()} ---\n{response}")
    
    return "\n\n".join(parts)
