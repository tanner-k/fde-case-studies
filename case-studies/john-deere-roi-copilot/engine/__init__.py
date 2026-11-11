"""Deterministic decision engine.

Pure functions over frozen models: no network, no file I/O, no LLM. Every number
the user sees is produced here, which is what makes the LLM boundary testable.
"""
