"""Prompt-driven generation: brief in, validated editable Building out.

The model writes intent (program, optionally rects). Coordinates, topology, and
every persisted byte come from deterministic code in this package.
"""

from plancheck.generation.agent import GenerationError, generate_from_brief

__all__ = ["GenerationError", "generate_from_brief"]
