"""
Pre-Flight Validation Module for Live Trading

This module provides validation that must pass before live trading can begin.
It runs profitability analysis and determines if a trading pair is viable.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from correlation_tracker import (
    AnalyzerConfig,
    ProfitabilityAnalyzer,
    DirectionalProfitabilityResult,
    ProfitabilityReport,
    parse_duration,
)

logger = logging.getLogger(__name__)

# Interval string to seconds mapping
INTERVAL_MAP = {
    "1 min": 60,
    "5 min": 300,
    "15 min": 900,
    "1 hour": 3600,
    "4 hour": 14400,
}

# Reverse mapping for convenience
SECONDS_TO_INTERVAL = {v: k for k, v in INTERVAL_MAP.items()}


@dataclass
class PreflightResult:
    """Result from pre-flight validation."""
    passed: bool
    verdict: str
    recommended_interval_seconds: Optional[int]
    sample_interval_seconds: Optional[int]  # For price monitoring (equals lag time)
    up_viable: bool
    down_viable: bool
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None  # Full profitability analysis results
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class PreflightValidator:
    """
    Validates trading viability before live trading begins.
    
    Runs profitability analysis and determines if a trading pair is viable
    for live trading. When directional_filter is enabled, also validates
    directional viability.
    """
    
    def __init__(self, 
                 leader: str, 
                 follower: str,
                 directional_filter: bool = False,
                 recent: str = "48hr",
                 position_size_usd: float = 1000.0,
                 target_profit_pct: float = 0.5,
                 data_dir: str = './correlation_data'):
        """
        Initialize preflight validator.
        
        Args:
            leader: Leader coin symbol (e.g., 'BTC')
            follower: Follower coin symbol (e.g., 'SOL')
            directional_filter: Enable UP/DOWN directional analysis
            recent: Time window for analysis (e.g., '48hr', '7days')
            position_size_usd: Position size for cost calculations
            target_profit_pct: Target profit percentage per trade
            data_dir: Directory containing correlation data
        """
        self.leader = leader.upper()
        self.follower = follower.upper()
        self.directional_filter = directional_filter
        self.recent = recent
        self.position_size_usd = position_size_usd
        self.target_profit_pct = target_profit_pct
        self.data_dir = data_dir
        
        self._result: Optional[PreflightResult] = None
        self._directional_result: Optional[DirectionalProfitabilityResult] = None
        self._standard_result: Optional[ProfitabilityReport] = None
    
    def _validate_jupiter_quote(self, follower_mint: str) -> Optional[PreflightResult]:
        """
        Validate that the follower token is actually tradeable on Jupiter
        by attempting to get a quote for a small swap.
        
        Args:
            follower_mint: The Solana mint address of the follower token.
            
        Returns:
            PreflightResult if validation fails, None if validation passes.
        """
        try:
            from dex.jupiterutil import JupiterClient, USDC_MINT
            
            jupiter = JupiterClient()
            
            # Try to get a quote for a tiny USDC -> follower swap
            # Using 1 USDC (1_000_000 in smallest units for 6 decimals)
            test_amount = 1_000_000  # 1 USDC
            
            print(f"[PREFLIGHT] Validating {self.follower} is tradeable on Jupiter...")
            quote = jupiter.get_quote(USDC_MINT, follower_mint, test_amount)
            
            if not quote:
                return PreflightResult(
                    passed=False,
                    verdict="TOKEN_NOT_TRADEABLE",
                    recommended_interval_seconds=None,
                    sample_interval_seconds=None,
                    up_viable=False,
                    down_viable=False,
                    error_message=f"Follower token '{self.follower}' (mint: {follower_mint}) "
                                  f"failed Jupiter quote validation. This token may not be "
                                  f"tradeable, have insufficient liquidity, or the mint address may be incorrect."
                )
            
            # Check for reasonable output (not zero)
            out_amount = int(quote.get("outAmount", 0))
            if out_amount == 0:
                return PreflightResult(
                    passed=False,
                    verdict="TOKEN_NO_LIQUIDITY",
                    recommended_interval_seconds=None,
                    sample_interval_seconds=None,
                    up_viable=False,
                    down_viable=False,
                    error_message=f"Follower token '{self.follower}' returned zero output amount. "
                                  f"This token may have no liquidity on Jupiter."
                )
            
            print(f"[PREFLIGHT] ✓ {self.follower} is tradeable on Jupiter")
            return None  # Validation passed
            
        except ImportError as e:
            logger.warning(f"Could not import Jupiter client for quote validation: {e}")
            return None  # Skip validation if imports fail
        except Exception as e:
            # Log but don't fail on unexpected errors - let trading attempt handle it
            logger.warning(f"Jupiter quote validation encountered error: {e}")
            return None
    
    def validate(self) -> PreflightResult:
        """
        Run profitability analysis and return validation result.
        
        Returns:
            PreflightResult with validation status and details
        """
        # Validate follower token has Jupiter mint address (required for trading)
        try:
            from dex.token_cache import get_mint_with_fallback
            follower_mint = get_mint_with_fallback(self.follower)
            if not follower_mint:
                return PreflightResult(
                    passed=False,
                    verdict="TOKEN_NOT_TRADEABLE",
                    recommended_interval_seconds=None,
                    sample_interval_seconds=None,
                    up_viable=False,
                    down_viable=False,
                    error_message=f"Follower token '{self.follower}' has no Jupiter mint address. "
                                  f"This token cannot be traded on Solana/Jupiter."
                )
            
            # Validate mint address is actually tradeable on Jupiter by attempting a quote
            validation_result = self._validate_jupiter_quote(follower_mint)
            if validation_result:
                return validation_result
                
        except ImportError:
            logger.warning("Could not import token_cache for mint validation")
        
        try:
            # Parse recent duration to seconds (default to hours for preflight)
            recent_seconds = parse_duration(self.recent, default_unit='hr')
        except ValueError as e:
            return PreflightResult(
                passed=False,
                verdict="CONFIGURATION_ERROR",
                recommended_interval_seconds=None,
                sample_interval_seconds=None,
                up_viable=False,
                down_viable=False,
                error_message=f"Invalid 'recent' parameter: {e}"
            )
        
        # Configure analyzer
        config = AnalyzerConfig(
            data_dir=self.data_dir,
            leader=self.leader,
            follower=self.follower,
            profitability=True,
            position_size_usd=self.position_size_usd,
            target_profit_pct=self.target_profit_pct,
            directional_filter=self.directional_filter,
            recent_seconds=recent_seconds,
            min_samples=100,  # Lower threshold for preflight
        )
        
        analyzer = ProfitabilityAnalyzer(config)
        
        if self.directional_filter:
            return self._validate_directional(analyzer)
        else:
            return self._validate_standard(analyzer)
    
    def _validate_directional(self, analyzer: ProfitabilityAnalyzer) -> PreflightResult:
        """Run directional (UP/DOWN) validation."""
        result = analyzer.analyze_directional(self.leader, self.follower)
        
        if result is None:
            return PreflightResult(
                passed=False,
                verdict="ANALYSIS_FAILED",
                recommended_interval_seconds=None,
                sample_interval_seconds=None,
                up_viable=False,
                down_viable=False,
                error_message=self._format_analysis_failure_message()
            )
        
        self._directional_result = result
        
        # Determine pass/fail based on viability
        # Partial viability is allowed (PARTIALLY_VIABLE_UP or PARTIALLY_VIABLE_DOWN)
        passed = result.combined_verdict in [
            "FULLY_VIABLE", 
            "PARTIALLY_VIABLE_UP", 
            "PARTIALLY_VIABLE_DOWN"
        ]
        
        # Sample interval = lag time (Option B: compare to previous sample at lag interval)
        sample_interval = result.recommended_interval_seconds
        
        error_msg = None
        if not passed:
            error_msg = self._format_not_viable_message(result)
        
        self._result = PreflightResult(
            passed=passed,
            verdict=result.combined_verdict,
            recommended_interval_seconds=result.recommended_interval_seconds,
            sample_interval_seconds=sample_interval,
            up_viable=result.up_viable,
            down_viable=result.down_viable,
            error_message=error_msg,
            details=asdict(result)
        )
        
        return self._result
    
    def _validate_standard(self, analyzer: ProfitabilityAnalyzer) -> PreflightResult:
        """Run standard (non-directional) validation."""
        result = analyzer.analyze(self.leader, self.follower)
        
        if result is None:
            return PreflightResult(
                passed=False,
                verdict="ANALYSIS_FAILED",
                recommended_interval_seconds=None,
                sample_interval_seconds=None,
                up_viable=False,
                down_viable=False,
                error_message=self._format_analysis_failure_message()
            )
        
        self._standard_result = result
        
        # Determine pass/fail
        passed = result.verdict in ["VIABLE", "POSSIBLY VIABLE"]
        
        # Sample interval = lag time (Option B: compare to previous sample at lag interval)
        sample_interval = result.recommended_interval_seconds
        
        error_msg = None
        if not passed:
            error_msg = self._format_not_viable_message_standard(result)
        
        self._result = PreflightResult(
            passed=passed,
            verdict=result.verdict,
            recommended_interval_seconds=result.recommended_interval_seconds,
            sample_interval_seconds=sample_interval,
            up_viable=passed,  # In non-directional mode, viable means both directions
            down_viable=passed,
            error_message=error_msg,
            details=asdict(result)
        )
        
        return self._result
    
    def _format_analysis_failure_message(self) -> str:
        """Format error message for analysis failure."""
        return (
            f"Pre-flight analysis failed for {self.leader} → {self.follower}.\n"
            f"Possible causes:\n"
            f"  • Insufficient data in {self.data_dir}\n"
            f"  • Missing price data for one or both symbols\n"
            f"  • Data older than {self.recent}\n"
            f"\nSuggestions:\n"
            f"  • Run correlation tracker to collect more data\n"
            f"  • Check that both {self.leader} and {self.follower} are being tracked\n"
            f"  • Try --recent with a larger time window"
        )
    
    def _format_not_viable_message(self, result: DirectionalProfitabilityResult) -> str:
        """Format error message for not viable directional result."""
        lines = [
            f"Pre-flight FAILED: {self.leader} → {self.follower} is NOT VIABLE",
            "",
            f"Directional Analysis:",
            f"  UP direction: {'✓ Viable' if result.up_viable else '✗ Not viable'} "
            f"({result.up_sample_count} samples)",
            f"  DOWN direction: {'✓ Viable' if result.down_viable else '✗ Not viable'} "
            f"({result.down_sample_count} samples)",
            "",
            f"Verdict: {result.combined_verdict}",
            f"Details: {result.combined_verdict_details}",
            "",
            "Suggestions:",
            "  • Try paper trading mode to test strategy without real funds",
            "  • Consider a different trading pair with stronger correlation",
            "  • Wait for market conditions to change (higher volatility)",
            "  • Increase position size to improve break-even threshold",
        ]
        return "\n".join(lines)
    
    def _format_not_viable_message_standard(self, result: ProfitabilityReport) -> str:
        """Format error message for not viable standard result."""
        lines = [
            f"Pre-flight FAILED: {self.leader} → {self.follower} is NOT VIABLE",
            "",
            f"Verdict: {result.verdict}",
            f"Details: {result.verdict_details}",
            "",
            f"Break-even move required: {result.cost_analysis.break_even_move_pct:.2f}%",
            f"Viable intervals found: {result.viable_intervals if result.viable_intervals else 'None'}",
            "",
            "Suggestions:",
            "  • Try paper trading mode to test strategy without real funds",
            "  • Consider a different trading pair with stronger correlation",
            "  • Wait for market conditions to change (higher volatility)",
            "  • Increase position size to improve break-even threshold",
        ]
        return "\n".join(lines)
    
    def get_recommended_interval_seconds(self) -> Optional[int]:
        """Get the recommended trading interval in seconds."""
        if self._result:
            return self._result.recommended_interval_seconds
        return None
    
    def get_sample_interval_seconds(self) -> Optional[int]:
        """Get the recommended sample interval for price monitoring."""
        if self._result:
            return self._result.sample_interval_seconds
        return None
    
    def get_viable_directions(self) -> tuple:
        """
        Get which directions are viable for trading.
        
        Returns:
            Tuple of (up_viable, down_viable)
        """
        if self._result:
            return (self._result.up_viable, self._result.down_viable)
        return (False, False)
    
    def print_result(self):
        """Print the preflight result to console."""
        if not self._result:
            print("No preflight validation has been run yet.")
            return
        
        print("\n" + "=" * 70)
        print("                    PRE-FLIGHT VALIDATION")
        print("=" * 70)
        print(f"Pair: {self.leader} → {self.follower}")
        print(f"Data window: {self.recent}")
        print(f"Directional filter: {'Enabled' if self.directional_filter else 'Disabled'}")
        print("-" * 70)
        
        status = "✓ PASSED" if self._result.passed else "✗ FAILED"
        print(f"\nResult: {status}")
        print(f"Verdict: {self._result.verdict}")
        
        if self._result.recommended_interval_seconds:
            label = SECONDS_TO_INTERVAL.get(
                self._result.recommended_interval_seconds,
                f"{self._result.recommended_interval_seconds}s"
            )
            print(f"Recommended interval: {label}")
            print(f"Sample interval: {self._result.sample_interval_seconds}s")
        
        if self.directional_filter:
            print(f"\nDirectional viability:")
            print(f"  UP: {'✓' if self._result.up_viable else '✗'}")
            print(f"  DOWN: {'✓' if self._result.down_viable else '✗'}")
        
        if self._result.error_message:
            print("\n" + "-" * 70)
            print(self._result.error_message)
        
        print("=" * 70 + "\n")


def run_preflight(leader: str, follower: str, 
                  directional_filter: bool = False,
                  recent: str = "48hr",
                  position_size_usd: float = 1000.0,
                  verbose: bool = True) -> PreflightResult:
    """
    Convenience function to run preflight validation.
    
    Args:
        leader: Leader coin symbol
        follower: Follower coin symbol
        directional_filter: Enable UP/DOWN directional analysis
        recent: Time window for analysis
        position_size_usd: Position size for cost calculations
        verbose: Print results to console
        
    Returns:
        PreflightResult
    """
    validator = PreflightValidator(
        leader=leader,
        follower=follower,
        directional_filter=directional_filter,
        recent=recent,
        position_size_usd=position_size_usd
    )
    
    result = validator.validate()
    
    if verbose:
        validator.print_result()
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pre-flight validation for live trading")
    parser.add_argument('--leader', required=True, help='Leader coin symbol')
    parser.add_argument('--follower', required=True, help='Follower coin symbol')
    parser.add_argument('--directional-filter', action='store_true',
                        help='Enable UP/DOWN directional analysis')
    parser.add_argument('--recent', default='48hr', help='Data window (default: 48hr)')
    parser.add_argument('--position-size', type=float, default=1000.0,
                        help='Position size in USD (default: 1000)')
    parser.add_argument('--data-dir', default='./correlation_data',
                        help='Directory containing correlation data (default: ./correlation_data)')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')
    
    # Create validator directly with data_dir
    validator = PreflightValidator(
        leader=args.leader,
        follower=args.follower,
        directional_filter=args.directional_filter,
        recent=args.recent,
        position_size_usd=args.position_size,
        data_dir=args.data_dir
    )
    
    result = validator.validate()
    validator.print_result()
    
    # Exit with appropriate code
    exit(0 if result.passed else 1)
