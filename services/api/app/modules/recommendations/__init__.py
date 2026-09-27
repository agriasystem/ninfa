"""Recommendation Engine V1 (Gate 16): a deterministic, non-autonomous suggestion layer over the
Decision Layer's own persisted memory (`app.modules.decisions`).

`RecommendationEngine.evaluate(decision, latest_observation)` is the only public entry point:
pure, framework-free, no database session. See docs/architecture/recommendation-engine-v1.md and
ADR 0022.
"""
