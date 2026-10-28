"""
Wire codec between application documents (datetime / Decimal / ObjectId /
nested dicts) and the JSON the storage API stores.

Rules (kept deliberately small so they are easy to audit):
* Declared datetime columns travel as ISO-8601 UTC text with millisecond
  precision, so plain string comparison orders them correctly.
* Money columns travel as 2-dp decimal text; decoded to Decimal.
* JSON columns and undeclared fields (stored in `_extra`) use tagged values for
  anything JSON cannot represent: {"$date": iso}, {"$oid": hex}, {"$decimal": s}.
* `_id` is a 24-hex string on the wire and a bson.ObjectId in the application.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

try:  # bson ships with pymongo, which stays a dependency for the Mongo mode
    from bson import ObjectId
except Exception:  # pragma: no cover - only when bson is truly absent
    ObjectId = None  # type: ignore[assignment]

from app.storage.schema import BY_COLLECTION, BY_TAB

_HEX24 = re.compile(r"^[0-9a-f]{24}$")


def table_def(name: str) -> dict:
    t = BY_COLLECTION.get(name) or BY_TAB.get(name)
    if t is None:
        raise KeyError(f"Unknown storage table: {name}")
    return t


def col_types(t: dict) -> dict:
    cached = t.get("_types")
    if cached is None:
        cached = {c[0]: c[1] for c in t["columns"]}
        t["_types"] = cached
    return cached


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def from_iso(text: str) -> datetime:
    return datetime.strptime(text.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z") if "." in text else \
        datetime.strptime(text.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")


def money_text(value: Any) -> str:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.01")))


# ----------------------------------------------------------- tagged JSON ----

def tag(value: Any) -> Any:
    """Application value -> JSON-safe value (tagged where needed)."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, datetime):
        return {"$date": to_iso(value)}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if ObjectId is not None and isinstance(value, ObjectId):
        return {"$oid": str(value)}
    if isinstance(value, dict):
        return {str(k): tag(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [tag(v) for v in value]
    return str(value)


def untag(value: Any) -> Any:
    if isinstance(value, list):
        return [untag(v) for v in value]
    if isinstance(value, dict):
        if len(value) == 1:
            if "$date" in value:
                return from_iso(value["$date"])
            if "$decimal" in value:
                return Decimal(value["$decimal"])
            if "$oid" in value and ObjectId is not None:
                return ObjectId(value["$oid"])
        return {k: untag(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------- documents ----

def encode_field(t: dict, name: str, value: Any) -> Any:
    base = name.split(".")[0]
    typ = col_types(t).get(base)
    if "." in name:  # dotted path: the leaf lives inside a JSON column / _extra
        return tag(value)
    if value is None:
        return None
    if typ == "d":
        if isinstance(value, datetime):
            return to_iso(value)
        return str(value)
    if typ == "m":
        return money_text(value)
    if typ in ("s", None) and ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    if typ == "s" and not isinstance(value, str):
        return value if isinstance(value, (int, float, bool)) else tag(value)
    if typ in ("i", "f", "b"):
        if isinstance(value, Decimal):
            return float(value)
        return value
    return tag(value)


def encode_doc(t: dict, doc: dict) -> dict:
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["_id"] = str(v) if v is not None else None
            continue
        out[k] = encode_field(t, k, v)
    return out


def _decode_scalar(typ: str, value: Any) -> Any:
    if value is None:
        return None
    if typ == "d":
        return from_iso(value) if isinstance(value, str) else value
    if typ == "m":
        return Decimal(str(value))
    if typ == "i":
        return int(value)
    if typ == "f":
        return float(value)
    if typ == "j":
        return untag(value)
    return value


def decode_doc(t: dict, doc: dict | None) -> dict | None:
    if doc is None:
        return None
    types = col_types(t)
    out = {}
    for k, v in doc.items():
        if k == "_id":
            out["_id"] = ObjectId(v) if (ObjectId is not None and isinstance(v, str) and _HEX24.match(v)) else v
        elif k in types:
            out[k] = _decode_scalar(types[k], v)
        else:
            out[k] = untag(v)  # undeclared field that lived in _extra
    out.pop("_extra", None)
    return out


# ----------------------------------------------------------------- queries ----

def _encode_filter_value(t: dict, field: str | None, value: Any) -> Any:
    if isinstance(value, re.Pattern):
        return {"$regex": value.pattern, **({"$options": "i"} if value.flags & re.IGNORECASE else {})}
    if isinstance(value, dict):
        out = {}
        for op, arg in value.items():
            if op in ("$in", "$nin") and isinstance(arg, (list, tuple, set)):
                out[op] = [_encode_filter_value(t, field, a) for a in arg]
            elif op == "$not":
                out[op] = _encode_filter_value(t, field, arg)
            else:
                out[op] = _encode_filter_value(t, field, arg)
        return out
    if isinstance(value, (list, tuple)):
        return [_encode_filter_value(t, field, v) for v in value]
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, Decimal):
        return money_text(value) if col_types(t).get((field or "").split(".")[0]) == "m" else float(value)
    if ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    return value


def encode_filter(t: dict, flt: dict | None) -> dict:
    if not flt:
        return {}
    out: dict = {}
    for key, cond in flt.items():
        if key in ("$and", "$or", "$nor"):
            out[key] = [encode_filter(t, c) for c in cond]
        else:
            out[key] = _encode_filter_value(t, key, cond)
    return out


def encode_update(t: dict, update: dict) -> dict:
    out: dict = {}
    for op, body in update.items():
        if op == "$set" or op == "$setOnInsert":
            out[op] = {k: encode_field(t, k, v) for k, v in body.items()}
        elif op == "$push":
            out[op] = {k: tag(v) for k, v in body.items()}
        else:  # $inc / $unset
            out[op] = dict(body)
    return out


def encode_sort(sort) -> dict | None:
    if sort is None:
        return None
    if isinstance(sort, dict):
        return {k: (-1 if v in (-1, "desc") else 1) for k, v in sort.items()}
    return {k: (-1 if d in (-1, "desc") else 1) for k, d in sort}
