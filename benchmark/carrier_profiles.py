"""
Two "carrier profiles" per document type — different label text and layout
for the same underlying fields. This is the mechanism that makes the
benchmark's LLM-vs-OCR gap real rather than assumed: the OCR baseline finds
fields by matching label keywords (see FIELD_LABEL_ALIASES in
app/extraction/ocr_extractor.py), so a profile that phrases "Shipper" as
"Ship From" or "PRO Number" as "Tracking #" will cause specific,
predictable OCR misses — while the LLM, which reads for meaning rather than
keyword match, isn't fooled by the relabeling.

Every (field, label) pair below was checked by hand against
FIELD_LABEL_ALIASES to know in advance which fields "standard" will find and
which "altcarrier" will plausibly miss — that's what makes the benchmark
result explainable rather than a black box.
"""
from dataclasses import dataclass


@dataclass
class CarrierProfile:
    name: str
    layout: str  # "table" | "stacked"
    accent_color: str
    font_family: str
    labels: dict[str, str]  # field_name -> label text shown on the document


BOL_PROFILES = [
    CarrierProfile(
        name="standard",
        layout="table",
        accent_color="#1a3c6e",
        font_family="Helvetica, Arial, sans-serif",
        labels={
            "bol_number": "BOL Number",
            "shipper_name": "Shipper",
            "shipper_address": "Shipper Address",
            "consignee_name": "Consignee",
            "consignee_address": "Consignee Address",
            "carrier_name": "Carrier",
            "pro_number": "PRO Number",
            "pickup_date": "Pickup Date",
            "total_weight_lbs": "Total Weight (lbs)",
            "piece_count": "Pieces",
            "freight_charge_terms": "Freight Charge Terms",
        },
    ),
    CarrierProfile(
        name="altcarrier",
        layout="stacked",
        accent_color="#7a1f1f",
        font_family="Georgia, 'Times New Roman', serif",
        labels={
            "bol_number": "Bill of Lading #",
            "shipper_name": "Ship From",
            "shipper_address": "Origin Address",
            "consignee_name": "Ship To",
            "consignee_address": "Destination Address",
            "carrier_name": "Carrier",
            "pro_number": "PRO#",
            "pickup_date": "Date Shipped",
            "total_weight_lbs": "Weight",
            "piece_count": "Pieces",
            "freight_charge_terms": "Charge Terms",
        },
    ),
]

POD_PROFILES = [
    CarrierProfile(
        name="standard",
        layout="table",
        accent_color="#1a3c6e",
        font_family="Helvetica, Arial, sans-serif",
        labels={
            "pro_number": "PRO Number",
            "consignee_name": "Consignee",
            "delivery_date": "Delivery Date",
            "delivery_time": "Delivery Time",
            "received_by": "Received By",
            "signature_present": "Signature",
            "condition_notes": "Condition Notes",
        },
    ),
    CarrierProfile(
        name="altcarrier",
        layout="stacked",
        accent_color="#7a1f1f",
        font_family="Georgia, 'Times New Roman', serif",
        labels={
            "pro_number": "Tracking #",
            "consignee_name": "Delivered To",
            "delivery_date": "Date Delivered",
            "delivery_time": "Time",
            "received_by": "Signed By",
            "signature_present": "Signature on File",
            "condition_notes": "Exceptions",
        },
    ),
]

FREIGHT_INVOICE_PROFILES = [
    CarrierProfile(
        name="standard",
        layout="table",
        accent_color="#1a3c6e",
        font_family="Helvetica, Arial, sans-serif",
        labels={
            "invoice_number": "Invoice Number",
            "invoice_date": "Invoice Date",
            "carrier_name": "Carrier",
            "bol_number": "BOL Number",
            "pro_number": "PRO Number",
            "total_charge": "Total Charge",
            "fuel_surcharge": "Fuel Surcharge",
            "payment_due_date": "Payment Due Date",
        },
    ),
    CarrierProfile(
        name="altcarrier",
        layout="stacked",
        accent_color="#7a1f1f",
        font_family="Georgia, 'Times New Roman', serif",
        labels={
            "invoice_number": "Invoice #",
            "invoice_date": "Billed On",
            "carrier_name": "Freight Carrier",
            "bol_number": "Ref BOL#",
            "pro_number": "Ref PRO#",
            "total_charge": "Amount Due",
            "fuel_surcharge": "Fuel Surcharge",
            "payment_due_date": "Due Date",
        },
    ),
]

PROFILES_BY_DOC_TYPE: dict[str, list[CarrierProfile]] = {
    "bill_of_lading": BOL_PROFILES,
    "proof_of_delivery": POD_PROFILES,
    "freight_invoice": FREIGHT_INVOICE_PROFILES,
}

DOC_TITLES = {
    "bill_of_lading": "BILL OF LADING",
    "proof_of_delivery": "PROOF OF DELIVERY",
    "freight_invoice": "FREIGHT INVOICE",
}
