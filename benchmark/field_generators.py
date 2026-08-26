"""
Generates realistic ground-truth field values with Faker. This is the
"answer key" the benchmark grades extraction against — every value produced
here is recorded verbatim in ground_truth.json before the document is ever
rendered to an image, so grading is a plain string comparison, not a guess.

Required fields (per app/extraction/field_schema.py) are always populated —
a document ground-truthed as "missing its BOL number" isn't a realistic
document. Optional fields are randomly omitted ~15% of the time, which is
what real freight paperwork looks like (not every BOL has a piece count
filled in).
"""
import random
from datetime import timedelta

from faker import Faker

from app.extraction.field_schema import get_field_schema

OPTIONAL_OMIT_PROBABILITY = 0.15


def _omit(required: bool) -> bool:
    return (not required) and random.random() < OPTIONAL_OMIT_PROBABILITY


def generate_bill_of_lading_fields(fake: Faker) -> dict[str, str | None]:
    pickup_date = fake.date_between(start_date="-60d", end_date="-1d")
    values = {
        "bol_number": fake.bothify("BOL-######"),
        "shipper_name": fake.company(),
        "shipper_address": fake.address().replace("\n", ", "),
        "consignee_name": fake.company(),
        "consignee_address": fake.address().replace("\n", ", "),
        "carrier_name": fake.company() + " " + fake.random_element(["Freight", "Logistics", "Trucking"]),
        "pro_number": fake.bothify("PRO-#######"),
        "pickup_date": pickup_date.isoformat(),
        "total_weight_lbs": str(fake.random_int(min=150, max=45000)),
        "piece_count": str(fake.random_int(min=1, max=48)),
        "freight_charge_terms": fake.random_element(["Prepaid", "Collect", "Third Party"]),
    }
    return _apply_optional_omissions(values, "bill_of_lading")


def generate_proof_of_delivery_fields(fake: Faker) -> dict[str, str | None]:
    delivery_date = fake.date_between(start_date="-30d", end_date="-1d")
    values = {
        "pro_number": fake.bothify("PRO-#######"),
        "consignee_name": fake.company(),
        "delivery_date": delivery_date.isoformat(),
        "delivery_time": fake.time(pattern="%H:%M"),
        "received_by": fake.name(),
        "signature_present": fake.random_element(["yes", "no"]),
        "condition_notes": fake.random_element(
            ["No exceptions", "Minor box damage noted", "One pallet short", "Wet carton, contents ok"]
        ),
    }
    return _apply_optional_omissions(values, "proof_of_delivery")


def generate_freight_invoice_fields(fake: Faker) -> dict[str, str | None]:
    invoice_date = fake.date_between(start_date="-90d", end_date="-30d")
    payment_due_date = invoice_date + timedelta(days=fake.random_element([15, 30, 45]))
    total = fake.pydecimal(left_digits=4, right_digits=2, positive=True, min_value=100, max_value=9800)
    values = {
        "invoice_number": fake.bothify("INV-######"),
        "invoice_date": invoice_date.isoformat(),
        "carrier_name": fake.company() + " " + fake.random_element(["Freight", "Logistics", "Trucking"]),
        "bol_number": fake.bothify("BOL-######"),
        "pro_number": fake.bothify("PRO-#######"),
        "total_charge": f"{total:.2f}",
        "fuel_surcharge": f"{fake.pydecimal(left_digits=3, right_digits=2, positive=True, min_value=10, max_value=450):.2f}",
        "payment_due_date": payment_due_date.isoformat(),
    }
    return _apply_optional_omissions(values, "freight_invoice")


GENERATORS = {
    "bill_of_lading": generate_bill_of_lading_fields,
    "proof_of_delivery": generate_proof_of_delivery_fields,
    "freight_invoice": generate_freight_invoice_fields,
}


def _apply_optional_omissions(values: dict[str, str], doc_type: str) -> dict[str, str | None]:
    specs_by_name = {s.name: s for s in get_field_schema(doc_type)}
    result = dict(values)
    for name in list(result.keys()):
        spec = specs_by_name.get(name)
        if spec is not None and _omit(spec.required):
            result[name] = None
    return result


def generate_fields(doc_type: str, fake: Faker) -> dict[str, str | None]:
    return GENERATORS[doc_type](fake)
