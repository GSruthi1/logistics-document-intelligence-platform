"""
Single source of truth for "what fields does each document type have".

Both the LLM extractor (what to ask the model for) and the rules validator
(what's required, what format) read from this registry. Without this, you'd
end up defining the field list once in a prompt string and again in
validation logic — and the two would silently drift apart over time. This is
also the file a new client integration touches first: adding a new document
type is "add a FieldSpec list here", not "go edit five modules".
"""
from dataclasses import dataclass
from enum import Enum


class FieldType(str, Enum):
    STRING = "string"
    DATE = "date"          # ISO 8601 (YYYY-MM-DD)
    NUMBER = "number"
    CURRENCY = "currency"  # numeric string, e.g. "1245.50"


@dataclass(frozen=True)
class FieldSpec:
    name: str
    description: str
    field_type: FieldType
    required: bool = True


BILL_OF_LADING_FIELDS: list[FieldSpec] = [
    FieldSpec("bol_number", "Bill of Lading number / BOL #", FieldType.STRING),
    FieldSpec("shipper_name", "Name of the shipping party (origin)", FieldType.STRING),
    FieldSpec("shipper_address", "Address of the shipper", FieldType.STRING),
    FieldSpec("consignee_name", "Name of the receiving party (destination)", FieldType.STRING),
    FieldSpec("consignee_address", "Address of the consignee", FieldType.STRING),
    FieldSpec("carrier_name", "Name of the freight carrier", FieldType.STRING),
    FieldSpec("pro_number", "Carrier PRO / tracking number", FieldType.STRING, required=False),
    FieldSpec("pickup_date", "Date freight was picked up", FieldType.DATE),
    FieldSpec("total_weight_lbs", "Total shipment weight in pounds", FieldType.NUMBER),
    FieldSpec("piece_count", "Number of pieces / pallets shipped", FieldType.NUMBER, required=False),
    FieldSpec("freight_charge_terms", "Prepaid, Collect, or Third Party", FieldType.STRING, required=False),
]

PROOF_OF_DELIVERY_FIELDS: list[FieldSpec] = [
    FieldSpec("pro_number", "Carrier PRO / tracking number", FieldType.STRING),
    FieldSpec("consignee_name", "Name of the receiving party", FieldType.STRING),
    FieldSpec("delivery_date", "Date the shipment was delivered", FieldType.DATE),
    FieldSpec("delivery_time", "Time of delivery", FieldType.STRING, required=False),
    FieldSpec("received_by", "Printed name of person who signed for delivery", FieldType.STRING),
    FieldSpec("signature_present", "Whether a signature is present ('yes'/'no')", FieldType.STRING),
    FieldSpec("condition_notes", "Notes on shipment condition / exceptions", FieldType.STRING, required=False),
]

FREIGHT_INVOICE_FIELDS: list[FieldSpec] = [
    FieldSpec("invoice_number", "Invoice number", FieldType.STRING),
    FieldSpec("invoice_date", "Date the invoice was issued", FieldType.DATE),
    FieldSpec("carrier_name", "Name of the freight carrier / biller", FieldType.STRING),
    FieldSpec("bol_number", "Referenced Bill of Lading number", FieldType.STRING, required=False),
    FieldSpec("pro_number", "Carrier PRO / tracking number", FieldType.STRING, required=False),
    FieldSpec("total_charge", "Total amount due", FieldType.CURRENCY),
    FieldSpec("fuel_surcharge", "Fuel surcharge amount", FieldType.CURRENCY, required=False),
    FieldSpec("payment_due_date", "Date payment is due", FieldType.DATE, required=False),
]

FIELD_SCHEMAS: dict[str, list[FieldSpec]] = {
    "bill_of_lading": BILL_OF_LADING_FIELDS,
    "proof_of_delivery": PROOF_OF_DELIVERY_FIELDS,
    "freight_invoice": FREIGHT_INVOICE_FIELDS,
}


def get_field_schema(doc_type: str) -> list[FieldSpec]:
    try:
        return FIELD_SCHEMAS[doc_type]
    except KeyError as e:
        raise ValueError(
            f"Unknown doc_type '{doc_type}'. Known types: {list(FIELD_SCHEMAS)}"
        ) from e
