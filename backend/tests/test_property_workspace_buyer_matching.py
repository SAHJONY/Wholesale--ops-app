from app.models import Buyer
from app.property_workspace import _buyer_zip_codes


def test_buyer_zip_codes_normalizes_values():
    buyer = Buyer(
        name="Test Buyer",
        phone="3055550100",
        zip_codes=[33101, "32501-1234", " 30310 "],
    )

    assert _buyer_zip_codes(buyer) == {"33101", "32501", "30310"}


def test_buyer_zip_codes_handles_non_list_payload():
    buyer = Buyer(name="Test Buyer", phone="3055550100", zip_codes=None)

    assert _buyer_zip_codes(buyer) == set()
