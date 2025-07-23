# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

class PaymentMethod(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        additional_settings: DF.JSON | None
        currency: DF.Link | None
        description: DF.Text | None
        is_active: DF.Check
        is_default: DF.Check
        method_name: DF.Data
        payment_provider: DF.Link
        provider_method_id: DF.Data
    # end: auto-generated types

    def validate(self):
        # Validate payment provider exists and is active
        if self.payment_provider:
            provider = frappe.get_doc("Payment Provider", self.payment_provider)
            if not provider.is_active:
                frappe.throw(_("Payment Provider '{0}' is not active").format(self.payment_provider))
            
            # Validate that the provider method exists in the provider's supported methods
            if self.provider_method_id:
                supported_methods = [method.method_id for method in provider.supported_payment_methods if method.is_active]
                if self.provider_method_id not in supported_methods:
                    frappe.throw(_("Method '{0}' is not supported by provider '{1}'").format(self.provider_method_id, self.payment_provider))
        
        # Ensure only one default payment method per currency
        if self.is_default:
            existing_default = frappe.get_all("Payment Method", 
                filters={
                    "currency": self.currency,
                    "is_default": 1,
                    "name": ["!=", self.name]
                })
            if existing_default:
                frappe.throw(f"A default payment method already exists for currency {self.currency}")
    
    def get_provider_settings(self):
        """Get payment provider settings"""
        if self.payment_provider:
            return frappe.get_doc("Payment Provider", self.payment_provider)
        return None
    
    def is_method_available(self, amount=None, currency=None):
        """Check if payment method is available for given amount and currency"""
        if not self.is_active:
            return False
        
        provider = self.get_provider_settings()
        if not provider or not provider.is_active:
            return False
        
        # Check provider method constraints
        for method in provider.supported_payment_methods:
            if method.method_id == self.provider_method_id and method.is_active:
                if amount:
                    min_amount = float(method.minimum_amount or 0)
                    max_amount = float(method.maximum_amount or float('inf'))
                    if not (min_amount <= float(amount) <= max_amount):
                        return False
                
                if currency and method.currencies:
                    supported_currencies = [c.strip() for c in method.currencies.split(",")]
                    if currency not in supported_currencies:
                        return False
                
                return True
        
        return False