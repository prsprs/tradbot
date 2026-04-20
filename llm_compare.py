#!/usr/bin/env python3
"""Multi-LLM Advisory System - Compare and integrate LLM perspectives.

This program leverages multiple LLMs to evaluate questions, make predictions,
and provide recommendations through comparison and integration of diverse AI perspectives.
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from config import Config, parse_args, estimate_cost, validate_config
from context.trends import get_trends_context
from history.recorder import HistoryRecorder
from prompts.templates import (
    get_base_prompt,
    get_integration_prompt,
    get_summarization_prompt,
    format_peer_analyses,
    format_all_responses,
)
from llm_utils.base import LLMClient


# Maximum characters per reference file
MAX_FILE_CONTEXT_SIZE = 50000
MAX_TOTAL_REFERENCE_SIZE = 150000


def get_llm_client(llm_name: str) -> Optional[LLMClient]:
    """Get an LLM client by name.
    
    Args:
        llm_name: Name of the LLM (gemini, claude, openai, grok, perplexity)
        
    Returns:
        LLMClient instance or None if not available
    """
    try:
        if llm_name == 'gemini':
            from llm_utils.gemini_client import GeminiClient
            return GeminiClient()
        elif llm_name == 'claude':
            from llm_utils.claude_client import ClaudeClient
            return ClaudeClient()
        elif llm_name == 'openai':
            from llm_utils.openai_client import OpenAIClient
            return OpenAIClient()
        elif llm_name == 'grok':
            from llm_utils.grok_client import GrokClient
            return GrokClient()
        elif llm_name == 'perplexity':
            from llm_utils.perplexity_client import PerplexityClient
            return PerplexityClient()
        else:
            print(f"Unknown LLM: {llm_name}")
            return None
    except ValueError as e:
        print(f"Could not initialize {llm_name}: {e}")
        return None


def get_file_context(file_paths: List[str], max_per_file: int = MAX_FILE_CONTEXT_SIZE, 
                     max_total: int = MAX_TOTAL_REFERENCE_SIZE) -> str:
    """Read and format reference files for LLM context.
    
    Args:
        file_paths: List of file paths to read
        max_per_file: Maximum characters per file
        max_total: Maximum total characters for all files
        
    Returns:
        Formatted string with file contents
    """
    context_parts = []
    total_size = 0
    
    for path in file_paths:
        if not os.path.exists(path):
            print(f"Warning: Reference file not found: {path}")
            continue
        
        filename = os.path.basename(path)
        
        try:
            with open(path, 'r') as f:
                content = f.read()
        except IOError as e:
            print(f"Warning: Could not read file {path}: {e}")
            continue
        
        # Truncate if too large
        truncated = False
        if len(content) > max_per_file:
            content = content[:max_per_file]
            truncated = True
        
        # Check total size
        if total_size + len(content) > max_total:
            remaining = max_total - total_size
            if remaining > 1000:
                content = content[:remaining]
                truncated = True
            else:
                print(f"Warning: Skipping {filename} - total reference size limit reached")
                continue
        
        truncation_note = "\n... [truncated]" if truncated else ""
        context_parts.append(f"""---BEGIN REFERENCE FILE: {filename}---
{content}{truncation_note}
---END REFERENCE FILE: {filename}---""")
        
        total_size += len(content)
    
    return "\n\n".join(context_parts)


def parse_response(response: str, yes_no_eval: bool = False) -> Dict[str, Any]:
    """Parse structured output from LLM response.
    
    Args:
        response: The LLM response text
        yes_no_eval: Whether this is a yes/no evaluation
        
    Returns:
        Dict with parsed values (answer/choice, confidence, reasoning)
    """
    result = {
        "raw_response": response,
        "answer": None,
        "confidence": None,
        "reasoning": None,
    }
    
    if not response:
        return result
    
    # Parse YES/NO/UNKNOWN answer
    if yes_no_eval:
        answer_match = re.search(r'<ANSWER>\s*(YES|NO|UNKNOWN)\s*</ANSWER>', response, re.IGNORECASE)
        if answer_match:
            result["answer"] = answer_match.group(1).upper()
    
    # Parse CHOICE
    choice_match = re.search(r'<CHOICE>\s*([^<]+)\s*</CHOICE>', response, re.IGNORECASE)
    if choice_match:
        result["answer"] = choice_match.group(1).strip()
    
    # Parse PREDICTION
    pred_match = re.search(r'<PREDICTION>\s*(LIKELY|UNLIKELY|UNCERTAIN)\s*</PREDICTION>', response, re.IGNORECASE)
    if pred_match:
        result["answer"] = pred_match.group(1).upper()
    
    # Parse SUMMARY
    summary_match = re.search(r'<SUMMARY>\s*([^<]+)\s*</SUMMARY>', response, re.IGNORECASE)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()
    
    # Parse confidence
    conf_match = re.search(r'<CONFIDENCE>\s*(\d+)\s*</CONFIDENCE>', response, re.IGNORECASE)
    if conf_match:
        result["confidence"] = int(conf_match.group(1))
    
    # Parse reasoning
    reason_match = re.search(r'<REASONING>\s*([^<]+)\s*</REASONING>', response, re.IGNORECASE | re.DOTALL)
    if reason_match:
        result["reasoning"] = reason_match.group(1).strip()
    
    return result


def check_consensus(responses: Dict[str, Dict[str, Any]], yes_no_eval: bool = False) -> Tuple[bool, Optional[str], str]:
    """Check if LLMs reached consensus.
    
    Args:
        responses: Dict mapping LLM names to parsed responses
        yes_no_eval: Whether this is a yes/no evaluation
        
    Returns:
        Tuple of (consensus_reached, majority_answer, count_string)
    """
    answers = {}
    for llm, resp in responses.items():
        answer = resp.get("answer")
        if answer:
            answers[answer] = answers.get(answer, 0) + 1
    
    if not answers:
        return False, None, "0/0"
    
    total = sum(answers.values())
    max_count = max(answers.values())
    majority_answer = max(answers.keys(), key=lambda k: answers[k])
    
    # Consensus if more than half agree
    consensus = max_count > total / 2
    count_string = f"{max_count}/{total}"
    
    return consensus, majority_answer if consensus else None, count_string


def run_single_mode(config: Config, context: str, file_context: str) -> Dict[str, Any]:
    """Run single LLM mode.
    
    Args:
        config: Configuration object
        context: Additional context (trends, etc.)
        file_context: Reference file content
        
    Returns:
        Result dict with response and parsed data
    """
    client = get_llm_client(config.primary_llm)
    if not client:
        return {"error": f"Could not initialize {config.primary_llm}"}
    
    prompt = get_base_prompt(
        user_prompt=config.prompt,
        choices=config.choices,
        yes_no_eval=config.yes_no_eval,
        context_section=context,
        file_context=file_context,
        max_words=config.max_response_words,
        max_reasoning_points=config.max_reasoning_points,
        verbose_mode=config.verbose_mode
    )
    
    print(f"\n=== LLM ADVISOR (Single Mode: {config.primary_llm}) ===")
    print(f"Prompt: {config.prompt[:100]}{'...' if len(config.prompt) > 100 else ''}")
    
    response = client.send_request(prompt)
    parsed = parse_response(response, config.yes_no_eval)
    
    answer = parsed.get("answer", "N/A")
    confidence = parsed.get("confidence")
    conf_str = f" ({confidence}%)" if confidence else ""
    print(f"  {config.primary_llm.capitalize()}: {answer}{conf_str}")
    
    if config.show_reasoning and parsed.get("reasoning"):
        print(f"    Reasoning: {parsed.get('reasoning')}")
    
    if config.log_integration_rounds:
        print(f"\n--- {config.primary_llm.capitalize()} Response ---")
        print(response)
    
    return {
        "mode": "single",
        "llm": config.primary_llm,
        "response": response,
        "parsed": parsed,
        "answer": parsed.get("answer"),
        "confidence": parsed.get("confidence"),
    }


def run_compare_mode(config: Config, context: str, file_context: str) -> Dict[str, Any]:
    """Run compare mode - query multiple LLMs independently.
    
    Args:
        config: Configuration object
        context: Additional context (trends, etc.)
        file_context: Reference file content
        
    Returns:
        Result dict with all responses and consensus info
    """
    print(f"\n=== LLM COMPARISON ===")
    print(f"Prompt: {config.prompt[:100]}{'...' if len(config.prompt) > 100 else ''}")
    if config.choices:
        print(f"Choices: {', '.join(config.choices)}")
    
    prompt = get_base_prompt(
        user_prompt=config.prompt,
        choices=config.choices,
        yes_no_eval=config.yes_no_eval,
        context_section=context,
        file_context=file_context,
        max_words=config.max_response_words,
        max_reasoning_points=config.max_reasoning_points,
        verbose_mode=config.verbose_mode
    )
    
    responses = {}
    parsed_responses = {}
    
    for llm_name in config.compare_llms:
        client = get_llm_client(llm_name)
        if not client:
            print(f"  Skipping {llm_name} (not available)")
            continue
        
        print(f"\nQuerying {llm_name}...")
        response = client.send_request(prompt)
        
        if response:
            responses[llm_name] = response
            parsed = parse_response(response, config.yes_no_eval)
            parsed_responses[llm_name] = parsed
            
            answer = parsed.get("answer", "N/A")
            confidence = parsed.get("confidence")
            conf_str = f" ({confidence}%)" if confidence else ""
            print(f"  {llm_name.capitalize()}: {answer}{conf_str}")
            
            if config.show_reasoning and parsed.get("reasoning"):
                print(f"    Reasoning: {parsed.get('reasoning')}")
            
            if config.log_integration_rounds:
                print(f"\n--- {llm_name.capitalize()} Response ---")
                print(response)
    
    # Check consensus
    consensus, majority, count = check_consensus(parsed_responses, config.yes_no_eval)
    
    # Build comparison summary
    comparison_parts = [f"{k}: {v.get('answer', 'N/A')}" for k, v in parsed_responses.items()]
    print(f"\n[COMPARISON] {', '.join(comparison_parts)}")
    
    if consensus:
        print(f"[RESULT] Majority recommends: {majority} ({count})")
    else:
        if config.require_consensus:
            print(f"[RESULT] No consensus reached ({count}) - no recommendation")
        elif config.integration_tiebreaker in parsed_responses:
            tiebreaker_answer = parsed_responses[config.integration_tiebreaker].get("answer")
            print(f"[RESULT] No consensus ({count}). Using {config.integration_tiebreaker}: {tiebreaker_answer}")
            majority = tiebreaker_answer
    
    return {
        "mode": "compare",
        "responses": responses,
        "parsed": parsed_responses,
        "consensus_reached": consensus,
        "consensus_count": count,
        "final_recommendation": majority,
    }


def run_integrate_mode(config: Config, context: str, file_context: str) -> Dict[str, Any]:
    """Run integrate mode - multi-round deliberation with peer review.
    
    Args:
        config: Configuration object
        context: Additional context (trends, etc.)
        file_context: Reference file content
        
    Returns:
        Result dict with all responses, consensus info, and flips
    """
    print(f"\n=== LLM INTEGRATION ===")
    print(f"Prompt: {config.prompt[:100]}{'...' if len(config.prompt) > 100 else ''}")
    if config.choices:
        print(f"Choices: {', '.join(config.choices)}")
    
    # Initialize LLM clients
    clients = {}
    for llm_name in config.compare_llms:
        client = get_llm_client(llm_name)
        if client:
            clients[llm_name] = client
        else:
            print(f"  Skipping {llm_name} (not available)")
    
    if len(clients) < 2:
        return {"error": "Need at least 2 LLMs for integration mode"}
    
    # === ROUND 1: Independent Analysis ===
    print(f"\n--- Round 1 (Independent Analysis) ---")
    
    base_prompt = get_base_prompt(
        user_prompt=config.prompt,
        choices=config.choices,
        yes_no_eval=config.yes_no_eval,
        context_section=context,
        file_context=file_context,
        max_words=config.max_response_words,
        max_reasoning_points=config.max_reasoning_points,
        verbose_mode=config.verbose_mode
    )
    
    r1_responses = {}
    r1_parsed = {}
    
    if config.simple_integration:
        # Simple integration: only primary LLM does Round 1
        primary = config.primary_llm
        if primary not in clients:
            primary = list(clients.keys())[0]
        
        print(f"Querying {primary} (primary)...")
        response = clients[primary].send_request(base_prompt)
        if response:
            r1_responses[primary] = response
            r1_parsed[primary] = parse_response(response, config.yes_no_eval)
            
            answer = r1_parsed[primary].get("answer", "N/A")
            confidence = r1_parsed[primary].get("confidence")
            conf_str = f" ({confidence}%)" if confidence else ""
            print(f"  {primary.capitalize()}: {answer}{conf_str}")
            
            if config.show_reasoning and r1_parsed[primary].get("reasoning"):
                print(f"    Reasoning: {r1_parsed[primary].get('reasoning')}")
    else:
        # Full integration: all LLMs do Round 1
        for llm_name, client in clients.items():
            print(f"Querying {llm_name}...")
            response = client.send_request(base_prompt)
            
            if response:
                r1_responses[llm_name] = response
                parsed = parse_response(response, config.yes_no_eval)
                r1_parsed[llm_name] = parsed
                
                answer = parsed.get("answer", "N/A")
                confidence = parsed.get("confidence")
                conf_str = f" ({confidence}%)" if confidence else ""
                print(f"  {llm_name.capitalize()}: {answer}{conf_str}")
                
                if config.show_reasoning and parsed.get("reasoning"):
                    print(f"    Reasoning: {parsed.get('reasoning')}")
                
                if config.log_integration_rounds:
                    print(f"\n--- {llm_name.capitalize()} Round 1 Response ---")
                    print(response)
    
    # Log Round 1 summary
    r1_summary = ", ".join(f"{k}: {v.get('answer', 'N/A')}" for k, v in r1_parsed.items())
    print(f"\n[INTEGRATE] Round 1 - {r1_summary}")
    
    # === ROUND 2: Cross-Pollination ===
    print(f"\n--- Round 2 (After Peer Review) ---")
    
    r2_responses = {}
    r2_parsed = {}
    flips = []
    
    if config.simple_integration:
        # Simple integration: other LLMs reflect on primary's analysis
        primary = list(r1_responses.keys())[0]
        primary_response = r1_responses[primary]
        
        for llm_name, client in clients.items():
            if llm_name == primary:
                # Primary keeps its response
                r2_responses[llm_name] = primary_response
                r2_parsed[llm_name] = r1_parsed[primary]
                continue
            
            print(f"Querying {llm_name} (reflecting on {primary})...")
            
            integration_prompt = get_integration_prompt(
                user_prompt=config.prompt,
                own_response="[First analysis from another AI]",
                peer_analyses=f"[{primary.upper()}]:\n{primary_response}",
                yes_no_eval=config.yes_no_eval,
                choices=config.choices,
                max_words=config.round_two_output_limit,
                verbose_mode=config.verbose_mode
            )
            
            response = client.send_request(integration_prompt)
            if response:
                r2_responses[llm_name] = response
                parsed = parse_response(response, config.yes_no_eval)
                r2_parsed[llm_name] = parsed
                
                answer = parsed.get("answer", "N/A")
                confidence = parsed.get("confidence")
                conf_str = f" ({confidence}%)" if confidence else ""
                print(f"  {llm_name.capitalize()}: {answer}{conf_str}")
                
                if config.show_reasoning and parsed.get("reasoning"):
                    print(f"    Reasoning: {parsed.get('reasoning')}")
                
                if config.log_integration_rounds:
                    print(f"\n--- {llm_name.capitalize()} Round 2 Response ---")
                    print(response)
    else:
        # Full integration: each LLM sees all peers
        for llm_name, client in clients.items():
            peer_text = format_peer_analyses(r1_responses, exclude_llm=llm_name)
            own_response = r1_responses.get(llm_name, "")
            
            print(f"Querying {llm_name} (with peer review)...")
            
            integration_prompt = get_integration_prompt(
                user_prompt=config.prompt,
                own_response=own_response,
                peer_analyses=peer_text,
                yes_no_eval=config.yes_no_eval,
                choices=config.choices,
                max_words=config.round_two_output_limit,
                verbose_mode=config.verbose_mode
            )
            
            response = client.send_request(integration_prompt)
            if response:
                r2_responses[llm_name] = response
                parsed = parse_response(response, config.yes_no_eval)
                r2_parsed[llm_name] = parsed
                
                answer = parsed.get("answer", "N/A")
                confidence = parsed.get("confidence")
                conf_str = f" ({confidence}%)" if confidence else ""
                
                # Check for flip
                r1_answer = r1_parsed.get(llm_name, {}).get("answer")
                if r1_answer and answer != r1_answer and answer != "N/A":
                    print(f"  {llm_name.capitalize()}: {answer}{conf_str}  [FLIP from {r1_answer}]")
                    flips.append({"llm": llm_name, "from": r1_answer, "to": answer})
                else:
                    print(f"  {llm_name.capitalize()}: {answer}{conf_str}")
                
                if config.show_reasoning and parsed.get("reasoning"):
                    print(f"    Reasoning: {parsed.get('reasoning')}")
                
                if config.log_integration_rounds:
                    print(f"\n--- {llm_name.capitalize()} Round 2 Response ---")
                    print(response)
    
    # Log Round 2 summary
    r2_summary = ", ".join(f"{k}: {v.get('answer', 'N/A')}" for k, v in r2_parsed.items())
    print(f"\n[INTEGRATE] Round 2 - {r2_summary}")
    
    # Check final consensus
    consensus, majority, count = check_consensus(r2_parsed, config.yes_no_eval)
    
    if consensus:
        print(f"\n[INTEGRATE FINAL] Consensus reached: {majority} ({count} agree)")
    else:
        if config.integration_tiebreaker in r2_parsed and config.integration_tiebreaker != 'none':
            tiebreaker_answer = r2_parsed[config.integration_tiebreaker].get("answer")
            print(f"\n[INTEGRATE FINAL] No consensus ({count}). Tiebreaker ({config.integration_tiebreaker}): {tiebreaker_answer}")
            majority = tiebreaker_answer
        else:
            print(f"\n[INTEGRATE FINAL] No consensus ({count})")
    
    # === SUMMARIZATION PHASE ===
    print(f"\n--- Summarization (by {config.summarization_llm}) ---")
    
    summary_client = get_llm_client(config.summarization_llm)
    summary = None
    
    if summary_client:
        all_responses_text = format_all_responses(r2_responses)
        consensus_info = f"Consensus: {'YES' if consensus else 'NO'} - {majority if majority else 'No majority'} ({count})"
        
        summary_prompt = get_summarization_prompt(
            user_prompt=config.prompt,
            all_responses=all_responses_text,
            yes_no_eval=config.yes_no_eval,
            consensus_info=consensus_info,
            max_words=config.summarization_max_words
        )
        
        summary = summary_client.send_request(summary_prompt)
        if summary:
            print(f"\n{summary}")
    
    return {
        "mode": "integrate",
        "round_1_responses": r1_responses,
        "round_1_parsed": r1_parsed,
        "round_2_responses": r2_responses,
        "round_2_parsed": r2_parsed,
        "flips": flips,
        "consensus_reached": consensus,
        "consensus_count": count,
        "final_recommendation": majority,
        "summary": summary,
    }


def format_output(result: Dict[str, Any], config: Config) -> str:
    """Format result for output based on configured format.
    
    Args:
        result: The result dict from processing
        config: Configuration object
        
    Returns:
        Formatted output string
    """
    if config.output_format == 'json':
        # Remove raw responses for cleaner JSON output
        output = {
            "mode": result.get("mode"),
            "prompt": config.prompt,
            "final_recommendation": result.get("final_recommendation"),
            "consensus_reached": result.get("consensus_reached"),
            "consensus_count": result.get("consensus_count"),
        }
        if result.get("flips"):
            output["flips"] = result["flips"]
        return json.dumps(output, indent=2)
    
    elif config.output_format == 'markdown':
        lines = [
            f"# LLM Advisory Result",
            f"",
            f"**Mode:** {result.get('mode')}",
            f"**Prompt:** {config.prompt}",
            f"",
        ]
        if result.get("final_recommendation"):
            lines.append(f"## Recommendation: {result.get('final_recommendation')}")
        if result.get("consensus_reached") is not None:
            lines.append(f"**Consensus:** {'Yes' if result.get('consensus_reached') else 'No'} ({result.get('consensus_count', 'N/A')})")
        if result.get("summary"):
            lines.append(f"\n## Summary\n{result.get('summary')}")
        return "\n".join(lines)
    
    # Default text format - already printed during execution
    return ""


def main():
    """Main entry point."""
    config = parse_args()
    
    # Validate configuration
    errors = validate_config(config)
    if errors:
        print("Configuration errors:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    # What-if mode: show cost estimate and exit
    if config.what_if_mode:
        print("\n=== WHAT-IF MODE (Cost Estimation) ===")
        estimate = estimate_cost(config)
        print(f"Mode: {estimate['mode']}")
        print(f"LLMs: {estimate['num_llms']}")
        print(f"Estimated API calls: {estimate['num_calls']}")
        print(f"Simple integration: {estimate['simple_integration']}")
        print(f"Estimated input tokens: {estimate['estimated_input_tokens']:,}")
        print(f"Estimated output tokens: {estimate['estimated_output_tokens']:,}")
        print(f"Estimated cost: ${estimate['estimated_cost_usd']:.4f}")
        print("\nNo LLM calls made.")
        sys.exit(0)
    
    # Gather context
    context = ""
    if config.google_trends_keyword:
        print(f"Fetching Google Trends data for '{config.google_trends_keyword}'...")
        trends_context = get_trends_context(config.google_trends_keyword)
        if trends_context:
            context = trends_context
            print("  Google Trends data retrieved")
    
    # Load reference files
    file_context = ""
    if config.reference_files:
        print(f"Loading {len(config.reference_files)} reference file(s)...")
        file_context = get_file_context(config.reference_files)
        if file_context:
            print("  Reference files loaded")
    
    # Run appropriate mode
    if config.mode == 'single':
        result = run_single_mode(config, context, file_context)
    elif config.mode == 'compare':
        result = run_compare_mode(config, context, file_context)
    elif config.mode == 'integrate':
        result = run_integrate_mode(config, context, file_context)
    else:
        print(f"Unknown mode: {config.mode}")
        sys.exit(1)
    
    # Check for errors
    if result.get("error"):
        print(f"\nError: {result['error']}")
        sys.exit(1)
    
    # Format and print output
    output = format_output(result, config)
    if output:
        print(f"\n{output}")
    
    # Record to history
    if config.mode in ['compare', 'integrate']:
        recorder = HistoryRecorder(config.history_file)
        
        # Prepare responses for recording
        r1_responses = {}
        if config.mode == 'compare':
            for llm, parsed in result.get("parsed", {}).items():
                r1_responses[llm] = {
                    "choice": parsed.get("answer"),
                    "confidence": parsed.get("confidence"),
                    "reasoning_summary": parsed.get("reasoning", "")[:200] if parsed.get("reasoning") else None
                }
        else:
            for llm, parsed in result.get("round_1_parsed", {}).items():
                r1_responses[llm] = {
                    "choice": parsed.get("answer"),
                    "confidence": parsed.get("confidence"),
                    "reasoning_summary": parsed.get("reasoning", "")[:200] if parsed.get("reasoning") else None
                }
        
        r2_responses = None
        if config.mode == 'integrate':
            r2_responses = {}
            for llm, parsed in result.get("round_2_parsed", {}).items():
                r2_responses[llm] = {
                    "choice": parsed.get("answer"),
                    "confidence": parsed.get("confidence"),
                }
        
        rec_id = recorder.record(
            prompt=config.prompt,
            mode=config.mode,
            llms_used=config.compare_llms,
            round_1_responses=r1_responses,
            round_2_responses=r2_responses,
            final_recommendation=result.get("final_recommendation"),
            consensus_reached=result.get("consensus_reached", False),
            consensus_count=result.get("consensus_count"),
            flips=result.get("flips"),
            choices=config.choices if config.choices else None,
            google_trends_keyword=config.google_trends_keyword,
            reference_files=config.reference_files if config.reference_files else None,
            yes_no_eval=config.yes_no_eval,
            summary=result.get("summary")
        )
        print(f"\nRecommendation saved: {rec_id}")
        print(f"History file: {config.history_file}")


if __name__ == "__main__":
    main()
