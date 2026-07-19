"""Closed product-maintained M0 adapter registry; no dynamic loading."""
import copy
FROZEN_ADAPTER_ID = "case-01-frozen-v1"
PRODUCT_ADAPTER_IDS = frozenset({FROZEN_ADAPTER_ID})

def adapt_frozen_legacy_package(raw: dict) -> dict:
    value = copy.deepcopy(raw)
    for source in value.get("sources", []):
        role = source.get("source_role")
        if role not in {"MAIN", "SI"}: raise ValueError("legacy source_role required")
        source["document_role"] = role
    for conflict in value.get("conflicts", []):
        if conflict.get("legacy_kind") != "SOURCE_INTERNAL": raise ValueError("legacy conflict kind required")
        conflict.update({"comparability": "EXPLICITLY_INCOMPARABLE", "classification": "SOURCE_INTERNAL_CONFLICT", "status": "EXCLUDED"})
    return value

ADAPTER_DISPATCH = {FROZEN_ADAPTER_ID: adapt_frozen_legacy_package}
def resolve_adapter(adapter_id: str):
    try: return ADAPTER_DISPATCH[adapter_id]
    except KeyError as exc: raise ValueError("unknown product adapter") from exc
