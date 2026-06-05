"""Static workflow templates — one file per request_type.

Each template module exposes a `TEMPLATE: list[dict]` (the step list) and a
`REQUEST_TYPE: str`. The registry in `src.workflow.registry` discovers them.
"""
