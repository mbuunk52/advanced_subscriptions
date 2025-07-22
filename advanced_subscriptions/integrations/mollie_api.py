# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
import requests
import json
from frappe import _
from frappe.utils import now, flt, cint


class MollieAPI:
    """Mollie API integration for subscription management"""
    
    def __init__(self, payment_provider=None):
        if payment_provider:
            if isinstance(payment_provider, str):
                self.provider = frappe.get_doc("Payment Provider", payment_provider)
            else:
                self.provider = payment_provider
        else:
            # Get default Mollie provider
            self.provider = frappe.get_doc("Payment Provider", {"provider_type": "Mollie", "is_active": 1})
        
        if not self.provider:
            frappe.throw(_("No active Mollie provider found"))
        
        self.api_key = self.provider.get_api_key()
        self.base_url = self.provider.base_url
        
        if not self.api_key:
            frappe.throw(_("Mollie API key not configured"))
    
    def _make_request(self, method, endpoint, data=None):
        """Make API request to Mollie"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=data)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data)
            elif method.upper() == "PATCH":
                response = requests.patch(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers)
            else:
                frappe.throw(f"Unsupported HTTP method: {method}")
            
            if response.status_code >= 400:
                error_data = response.json() if response.content else {}
                error_message = error_data.get("detail", f"HTTP {response.status_code}: {response.text}")
                frappe.throw(f"Mollie API Error: {error_message}")
            
            return response.json() if response.content else {}
        
        except requests.exceptions.RequestException as e:
            frappe.throw(f"Request failed: {str(e)}")
    
    # Customer Management
    def create_customer(self, name, email, metadata=None):
        """Create a customer in Mollie"""
        data = {
            "name": name,
            "email": email
        }
        if metadata:
            data["metadata"] = metadata
        
        return self._make_request("POST", "customers", data)
    
    def get_customer(self, customer_id):
        """Get customer details"""
        return self._make_request("GET", f"customers/{customer_id}")
    
    def update_customer(self, customer_id, name=None, email=None, metadata=None):
        """Update customer details"""
        data = {}
        if name:
            data["name"] = name
        if email:
            data["email"] = email
        if metadata:
            data["metadata"] = metadata
        
        return self._make_request("PATCH", f"customers/{customer_id}", data)
    
    def delete_customer(self, customer_id):
        """Delete a customer"""
        return self._make_request("DELETE", f"customers/{customer_id}")
    
    # Mandate Management
    def create_mandate(self, customer_id, method, consumer_name, consumer_account, consumer_bic=None, signature_date=None, mandate_reference=None):
        """Create a mandate for recurring payments"""
        data = {
            "method": method,
            "consumerName": consumer_name,
            "consumerAccount": consumer_account
        }
        
        if consumer_bic:
            data["consumerBic"] = consumer_bic
        if signature_date:
            data["signatureDate"] = signature_date
        if mandate_reference:
            data["mandateReference"] = mandate_reference
        
        return self._make_request("POST", f"customers/{customer_id}/mandates", data)
    
    def get_mandates(self, customer_id):
        """Get customer mandates"""
        return self._make_request("GET", f"customers/{customer_id}/mandates")
    
    def get_mandate(self, customer_id, mandate_id):
        """Get specific mandate"""
        return self._make_request("GET", f"customers/{customer_id}/mandates/{mandate_id}")
    
    def delete_mandate(self, customer_id, mandate_id):
        """Delete a mandate"""
        return self._make_request("DELETE", f"customers/{customer_id}/mandates/{mandate_id}")
    
    # Subscription Management
    def create_subscription(self, customer_id, amount, currency, interval, description, times=None, start_date=None, webhook_url=None, metadata=None):
        """Create a subscription"""
        data = {
            "amount": {
                "currency": currency,
                "value": f"{flt(amount):.2f}"
            },
            "interval": interval,
            "description": description
        }
        
        if times:
            data["times"] = cint(times)
        if start_date:
            data["startDate"] = start_date
        if webhook_url:
            data["webhookUrl"] = webhook_url
        if metadata:
            data["metadata"] = metadata
        
        return self._make_request("POST", f"customers/{customer_id}/subscriptions", data)
    
    def get_subscriptions(self, customer_id):
        """Get customer subscriptions"""
        return self._make_request("GET", f"customers/{customer_id}/subscriptions")
    
    def get_subscription(self, customer_id, subscription_id):
        """Get specific subscription"""
        return self._make_request("GET", f"customers/{customer_id}/subscriptions/{subscription_id}")
    
    def update_subscription(self, customer_id, subscription_id, amount=None, currency=None, times=None, start_date=None, description=None, metadata=None):
        """Update a subscription"""
        data = {}
        
        if amount and currency:
            data["amount"] = {
                "currency": currency,
                "value": f"{flt(amount):.2f}"
            }
        if times:
            data["times"] = cint(times)
        if start_date:
            data["startDate"] = start_date
        if description:
            data["description"] = description
        if metadata:
            data["metadata"] = metadata
        
        return self._make_request("PATCH", f"customers/{customer_id}/subscriptions/{subscription_id}", data)
    
    def cancel_subscription(self, customer_id, subscription_id):
        """Cancel a subscription"""
        return self._make_request("DELETE", f"customers/{customer_id}/subscriptions/{subscription_id}")
    
    # Payment Management
    def create_payment(self, amount, currency, description, redirect_url=None, webhook_url=None, method=None, customer_id=None, mandate_id=None, sequence_type=None, metadata=None):
        """Create a payment"""
        data = {
            "amount": {
                "currency": currency,
                "value": f"{flt(amount):.2f}"
            },
            "description": description
        }
        
        if redirect_url:
            data["redirectUrl"] = redirect_url
        if webhook_url:
            data["webhookUrl"] = webhook_url
        if method:
            data["method"] = method
        if customer_id:
            data["customerId"] = customer_id
        if mandate_id:
            data["mandateId"] = mandate_id
        if sequence_type:
            data["sequenceType"] = sequence_type
        if metadata:
            data["metadata"] = metadata
        
        if customer_id:
            return self._make_request("POST", f"customers/{customer_id}/payments", data)
        else:
            return self._make_request("POST", "payments", data)
    
    def get_payment(self, payment_id):
        """Get payment details"""
        return self._make_request("GET", f"payments/{payment_id}")
    
    def get_customer_payments(self, customer_id):
        """Get customer payments"""
        return self._make_request("GET", f"customers/{customer_id}/payments")
    
    def get_subscription_payments(self, customer_id, subscription_id):
        """Get subscription payments"""
        return self._make_request("GET", f"customers/{customer_id}/subscriptions/{subscription_id}/payments")
    
    # Methods Information
    def get_payment_methods(self):
        """Get available payment methods"""
        return self._make_request("GET", "methods")
    
    def get_payment_method(self, method_id):
        """Get specific payment method details"""
        return self._make_request("GET", f"methods/{method_id}")


@frappe.whitelist()
def create_mollie_customer(administration_name):
    """Create a Mollie customer for an administration"""
    try:
        admin = frappe.get_doc("Administration", administration_name)
        mollie = MollieAPI()
        
        # Create customer in Mollie
        customer_data = mollie.create_customer(
            name=admin.company_name or admin.name,
            email=admin.email,
            metadata={
                "administration_id": admin.name,
                "created_from": "Legal Portal"
            }
        )
        
        # Store Mollie customer ID in administration
        admin.mollie_customer_id = customer_data["id"]
        admin.save()
        
        return {
            "success": True,
            "customer_id": customer_data["id"],
            "message": "Mollie customer created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating Mollie customer: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def create_mollie_subscription(subscription_name):
    """Create a Mollie subscription"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        # Ensure Mollie customer exists
        if not admin.mollie_customer_id:
            customer_result = create_mollie_customer(admin.name)
            if not customer_result["success"]:
                return customer_result
        
        mollie = MollieAPI()
        
        # Map plan period to Mollie interval
        interval_mapping = {
            "Month": "1 month",
            "Year": "1 year"
        }
        
        interval = interval_mapping.get(plan.periode, "1 month")
        
        # Create subscription in Mollie
        mollie_subscription = mollie.create_subscription(
            customer_id=admin.mollie_customer_id,
            amount=plan.prijs,
            currency="EUR",
            interval=interval,
            description=f"Subscription to {plan.naam}",
            webhook_url=frappe.utils.get_url() + "/api/method/advanced_subscriptions.api.webhooks.mollie_webhook",
            metadata={
                "subscription_id": subscription.name,
                "plan_id": plan.name,
                "administration_id": admin.name
            }
        )
        
        # Store Mollie subscription ID
        subscription.mollie_subscription_id = mollie_subscription["id"]
        subscription.mollie_customer_id = admin.mollie_customer_id
        subscription.save()
        
        return {
            "success": True,
            "mollie_subscription_id": mollie_subscription["id"],
            "message": "Mollie subscription created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating Mollie subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }
