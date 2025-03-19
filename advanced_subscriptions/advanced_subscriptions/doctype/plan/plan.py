# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Plan(Document):
    def validate(self):
        # Ensure at least one feature is added
        if not self.features:
            frappe.throw("At least one feature must be added to the plan.")