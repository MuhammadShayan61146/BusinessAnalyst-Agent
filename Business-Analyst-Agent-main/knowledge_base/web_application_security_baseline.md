

## Common baseline controls for web applications

- Store passwords only as salted, slow hashes; never in plain text.
- Use HTTPS everywhere; set secure, HTTP-only cookies when cookies are used.
- Validate and encode all input and output to prevent injection and cross-site
  scripting; use parameterised database queries.
- Apply role-based access control on the server for every operation; hiding a
  button in the interface is not access control.
- Never accept file paths from clients; map opaque identifiers to files on the
  server to avoid path traversal.
- Limit upload types and sizes; scan or validate uploaded files before use.
- Keep secrets (API keys, database passwords) in environment configuration, not
  in source code or client-side code.
- Log security-relevant events (logins, failures, permission changes) without
  logging secrets or personal data.
- Rate-limit authentication endpoints to slow credential guessing.
- Plan for data-breach response: who is notified, and how access is revoked.
