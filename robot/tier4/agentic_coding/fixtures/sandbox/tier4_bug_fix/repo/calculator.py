"""Tiny calculator with a deliberate bug for the tier:4 bug-fix scenario."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a + b  # BUG: should be a - b


def multiply(a, b):
    return a * b
