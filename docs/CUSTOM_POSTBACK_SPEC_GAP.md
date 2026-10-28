# Custom postback adapter — specification gap

Status: **not implemented, deliberately.**

The `custom` value exists in `PostbackPlatform`, but nothing in the project
specification / PRD defines the Custom platform's inbound contract. A Custom
adapter would have to guess at it, and a wrong guess mis-maps conversions
(and therefore money). Inbound `custom` postbacks currently fail closed with a
clear validation error instead.

Offer18, Trackier and Trackix adapters are unchanged.

## What the adapter interface needs (what is missing)

An adapter is `normalize(params: dict) -> CanonicalPostback`. For Custom, the
specification must state:

1. The parameter name carrying the click id (DigiSanchaar's own id vs. an upstream id).
2. The parameter name(s) for event / goal and how values map to campaign events.
3. The parameter name for conversion status and the accepted values
   (-> approved / pending / rejected mapping).
4. Payout / revenue / currency parameter names (or that they are ignored).
5. The external transaction id parameter (used for dedupe/idempotency).
6. Allowed HTTP methods and any authentication/secret mechanism.

Everything else is already in place and will be reused unchanged: DigiSanchaar click
id vs. upstream id separation, per-conversion idempotency, postback logging,
publisher macro pass-through, fraud checks and status handling.

When items 1-6 are provided, add `normalize_custom` + a `PLATFORM_METADATA`
entry in `app/services/postback_adapters.py` and register it in `ADAPTERS`.
