

## Multi-tenant software-as-a-service considerations

- Decide early whether customers (tenants) share a database with a tenant
  identifier on every row, or have separate schemas or databases; each choice
  affects isolation, cost and migration effort.
- Every query must be scoped to the current tenant on the server.
- Plan subscription tiers, trial periods, usage limits and what happens to data
  when a subscription ends.

## Role-based access control (RBAC)

- Define roles from real duties (for example administrator, analyst, viewer)
  and list which actions each role may perform.
- Give each user the minimum role needed; keep an audit trail of role changes.
- Separate system administration from business administration.
- Support invitation, deactivation and password reset flows.
