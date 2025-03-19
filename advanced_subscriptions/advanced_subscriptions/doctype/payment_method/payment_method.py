# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class PaymentMethod(Document):
    def validate(self):
        # Validate API key format based on provider
        if self.provider == "Mollie" and not self.api_key.startswith("test_") and not self.api_key.startswith("live_"):
            frappe.throw("Mollie API key should start with 'test_' or 'live_'")
        
        # Additional validation logic for other providers can be added here