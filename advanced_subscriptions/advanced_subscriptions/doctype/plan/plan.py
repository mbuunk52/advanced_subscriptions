# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Plan(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from advanced_subscriptions.advanced_subscriptions.doctype.pay_as_you_go_item.pay_as_you_go_item import PayAsYouGoItem
        from advanced_subscriptions.advanced_subscriptions.doctype.plan_feature.plan_feature import PlanFeature
        from frappe.types import DF

        beschrijving: DF.Text | None
        features: DF.Table[PlanFeature]
        is_active: DF.Check
        naam: DF.Data
        payg_items: DF.Table[PayAsYouGoItem]
        periode: DF.Literal["Month", "Year"]
        prijs: DF.Currency
    # end: auto-generated types

    def validate(self):
        # Ensure at least one feature is added
        if not self.features:
            frappe.throw("At least one feature must be added to the plan.")