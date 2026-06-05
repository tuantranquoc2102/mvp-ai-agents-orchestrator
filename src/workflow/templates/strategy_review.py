"""Strategic planning workflow."""
from ._helpers import step

REQUEST_TYPE = "strategy_review"

TEMPLATE = [
    step("market_scan", "cso",
         instruction="Scan the competitive landscape."),
    step("product_pov", "cpo",
         instruction="Add product point of view.",
         inputs_from=["market_scan"]),
    step("ceo_decision", "ceo",
         instruction="Make the go/no-go call.",
         inputs_from=["market_scan", "product_pov"]),
]
