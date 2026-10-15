"""
Service layer for the review aggregate.

Every function takes keyword-only arguments, receives an already authorised ``review`` (or the acting user
for review-level operations), scopes every child lookup to that review and raises the typed exceptions from
``parsifal.apps.core.exceptions`` instead of returning HTTP responses. Views, the JSON API, the CLI and the
MCP server all go through these functions so behaviour cannot drift between surfaces.
"""
