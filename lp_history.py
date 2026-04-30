"""
LP History Utility - Recording and loading LP arbitrage history.

This module provides functions to:
- Create and save snapshot records (price/spread observations)
- Create and save trade records (executed or simulated)
- Load historical data for analysis
- Manage the LP history directory structure
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, List


DEFAULT_HISTORY_DIR = os.environ.get('HISTORY_DIR', './history/lp/')


class LPHistoryManager:
    """Manager for LP arbitrage history files."""
    
    def __init__(self, history_dir: str = DEFAULT_HISTORY_DIR):
        self.history_dir = history_dir
        self.snapshots_file = os.path.join(history_dir, 'lp_snapshots.json')
        self.trades_file = os.path.join(history_dir, 'lp_trades.json')
        self.recommendations_file = os.path.join(history_dir, 'lp_recommendations.json')
        self._ensure_dir()
    
    def _ensure_dir(self):
        """Create history directory if it doesn't exist."""
        os.makedirs(self.history_dir, exist_ok=True)
    
    def _load_json_list(self, filepath: str, key: str) -> List[Dict]:
        """Load a list from a JSON file."""
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return data.get(key, [])
        except (json.JSONDecodeError, IOError) as e:
            print(f"[LP_HISTORY] Warning: Could not load {filepath}: {e}")
            return []
    
    def _save_json_list(self, filepath: str, key: str, items: List[Dict]):
        """Save a list to a JSON file."""
        self._ensure_dir()
        with open(filepath, 'w') as f:
            json.dump({key: items}, f, indent=2)
    
    def _append_to_json(self, filepath: str, key: str, item: Dict):
        """Append an item to a JSON list file."""
        items = self._load_json_list(filepath, key)
        items.append(item)
        self._save_json_list(filepath, key, items)
    
    # ========================================================================
    # SNAPSHOTS - Price/spread observations at each wake-up
    # ========================================================================
    
    def load_snapshots(self) -> List[Dict]:
        """Load all snapshot records."""
        return self._load_json_list(self.snapshots_file, 'snapshots')
    
    def save_snapshot(self, snapshot: Dict):
        """Save a snapshot record."""
        self._append_to_json(self.snapshots_file, 'snapshots', snapshot)
        timestamp = snapshot.get('timestamp', 'unknown')
        spread = snapshot.get('spread_pct', 0)
        action = snapshot.get('recommendation', 'UNKNOWN')
        print(f"  [HISTORY] Snapshot: spread={spread:+.2f}% action={action}")
    
    # ========================================================================
    # TRADES - Executed or simulated trades
    # ========================================================================
    
    def load_trades(self) -> List[Dict]:
        """Load all trade records."""
        return self._load_json_list(self.trades_file, 'trades')
    
    def save_trade(self, trade: Dict):
        """Save a trade record."""
        self._append_to_json(self.trades_file, 'trades', trade)
        action = trade.get('action', 'UNKNOWN')
        amount = trade.get('amount_usd', 0)
        executed = trade.get('executed', False)
        mode = "EXECUTED" if executed else "SIMULATED"
        print(f"  [HISTORY] Trade: {action} ${amount:.2f} ({mode})")
    
    # ========================================================================
    # RECOMMENDATIONS - Legacy format for compatibility
    # ========================================================================
    
    def load_recommendations(self) -> List[Dict]:
        """Load all recommendation records (snapshots with opportunities)."""
        return self._load_json_list(self.recommendations_file, 'recommendations')
    
    def save_recommendation(self, rec: Dict):
        """Save a recommendation record."""
        self._append_to_json(self.recommendations_file, 'recommendations', rec)
    
    # ========================================================================
    # ANALYSIS HELPERS
    # ========================================================================
    
    def get_snapshots_by_period(self, hours: int = 24) -> List[Dict]:
        """Get snapshots from the last N hours."""
        cutoff = datetime.utcnow().timestamp() - (hours * 3600)
        snapshots = self.load_snapshots()
        
        filtered = []
        for s in snapshots:
            try:
                ts = datetime.fromisoformat(s['timestamp'].replace('Z', '+00:00'))
                if ts.timestamp() >= cutoff:
                    filtered.append(s)
            except (KeyError, ValueError):
                continue
        
        return filtered
    
    def get_trades_by_period(self, hours: int = 24) -> List[Dict]:
        """Get trades from the last N hours."""
        cutoff = datetime.utcnow().timestamp() - (hours * 3600)
        trades = self.load_trades()
        
        filtered = []
        for t in trades:
            try:
                ts = datetime.fromisoformat(t['timestamp'].replace('Z', '+00:00'))
                if ts.timestamp() >= cutoff:
                    filtered.append(t)
            except (KeyError, ValueError):
                continue
        
        return filtered
    
    def get_opportunity_count(self, hours: int = 24) -> Dict:
        """Count opportunities in the last N hours."""
        snapshots = self.get_snapshots_by_period(hours)
        
        buys = sum(1 for s in snapshots if s.get('recommendation') == 'BUY')
        sells = sum(1 for s in snapshots if s.get('recommendation') == 'SELL')
        holds = sum(1 for s in snapshots if s.get('recommendation') == 'HOLD')
        
        return {
            'total': len(snapshots),
            'buys': buys,
            'sells': sells,
            'holds': holds,
            'hours': hours
        }
    
    def get_spread_stats(self, hours: int = 24) -> Dict:
        """Calculate spread statistics for the last N hours."""
        snapshots = self.get_snapshots_by_period(hours)
        
        if not snapshots:
            return {
                'count': 0,
                'min_spread': None,
                'max_spread': None,
                'avg_spread': None,
                'hours': hours
            }
        
        spreads = [s.get('spread_pct', 0) for s in snapshots]
        
        return {
            'count': len(spreads),
            'min_spread': min(spreads),
            'max_spread': max(spreads),
            'avg_spread': sum(spreads) / len(spreads),
            'hours': hours
        }


