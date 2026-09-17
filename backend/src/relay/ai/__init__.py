"""AI investigation: providers, read-only tools, the investigator loop and verification.

This package reads migration state and returns structured, verified findings. It never writes:
it may import only read models and schemas (import-linter), tool sessions are READ ONLY in
PostgreSQL, and transcripts and findings are persisted by ``relay.investigations``, not here.
"""
