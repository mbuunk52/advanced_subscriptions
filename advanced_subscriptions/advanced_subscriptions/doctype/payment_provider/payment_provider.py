# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import requests
import json


class PaymentProvider(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from advanced_subscriptions.advanced_subscriptions.doctype.payment_provider_method.payment_provider_method import PaymentProviderMethod
        from frappe.types import DF

        additional_settings: DF.JSON | None
        api_mode: DF.Literal["test", "live"]
        base_url: DF.Data | None
        is_active: DF.Check
        live_api_key: DF.Password | None
        provider_name: DF.Data
        provider_type: DF.Literal["Mollie", "Stripe", "PayPal", "Adyen", "Square", "Razorpay"]
        supported_payment_methods: DF.Table[PaymentProviderMethod]
        test_api_key: DF.Password | None
        webhook_secret: DF.Password | None
        webhook_url: DF.Data | None
    # end: auto-generated types

    def validate(self):
        """Validate payment provider configuration"""
        self.validate_api_keys()
        self.set_provider_defaults()
        self.validate_webhook_url()
    
    def validate_api_keys(self):
        """Validate API keys based on provider type"""
        if self.provider_type == "Mollie":
            # Validate Mollie API key format
            api_key = self.get_api_key()
            if api_key and not (api_key.startswith("test_") or api_key.startswith("live_")):
                frappe.throw(_("Mollie API key should start with 'test_' or 'live_'"))
        
        elif self.provider_type == "Stripe":
            # Validate Stripe API key format
            api_key = self.get_api_key()
            if api_key and not (api_key.startswith("sk_test_") or api_key.startswith("sk_live_")):
                frappe.throw(_("Stripe API key should start with 'sk_test_' or 'sk_live_'"))
    
    def set_provider_defaults(self):
        """Set default URLs and configurations based on provider type"""
        if self.provider_type == "Mollie":
            self.base_url = "https://api.mollie.com/v2"
            if not self.webhook_url:
                self.webhook_url = f"{frappe.utils.get_url()}/api/method/advanced_subscriptions.api.webhooks.mollie_webhook"
        
        elif self.provider_type == "Stripe":
            self.base_url = "https://api.stripe.com/v1"
            if not self.webhook_url:
                self.webhook_url = f"{frappe.utils.get_url()}/api/method/advanced_subscriptions.api.webhooks.stripe_webhook"
    
    def validate_webhook_url(self):
        """Ensure webhook URL is accessible"""
        if self.webhook_url and not self.webhook_url.startswith(("http://", "https://")):
            frappe.throw(_("Webhook URL must start with http:// or https://"))
    
    def get_api_key(self):
        """Get the appropriate API key based on mode"""
        if self.api_mode == "live":
            return self.get_password("live_api_key")
        else:
            return self.get_password("test_api_key")
    
    def test_connection(self):
        """Test the connection to the payment provider"""
        try:
            if self.provider_type == "Mollie":
                return self.test_mollie_connection()
            elif self.provider_type == "Stripe":
                return self.test_stripe_connection()
            else:
                return {"success": False, "message": f"Test connection not implemented for {self.provider_type}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
    
    def test_mollie_connection(self):
        """Test connection to Mollie API"""
        api_key = self.get_api_key()
        if not api_key:
            return {"success": False, "message": "API key is required"}
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.get(f"{self.base_url}/methods", headers=headers)
            if response.status_code == 200:
                methods = response.json()
                return {
                    "success": True,
                    "message": "Connection successful",
                    "data": methods
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned status {response.status_code}: {response.text}"
                }
        except Exception as e:
            return {"success": False, "message": f"Connection failed: {str(e)}"}
    
    def test_stripe_connection(self):
        """Test connection to Stripe API"""
        api_key = self.get_api_key()
        if not api_key:
            return {"success": False, "message": "API key is required"}
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            response = requests.get(f"{self.base_url}/payment_methods", headers=headers)
            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Connection successful"
                }
            else:
                return {
                    "success": False,
                    "message": f"API returned status {response.status_code}: {response.text}"
                }
        except Exception as e:
            return {"success": False, "message": f"Connection failed: {str(e)}"}
    
    def sync_payment_methods(self):
        """Sync available payment methods from the provider"""
        if self.provider_type == "Mollie":
            return self.sync_mollie_payment_methods()
        elif self.provider_type == "Stripe":
            return self.sync_stripe_payment_methods()
        else:
            return {"success": False, "message": f"Sync not implemented for {self.provider_type}"}
    
    def sync_mollie_payment_methods(self):
        """Sync payment methods from Mollie"""
        connection_test = self.test_mollie_connection()
        if not connection_test["success"]:
            return connection_test
        
        try:
            methods_data = connection_test["data"]
            methods = methods_data.get("_embedded", {}).get("methods", [])
            
            # Clear existing methods
            self.supported_payment_methods = []
            
            # Add new methods
            for method in methods:
                self.append("supported_payment_methods", {
                    "method_id": method["id"],
                    "method_name": method["description"],
                    "is_active": 1,
                    "minimum_amount": method.get("minimumAmount", {}).get("value", "0.01"),
                    "maximum_amount": method.get("maximumAmount", {}).get("value", "1000000.00"),
                    "currencies": ",".join(method.get("currencies", ["EUR"]))
                })
            
            self.save()
            return {"success": True, "message": f"Synced {len(methods)} payment methods"}
        
        except Exception as e:
            return {"success": False, "message": f"Sync failed: {str(e)}"}
    
    def sync_stripe_payment_methods(self):
        """Sync payment methods from Stripe"""
        # Stripe payment methods are more complex and usually configured per account
        # This is a simplified version
        default_methods = [
            {"method_id": "card", "method_name": "Credit/Debit Card", "is_active": 1},
            {"method_id": "ideal", "method_name": "iDEAL", "is_active": 1},
            {"method_id": "sepa_debit", "method_name": "SEPA Direct Debit", "is_active": 1},
            {"method_id": "bancontact", "method_name": "Bancontact", "is_active": 1},
        ]
        
        self.supported_payment_methods = []
        for method in default_methods:
            self.append("supported_payment_methods", method)
        
        self.save()
        return {"success": True, "message": f"Added {len(default_methods)} default payment methods"}


@frappe.whitelist()
def test_provider_connection(provider_name):
    """Test connection to a payment provider"""
    provider = frappe.get_doc("Payment Provider", provider_name)
    return provider.test_connection()


@frappe.whitelist()
def sync_provider_methods(provider_name):
    """Sync payment methods for a provider"""
    provider = frappe.get_doc("Payment Provider", provider_name)
    return provider.sync_payment_methods()
