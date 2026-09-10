# Contracts

Versioned OpenAPI, AsyncAPI/event schemas, and shared domain models. Changes here are reviewed as cross-service API changes.

Canonical HTTP contracts:

- `openapi/agent-api.v1.json`
- `openapi/practice-api.v1.json`

Every operation declares `x-implementation-status` so planned API surface is not confused with running functionality.
