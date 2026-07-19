"""History recording for recommendations.

Note: this is llm_compare.py's history recorder, distinct from the
LIVE BOT's history writer (historyutil.py, used by crypto_trading_bot.py).
See AGENTS.md's "check both stacks" rule.
"""

import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional


class HistoryRecorder:
    """Records recommendations to a JSON history file."""
    
    def __init__(self, history_file: Optional[str] = None):
        """Initialize the history recorder.

        Args:
            history_file: Path to the JSON history file. Defaults to
                '<HISTORY_DIR>/llm_compare_history.json', where HISTORY_DIR
                is the HISTORY_DIR env var (falling back to './history/').
        """
        if history_file is None:
            history_file = os.path.join(
                os.environ.get('HISTORY_DIR', './history/'),
                'llm_compare_history.json'
            )
        self.history_file = history_file
        self._ensure_directory()
    
    def _ensure_directory(self):
        """Ensure the history directory exists."""
        directory = os.path.dirname(self.history_file)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
    
    def _load_history(self) -> Dict[str, Any]:
        """Load existing history from file."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {"recommendations": []}
        return {"recommendations": []}
    
    def _save_history(self, history: Dict[str, Any]):
        """Save history to file."""
        with open(self.history_file, 'w') as f:
            json.dump(history, f, indent=2, default=str)
    
    def _generate_id(self) -> str:
        """Generate a unique recommendation ID."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"rec_{timestamp}"
    
    def _hash_prompt(self, prompt: str) -> str:
        """Generate a hash of the prompt for deduplication."""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]
    
    def _get_file_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a reference file."""
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                file_hash = hashlib.sha256(content).hexdigest()
            
            return {
                "path": file_path,
                "filename": os.path.basename(file_path),
                "size_bytes": os.path.getsize(file_path),
                "hash": f"sha256:{file_hash[:16]}"
            }
        except IOError:
            return None
    
    def record(
        self,
        prompt: str,
        mode: str,
        llms_used: List[str],
        round_1_responses: Dict[str, Dict[str, Any]],
        round_2_responses: Optional[Dict[str, Dict[str, Any]]] = None,
        final_recommendation: Optional[str] = None,
        consensus_reached: bool = False,
        consensus_count: Optional[str] = None,
        flips: Optional[List[Dict[str, str]]] = None,
        choices: Optional[List[str]] = None,
        google_trends_keyword: Optional[str] = None,
        reference_files: Optional[List[str]] = None,
        yes_no_eval: bool = False,
        summary: Optional[str] = None
    ) -> str:
        """Record a recommendation to history.
        
        Args:
            prompt: The user's prompt
            mode: Operating mode (single, compare, integrate)
            llms_used: List of LLM names used
            round_1_responses: Dict of Round 1 responses by LLM
            round_2_responses: Optional dict of Round 2 responses
            final_recommendation: The final recommendation
            consensus_reached: Whether consensus was reached
            consensus_count: Consensus count string (e.g., "4/5")
            flips: List of position changes between rounds
            choices: List of available choices
            google_trends_keyword: Google Trends keyword if used
            reference_files: List of reference file paths
            yes_no_eval: Whether this was a yes/no evaluation
            summary: Final summary text
            
        Returns:
            The recommendation ID
        """
        rec_id = self._generate_id()
        
        # Build reference files metadata
        ref_files_meta = []
        if reference_files:
            for path in reference_files:
                meta = self._get_file_metadata(path)
                if meta:
                    ref_files_meta.append(meta)
        
        record = {
            "id": rec_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "prompt": prompt,
            "prompt_hash": self._hash_prompt(prompt),
            "mode": mode,
            "yes_no_eval": yes_no_eval,
            "choices": choices,
            "llms_used": llms_used,
            "google_trends_keyword": google_trends_keyword,
            "reference_files": ref_files_meta if ref_files_meta else None,
            "round_1_responses": round_1_responses,
            "round_2_responses": round_2_responses,
            "final_recommendation": final_recommendation,
            "consensus_reached": consensus_reached,
            "consensus_count": consensus_count,
            "flips": flips if flips else [],
            "summary": summary
        }
        
        # Load, append, and save
        history = self._load_history()
        history["recommendations"].append(record)
        self._save_history(history)
        
        return rec_id
    
    def get_recent(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent recommendations.
        
        Args:
            count: Number of recent recommendations to return
            
        Returns:
            List of recommendation records
        """
        history = self._load_history()
        recommendations = history.get("recommendations", [])
        return recommendations[-count:]
    
    def find_by_prompt_hash(self, prompt: str) -> List[Dict[str, Any]]:
        """Find recommendations with matching prompt hash.
        
        Args:
            prompt: The prompt to search for
            
        Returns:
            List of matching recommendation records
        """
        prompt_hash = self._hash_prompt(prompt)
        history = self._load_history()
        
        return [
            rec for rec in history.get("recommendations", [])
            if rec.get("prompt_hash") == prompt_hash
        ]
