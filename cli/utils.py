"""
Shared CLI utilities.
"""
from typing import Optional


def prompt(prompt_text: str) -> str:
    """Prompt user for input with EOF handling."""
    try:
        return input(prompt_text)
    except EOFError:
        return ""


def input_float(prompt_text: str) -> Optional[float]:
    """Prompt for float input with validation."""
    val = prompt(prompt_text).strip()
    try:
        if val == "":
            return None
        return float(val)
    except ValueError:
        print("Invalid number.")
        return None

