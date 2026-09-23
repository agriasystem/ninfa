"""Priority Engine V1 (Gate 10): cross-domain signal ranking.

A detector (Gates 5, 7, 8, 9) answers "is this thing wrong?" for ONE domain. The Priority Engine
answers a different question: "of everything that is TRIGGERED right now, what should be looked
at first?" It does not decide whether a detector is right — that decision belongs entirely to the
detector — it only normalizes and orders what is already TRIGGERED. See
docs/architecture/priority-engine-v1.md and ADR 0016.

    TRIGGERED EVALUATIONS -> NORMALIZED PRIORITY COMPONENTS -> PRIORITY SCORE -> RANKING

Nothing here is a Decision, a recommendation, a persisted priority or an AI ranking model. Five
explicit adapters (one per MVP detector) are preferred to a generic rules framework that nothing
yet justifies.

    types           PriorityContext, PriorityCandidate, PriorityRankingResult, weights, policy
    errors          stable error codes for input that cannot be ranked at all
    precision       decision values vs displayed values (the Gate 5 rules, re-exported)
    impact          threshold_progress and the five detector-specific Impact Score V1 policies
    urgency         forward-dated / OTA / cost Urgency Score V1 policies
    actionability   the fixed V1 policy score per decision type
    adapters        one explicit function per detector: evaluation -> validated raw signal
    scoring         the frozen 40/25/20/15 Priority Score V1 formula
    fingerprint     the deterministic SHA-256 of a candidate and of a ranking result
    ranking         deterministic sort, tie-break, rank assignment, duplicate/conflict handling
    service         PriorityService.rank(context, evaluations) -> PriorityRankingResult
"""
