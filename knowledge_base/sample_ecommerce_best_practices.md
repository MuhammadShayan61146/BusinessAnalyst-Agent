# DEMONSTRATION CONTENT — NOT AUTHORITATIVE EXTERNAL EVIDENCE

This file is sample knowledge-base content shipped with the repository
so the RAG setup can be demonstrated end-to-end without relying on any
private or unavailable data source. It is general, non-authoritative
guidance written for this demo — it is not a cited external standard,
and the Business Analyst Agent's prompt is explicitly instructed not to
treat retrieved content as proof that a specific client requirement has
been confirmed.

## General guidance for small e-commerce storefronts

- Checkout flows with fewer than four steps tend to have lower
  cart-abandonment rates than longer flows.
- Guest checkout (not requiring account creation) is commonly offered
  alongside registered-account checkout, since mandatory registration
  is a frequently cited source of abandoned carts.
- Order confirmation emails are commonly sent immediately after
  successful payment, separately from any shipping-notification email.
- Product search with basic filtering (category, price range) is
  standard for storefronts with more than a few dozen products.
- Storing full payment card numbers directly is widely discouraged;
  delegating payment handling to a PCI-compliant processor is the
  common pattern instead.
- Mobile-responsive layout is treated as a baseline expectation for new
  storefronts, not an optional enhancement.
- Inventory counts are commonly decremented at order placement, with a
  reconciliation step at fulfillment to catch any discrepancy.
