"""Thin wrapper around the `diplomacy` engine plus game-store helpers.

The orchestration layer and skills only ever talk to this package; the
`diplomacy` library is treated as a black box behind these modules so the
rest of the codebase never depends on its internals.
"""
