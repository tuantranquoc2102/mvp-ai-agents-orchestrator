"""Agent-orchestrated codebase analyzer.

Layered layout:
    api/         CLI entry, codebase scoping, output writing
    workflow/    Orchestrator, step runner, workflow templates, tool registry
    agents/      One file per agent role (easy add/remove/edit)
    llm/         Pluggable LLM providers (Claude CLI, mock, ...)
    persistence/ Checkpoint stores
    config/      Defaults / constants shared across layers
"""
