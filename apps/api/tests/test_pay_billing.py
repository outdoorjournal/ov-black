"""Pure-unit coverage for the pay-form billing plumbing (M005/I2).

No DB / gateway needed — these assert the two pure transforms that carry the
traveler's name + address to Braintree:
  - ``_billing_from_request`` — how the pay form's flat fields become a
    :class:`BillingInfo` (name split on the LAST space; empties collapse to None),
  - ``_braintree_billing`` — how that maps onto Braintree's ``billing`` block
    (only non-empty parts; mirrors the voyage-site shape).
"""

from __future__ import annotations

from app.payments.base import BillingInfo
from app.payments.braintree_gateway import _braintree_billing
from app.routers.invoices import PayInvoiceRequest, _billing_from_request

_NONCE = "fake-valid-nonce"


def _req(**over: object) -> PayInvoiceRequest:
    return PayInvoiceRequest(payment_method_nonce=_NONCE, **over)  # type: ignore[arg-type]


def test_name_splits_on_last_space() -> None:
    billing = _billing_from_request(_req(billing_name="Ada Lovelace"))
    assert billing is not None
    assert billing.first_name == "Ada"
    assert billing.last_name == "Lovelace"


def test_multiword_first_name_keeps_last_token_as_surname() -> None:
    billing = _billing_from_request(_req(billing_name="Mary Jane Watson"))
    assert billing is not None
    assert billing.first_name == "Mary Jane"
    assert billing.last_name == "Watson"


def test_single_token_is_first_name_only() -> None:
    billing = _billing_from_request(_req(billing_name="Cher"))
    assert billing is not None
    assert billing.first_name == "Cher"
    assert billing.last_name is None


def test_country_is_upper_cased() -> None:
    billing = _billing_from_request(_req(billing_name="Ada", billing_country="gb"))
    assert billing is not None
    assert billing.country_code_alpha2 == "GB"


def test_all_empty_collapses_to_none() -> None:
    # A bare pay call (no billing form) must not fabricate an empty billing block.
    assert _billing_from_request(_req()) is None


def test_address_only_still_produces_billing() -> None:
    billing = _billing_from_request(_req(billing_address="1 Analytical Way"))
    assert billing is not None
    assert billing.street_address == "1 Analytical Way"
    assert billing.first_name is None


def test_braintree_billing_maps_and_drops_empties() -> None:
    mapped = _braintree_billing(
        BillingInfo(
            first_name="Ada",
            last_name="Lovelace",
            street_address="1 Analytical Way",
            locality="London",
            region="LDN",
            postal_code="EC1A 1AA",
            country_code_alpha2="GB",
        )
    )
    assert mapped == {
        "first_name": "Ada",
        "last_name": "Lovelace",
        "street_address": "1 Analytical Way",
        "locality": "London",
        "region": "LDN",
        "postal_code": "EC1A 1AA",
        "country_code_alpha2": "GB",
    }


def test_braintree_billing_omits_missing_parts() -> None:
    mapped = _braintree_billing(BillingInfo(first_name="Ada", street_address="1 Analytical Way"))
    assert mapped == {"first_name": "Ada", "street_address": "1 Analytical Way"}
