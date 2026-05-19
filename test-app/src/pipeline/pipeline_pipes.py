from __future__ import annotations


class TrimPipe:
    """Strip leading/trailing whitespace from a string value."""
    def transform(self, value):
        if isinstance(value, str):
            return value.strip()
        return value


class UpperPipe:
    """Uppercase a string value."""
    def transform(self, value):
        if isinstance(value, str):
            return value.upper()
        return value


class PositiveIntPipe:
    """Ensure an integer is strictly positive."""
    def transform(self, value):
        v = int(value)
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v


class ClampPipe:
    """Clamp an integer to [min_val, max_val]."""
    def __init__(self, min_val: int, max_val: int) -> None:
        self.min_val = min_val
        self.max_val = max_val

    def transform(self, value):
        return max(self.min_val, min(self.max_val, int(value)))
