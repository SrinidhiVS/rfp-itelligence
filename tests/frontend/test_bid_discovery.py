from src.frontend.config import FrontendConfig


def test_bid_ids_are_configurable(monkeypatch):
    monkeypatch.setenv("RFP_BID_IDS", "Bid1,UnseenNumericBid")
    config = FrontendConfig.from_env()
    assert config.bid_ids == ("Bid1", "UnseenNumericBid")