# ============================================================================
# RECORD CREATION FUNCTIONS
# ============================================================================

def create_snapshot_record(
    platform: str,
    lp_token: str,
    virtual_price: float,
    market_price: float,
    spread_pct: float,
    spread_direction: str,
    recommendation: str,
    trading_mode: str,
    wake_up_number: int,
    apy_bps: Optional[int] = None,
    aum_usd: Optional[float] = None,
    aum_cap_pct: Optional[float] = None,
    position_usd: Optional[float] = None
) -> Dict:
    """
    Create a snapshot record with all fields.
    
    Args:
        platform: Platform name (jupiter, drift, hyperliquid)
        lp_token: LP token symbol (JLP, HLP, etc.)
        virtual_price: Calculated fair value price
        market_price: Current market/swap price
        spread_pct: Spread percentage (positive = premium, negative = discount)
        spread_direction: 'premium', 'discount', or 'parity'
        recommendation: BUY, SELL, or HOLD
        trading_mode: 'whatif' or 'live'
        wake_up_number: Sequential wake-up counter
        apy_bps: Optional APY in basis points
        aum_usd: Optional current AUM in USD
        aum_cap_pct: Optional percentage of AUM cap used
        position_usd: Optional current position value in USD
    
    Returns:
        Dictionary containing the snapshot record.
    """
    timestamp = datetime.utcnow()
    
    record = {
        'id': f"lp_snap_{timestamp.strftime('%Y%m%d_%H%M%S')}_{lp_token}",
        'timestamp': timestamp.isoformat() + 'Z',
        'platform': platform,
        'lp_token': lp_token,
        'virtual_price': virtual_price,
        'market_price': market_price,
        'spread_pct': round(spread_pct, 4),
        'spread_direction': spread_direction,
        'recommendation': recommendation,
        'trading_mode': trading_mode,
        'wake_up_number': wake_up_number
    }
    
    # Add optional fields if provided
    if apy_bps is not None:
        record['apy_bps'] = apy_bps
    if aum_usd is not None:
        record['aum_usd'] = aum_usd
    if aum_cap_pct is not None:
        record['aum_cap_pct'] = aum_cap_pct
    if position_usd is not None:
        record['position_usd'] = position_usd
    
    return record


def create_trade_record(
    platform: str,
    lp_token: str,
    action: str,
    amount_usd: float,
    price: float,
    spread_pct: float,
    executed: bool,
    trading_mode: str,
    tx_signature: Optional[str] = None,
    jlp_amount: Optional[float] = None,
    error: Optional[str] = None
) -> Dict:
    """
    Create a trade record.
    
    Args:
        platform: Platform name (jupiter, drift, hyperliquid)
        lp_token: LP token symbol (JLP, HLP, etc.)
        action: BUY or SELL
        amount_usd: Trade amount in USD
        price: Price at trade time
        spread_pct: Spread percentage at trade time
        executed: Whether trade was actually executed
        trading_mode: 'whatif' or 'live'
        tx_signature: Optional transaction signature (for executed trades)
        jlp_amount: Optional JLP token amount
        error: Optional error message if trade failed
    
    Returns:
        Dictionary containing the trade record.
    """
    timestamp = datetime.utcnow()
    
    record = {
        'id': f"lp_trade_{timestamp.strftime('%Y%m%d_%H%M%S')}_{lp_token}_{action}",
        'timestamp': timestamp.isoformat() + 'Z',
        'platform': platform,
        'lp_token': lp_token,
        'action': action,
        'amount_usd': round(amount_usd, 2),
        'price': round(price, 6),
        'spread_pct': round(spread_pct, 4),
        'executed': executed,
        'trading_mode': trading_mode
    }
    
    # Add optional fields if provided
    if tx_signature:
        record['tx_signature'] = tx_signature
    if jlp_amount is not None:
        record['jlp_amount'] = round(jlp_amount, 6)
    if error:
        record['error'] = error
    
    return record


# ============================================================================
# STANDALONE FUNCTIONS (for backwards compatibility)
# ============================================================================

def ensure_history_dir(history_dir: str = DEFAULT_HISTORY_DIR):
    """Create history directory if it doesn't exist."""
    os.makedirs(history_dir, exist_ok=True)


def load_lp_snapshots(history_dir: str = DEFAULT_HISTORY_DIR) -> List[Dict]:
    """Load all LP snapshot records."""
    manager = LPHistoryManager(history_dir)
    return manager.load_snapshots()


def save_lp_snapshot(snapshot: Dict, history_dir: str = DEFAULT_HISTORY_DIR):
    """Save an LP snapshot record."""
    manager = LPHistoryManager(history_dir)
    manager.save_snapshot(snapshot)


def load_lp_trades(history_dir: str = DEFAULT_HISTORY_DIR) -> List[Dict]:
    """Load all LP trade records."""
    manager = LPHistoryManager(history_dir)
    return manager.load_trades()


def save_lp_trade(trade: Dict, history_dir: str = DEFAULT_HISTORY_DIR):
    """Save an LP trade record."""
    manager = LPHistoryManager(history_dir)
    manager.save_trade(trade)
