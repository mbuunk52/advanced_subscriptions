# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class UsageItem(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        description: DF.Text | None
        item_name: DF.Data
        payment_status: DF.Literal["Pending", "Paid", "Failed"]
        payment_url: DF.Data | None
        price: DF.Currency
        subscription: DF.Link
    # end: auto-generated types

    def after_insert(self):
        # Generate payment URL
        self.generate_payment_url()
        self.save()
    
    def generate_payment_url(self):
        # Get the subscription's payment method
        subscription = frappe.get_doc("Subscription", self.subscription)
        if subscription.betalingsmethode:
            payment_method = frappe.get_doc("Payment Method", subscription.betalingsmethode)
            
            # Here you would integrate with the payment provider (Mollie, Stripe, etc.)
            # For now, we'll just set a dummy URL
            self.payment_url = f"/api/method/advanced_subscriptions.api.payment.process_payment?usage_item={self.name}"
            
            # In a real implementation, you would call the payment provider's API
            # and set the actual payment URL returned by the provider