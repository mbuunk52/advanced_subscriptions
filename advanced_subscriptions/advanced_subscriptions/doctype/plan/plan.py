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
        if not self.features:
            frappe.throw(frappe._("At least one feature must be added to the plan."))
        products = [row.product for row in self.usage_rates]
        if len(products) != len(set(products)):
            frappe.throw(frappe._("A product can have only one usage rate per plan."))
        for row in self.usage_rates:
            if (row.included or 0) < 0 or (row.price or 0) < 0:
                frappe.throw(frappe._("Included numbers and prices cannot be negative."))
