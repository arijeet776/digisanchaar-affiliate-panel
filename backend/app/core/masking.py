"""
Masks values under obviously-secret-looking keys before a dict (e.g.
campaign postback_config) is returned to a client. This is a forward-looking
safeguard: Part 3 doesn't implement the postback engine, but
postback_config is free-form storage a Super Admin can already put API
keys into, and nothing should assume "it's fine because nothing reads it
yet" (spec: never return sensitive internal fields).
"""
SENSITIVE_KEY_MARKERS = ("key", "secret", "token", "password", "credential")


def mask_secret_fields(data: dict) -> dict:
    masked = {}
    for k, v in data.items():
        if isinstance(v, dict):
            masked[k] = mask_secret_fields(v)
        elif any(marker in k.lower() for marker in SENSITIVE_KEY_MARKERS):
            masked[k] = "***" if v else v
        else:
            masked[k] = v
    return masked
