"""The LLM provider gateway (Gate 18): a provider-agnostic boundary, not a vendor integration.

`protocol.py` defines `LanguageModelProvider`, the ONE seam `AskNinfaService` depends on - never a
concrete SDK. `unconfigured.py` is the only production implementation this gate ships: it always
fails closed (`LanguageModelUnavailableError`), because no vendor has been chosen yet (see ADR
0024, "why no vendor selected in this Gate"). A real provider, when approved, is added here as a
NEW implementation of the same protocol - `AskNinfaService` and the API route never change.
"""
