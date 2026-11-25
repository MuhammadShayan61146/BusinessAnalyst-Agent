

## Typical non-functional categories and how to make them measurable

- **Performance**: page or query response time at a stated load, for example
  "95% of dashboard views load within 3 seconds with 200 concurrent users".
- **Availability**: percentage of uptime per month and the maintenance window.
- **Scalability**: expected growth in users, data volume and requests, and the
  limit the system must handle without redesign.
- **Security**: authentication method, authorisation model, encryption in
  transit and at rest, audit logging, password policy.
- **Usability**: tasks a new user must complete without training and in how many
  steps; supported browsers and devices.
- **Reliability and recovery**: backup frequency, recovery point and recovery
  time objectives.
- **Maintainability**: automated test coverage expectations, documentation, and
  deployment frequency.
- **Compliance and privacy**: applicable regulations, data retention periods,
  consent handling.

A non-functional requirement without a number, unit or checkable condition
should be treated as an open question for the client.
