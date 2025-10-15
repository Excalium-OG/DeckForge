"""
Utility functions for drop rate management and weighted card selection
"""
import random
from typing import Dict, List, Optional
from utils.card_helpers import RARITY_HIERARCHY

# Default drop rates (must sum to 100%)
DEFAULT_DROP_RATES = {
    "Common": 40.0,
    "Uncommon": 25.0,
    "Exceptional": 15.0,
    "Rare": 10.0,
    "Epic": 6.0,
    "Legendary": 3.0,
    "Mythic": 1.0
}

def validate_drop_rates(rates: Dict[str, float]) -> tuple[bool, Optional[str]]:
    """
    Validate that drop rates are valid.
    
    Args:
        rates: Dictionary of rarity -> percentage
        
    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
    """
    # Check all rarities are present
    for rarity in RARITY_HIERARCHY:
        if rarity not in rates:
            return False, f"Missing rarity: {rarity}"
    
    # Check all percentages are valid
    for rarity, percentage in rates.items():
        if percentage < 0 or percentage > 100:
            return False, f"Invalid percentage for {rarity}: {percentage}% (must be 0-100)"
    
    # Check sum equals 100%
    total = sum(rates.values())
    if abs(total - 100.0) > 0.01:  # Allow small floating point errors
        return False, f"Total percentage is {total}%, must equal 100%"
    
    return True, None

def normalize_drop_rates(rates: Dict[str, float]) -> Dict[str, float]:
    """
    Normalize drop rates to exactly 100% (handles floating point errors).
    
    Args:
        rates: Dictionary of rarity -> percentage
        
    Returns:
        Normalized rates dictionary
    """
    total = sum(rates.values())
    if total == 0:
        return DEFAULT_DROP_RATES.copy()
    
    return {rarity: (percentage / total) * 100.0 for rarity, percentage in rates.items()}

def select_rarity_by_weight(rates: Dict[str, float]) -> str:
    """
    Select a random rarity based on weighted probabilities.
    
    Args:
        rates: Dictionary of rarity -> percentage (should sum to 100)
        
    Returns:
        Selected rarity string
    """
    # Normalize rates just in case
    normalized = normalize_drop_rates(rates)
    
    # Convert percentages to weights
    rarities = list(normalized.keys())
    weights = [normalized[r] for r in rarities]
    
    # Use random.choices for weighted selection
    selected = random.choices(rarities, weights=weights, k=1)[0]
    return selected

def get_default_drop_rates() -> Dict[str, float]:
    """
    Get a copy of the default drop rates.
    
    Returns:
        Dictionary of default drop rates
    """
    return DEFAULT_DROP_RATES.copy()

def format_drop_rates_table(rates: Dict[str, float]) -> str:
    """
    Format drop rates as a readable table string.
    
    Args:
        rates: Dictionary of rarity -> percentage
        
    Returns:
        Formatted table string
    """
    lines = []
    lines.append("```")
    lines.append("Rarity        Drop Rate")
    lines.append("─" * 30)
    
    # Sort by rarity hierarchy
    for rarity in RARITY_HIERARCHY:
        percentage = rates.get(rarity, 0.0)
        lines.append(f"{rarity:<13} {percentage:>6.2f}%")
    
    lines.append("─" * 30)
    lines.append(f"{'Total':<13} {sum(rates.values()):>6.2f}%")
    lines.append("```")
    
    return "\n".join(lines)
