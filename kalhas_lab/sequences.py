"""Synthetic sequences for the local development harness outside the shipped package.

The harness is not a KALHAS component or integration surface.
"""

LAB_SEQUENCES = {
    "mock-baseline": ("set-low", "set-low", "set-low"),
    "mock-conservative": ("set-low", "set-mid", "set-low"),
    "mock-balanced": ("set-low", "set-mid", "set-high"),
    "mock-adaptive": ("set-mid", "set-high", "set-mid"),
    "mock-diversified": ("set-high", "set-mid", "set-high"),
}
