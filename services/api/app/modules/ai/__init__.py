"""AI layer: the one place in this codebase that ever touches a language model provider.

`gateway` (Gate 18): the provider-agnostic `LanguageModelProvider` protocol and its fail-closed
production placeholder - no vendor SDK. `ask_ninfa` (Gate 18): the Ask NINFA Core domain (context
builder, static instructions, guardrails, orchestration service). `narrative` remains reserved for
a future gate - nothing in Gate 18 uses it."""
