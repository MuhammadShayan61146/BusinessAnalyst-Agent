

## Designing and integrating APIs

- Use consistent resource-oriented paths and standard status codes (400 for bad
  input, 401 for missing authentication, 403 for forbidden, 404 for unknown
  resources, 429 for rate limiting).
- Version the API so existing clients keep working when it changes.
- Validate request bodies against a schema and return clear, non-sensitive
  error messages.
- Third-party integrations (payments, email, maps, data providers) should be
  isolated behind an interface so a provider can be replaced; define timeouts,
  retries with limits, and behaviour when the provider is down.
- Keep API credentials server-side and rotate them regularly.
- Document each integration: purpose, data exchanged, owner, cost and rate
  limits.
