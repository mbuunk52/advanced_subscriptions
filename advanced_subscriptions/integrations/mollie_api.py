# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now, flt, cint
from mollie.api.client import Client
from mollie.api.error import Error as MollieError


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
        
        if not self.api_key:
            frappe.throw(_("Mollie API key not configured"))
            
        # Initialize Mollie client
        self.client = Client()
        self.client.set_api_key(self.api_key)
    
    # Customer Management
    def create_customer(self, name, email, metadata=None):
        """Create a customer in Mollie"""
        try:
            data = {
                'name': name,
                'email': email
            }
            if metadata:
                data['metadata'] = metadata
                
            customer = self.client.customers.create(data)
            return customer
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_customer(self, customer_id):
        """Get customer details"""
        try:
            return self.client.customers.get(customer_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def update_customer(self, customer_id, name=None, email=None, metadata=None):
        """Update customer details"""
        try:
            data = {}
            if name:
                data['name'] = name
            if email:
                data['email'] = email
            if metadata:
                data['metadata'] = metadata
            
            return self.client.customers.update(customer_id, data)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def delete_customer(self, customer_id):
        """Delete a customer"""
        try:
            return self.client.customers.delete(customer_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    # Mandate Management
    def create_mandate(self, customer_id, method, consumer_name, consumer_account, consumer_bic=None, signature_date=None, mandate_reference=None):
        """Create a mandate for recurring payments"""
        try:
            data = {
                'method': method,
                'consumerName': consumer_name,
                'consumerAccount': consumer_account
            }
            
            if consumer_bic:
                data['consumerBic'] = consumer_bic
            if signature_date:
                data['signatureDate'] = signature_date
            if mandate_reference:
                data['mandateReference'] = mandate_reference
            
            customer = self.client.customers.get(customer_id)
            return customer.mandates.create(data)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_mandates(self, customer_id):
        """Get customer mandates"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.mandates.list()
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_mandate(self, customer_id, mandate_id):
        """Get specific mandate"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.mandates.get(mandate_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def delete_mandate(self, customer_id, mandate_id):
        """Delete a mandate"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.mandates.delete(mandate_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    # Subscription Management
    def create_subscription(self, customer_id, amount, currency, interval, description, times=None, start_date=None, webhook_url=None, metadata=None):
        """Create a subscription"""
        try:
            data = {
                'amount': {
                    'currency': currency,
                    'value': f"{flt(amount):.2f}"
                },
                'interval': interval,
                'description': description
            }
            
            if times:
                data['times'] = cint(times)
            if start_date:
                data['startDate'] = start_date
            if webhook_url:
                data['webhookUrl'] = webhook_url
            if metadata:
                data['metadata'] = metadata
            
            customer = self.client.customers.get(customer_id)
            return customer.subscriptions.create(data)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_subscriptions(self, customer_id):
        """Get customer subscriptions"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.subscriptions.list()
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_subscription(self, customer_id, subscription_id):
        """Get specific subscription"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.subscriptions.get(subscription_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def update_subscription(self, customer_id, subscription_id, amount=None, currency=None, times=None, start_date=None, description=None, metadata=None):
        """Update a subscription"""
        try:
            data = {}
            
            if amount and currency:
                data['amount'] = {
                    'currency': currency,
                    'value': f"{flt(amount):.2f}"
                }
            if times:
                data['times'] = cint(times)
            if start_date:
                data['startDate'] = start_date
            if description:
                data['description'] = description
            if metadata:
                data['metadata'] = metadata
            
            customer = self.client.customers.get(customer_id)
            return customer.subscriptions.update(subscription_id, data)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def cancel_subscription(self, customer_id, subscription_id):
        """Cancel a subscription"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.subscriptions.delete(subscription_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    # Payment Management
    def create_payment(self, amount, currency, description, redirect_url=None, webhook_url=None, method=None, customer_id=None, mandate_id=None, sequence_type=None, metadata=None):
        """Create a payment"""
        try:
            data = {
                'amount': {
                    'currency': currency,
                    'value': f"{flt(amount):.2f}"
                },
                'description': description
            }
            
            if redirect_url:
                data['redirectUrl'] = redirect_url
            if webhook_url:
                data['webhookUrl'] = webhook_url
            if method:
                data['method'] = method
            if mandate_id:
                data['mandateId'] = mandate_id
            if sequence_type:
                data['sequenceType'] = sequence_type
            if metadata:
                data['metadata'] = metadata
            
            if customer_id:
                # When creating payment through customer endpoint, don't include customerId in payload
                customer = self.client.customers.get(customer_id)
                return customer.payments.create(data)
            else:
                # For standalone payments, include customerId if provided
                if customer_id:
                    data['customerId'] = customer_id
                return self.client.payments.create(data)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_payment(self, payment_id):
        """Get payment details"""
        try:
            return self.client.payments.get(payment_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_customer_payments(self, customer_id):
        """Get customer payments"""
        try:
            customer = self.client.customers.get(customer_id)
            return customer.payments.list()
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_subscription_payments(self, customer_id, subscription_id):
        """Get subscription payments"""
        try:
            customer = self.client.customers.get(customer_id)
            subscription = customer.subscriptions.get(subscription_id)
            return subscription.payments.list()
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    # Methods Information
    def get_payment_methods(self):
        """Get available payment methods"""
        try:
            return self.client.methods.list()
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")
    
    def get_payment_method(self, method_id):
        """Get specific payment method details"""
        try:
            return self.client.methods.get(method_id)
        except MollieError as e:
            frappe.throw(f"Mollie API Error: {str(e)}")


@frappe.whitelist()
def setup_recurring_payments(subscription_name):
    """Setup recurring payments for a subscription - creates customer, first payment, and subscription"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        mollie = MollieAPI()
        
        # Step 1: Ensure Mollie customer exists
        if not admin.mollie_customer_id:
            customer_result = create_mollie_customer(admin.name)
            if not customer_result["success"]:
                return customer_result
        
        # Step 2: Check for valid mandates
        mandates = mollie.get_mandates(admin.mollie_customer_id)
        valid_mandate = None
        
        for mandate in mandates:
            if mandate.status in ['valid', 'pending']:
                valid_mandate = mandate
                break
        
        # Step 3: If no valid mandate, create first payment to establish mandate
        if not valid_mandate:
            first_payment_result = create_first_payment(subscription_name)
            if not first_payment_result["success"]:
                return first_payment_result
            
            return {
                "success": True,
                "requires_customer_action": True,
                "payment_url": first_payment_result["payment_url"],
                "message": "Customer needs to complete first payment to establish mandate"
            }
        
        # Step 4: Create subscription if mandate exists
        subscription_result = create_mollie_subscription_with_mandate(subscription_name, valid_mandate.id)
        return subscription_result
    
    except Exception as e:
        frappe.log_error(f"Error setting up recurring payments: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def create_first_payment(subscription_name):
    """Create the first payment to establish a mandate for recurring payments"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        mollie = MollieAPI()
        
        # Get base URL and determine if we should use webhooks
        base_url = frappe.utils.get_url()
        webhook_url = None
        
        # Only set webhook URL if it's not localhost (for production/staging environments)
        if not ("localhost" in base_url or "127.0.0.1" in base_url):
            webhook_url = base_url + "/api/method/advanced_subscriptions.api.webhooks.mollie_webhook"
        
        # Create first payment with sequenceType: 'first'
        payment_data = mollie.create_payment(
            amount=plan.prijs,
            currency="EUR",
            description=f"First payment for {plan.naam} subscription",
            redirect_url=base_url + f"/tlp/instellingen/subscription/payment-result?payment_id={{id}}&type=first_payment",
            webhook_url=webhook_url,
            customer_id=admin.mollie_customer_id,
            sequence_type="first",
            metadata={
                "subscription_id": subscription.name,
                "plan_id": plan.name,
                "administration_id": admin.name,
                "payment_type": "first_payment"
            }
        )
        
        # Store first payment ID in subscription
        subscription.first_payment_id = payment_data.id
        subscription.save()
        
        return {
            "success": True,
            "payment_id": payment_data.id,
            "payment_url": payment_data.checkout_url,
            "message": "First payment created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating first payment: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def create_mollie_subscription_with_mandate(subscription_name, mandate_id=None):
    """Create a Mollie subscription after mandate is established"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        mollie = MollieAPI()
        
        # If no mandate_id provided, find the first valid one
        if not mandate_id:
            mandates = mollie.get_mandates(admin.mollie_customer_id)
            for mandate in mandates:
                if mandate.status == 'valid':
                    mandate_id = mandate.id
                    break
        
        if not mandate_id:
            return {
                "success": False,
                "message": "No valid mandate found. Please complete the first payment first."
            }
        
        # Map plan period to Mollie interval
        interval_mapping = {
            "Month": "1 month",
            "Year": "1 year"
        }
        
        interval = interval_mapping.get(plan.periode, "1 month")
        
        # Get base URL and determine if we should use webhooks
        base_url = frappe.utils.get_url()
        webhook_url = None
        
        # Only set webhook URL if it's not localhost (for production/staging environments)
        if not ("localhost" in base_url or "127.0.0.1" in base_url):
            webhook_url = base_url + "/api/method/advanced_subscriptions.api.webhooks.mollie_webhook"
        
        # Create subscription in Mollie
        mollie_subscription = mollie.create_subscription(
            customer_id=admin.mollie_customer_id,
            amount=plan.prijs,
            currency="EUR",
            interval=interval,
            description=f"Subscription to {plan.naam}",
            webhook_url=webhook_url,
            metadata={
                "subscription_id": subscription.name,
                "plan_id": plan.name,
                "administration_id": admin.name
            }
        )
        
        # Store Mollie subscription and mandate IDs
        subscription.mollie_subscription_id = mollie_subscription.id
        subscription.mollie_customer_id = admin.mollie_customer_id
        subscription.mollie_mandate_id = mandate_id
        subscription.status = "Active"
        subscription.save()
        
        return {
            "success": True,
            "mollie_subscription_id": mollie_subscription.id,
            "message": "Mollie subscription created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating Mollie subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


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
        admin.mollie_customer_id = customer_data.id
        admin.save()
        
        return {
            "success": True,
            "customer_id": customer_data.id,
            "message": "Mollie customer created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating Mollie customer: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def check_mandate_status(administration_name):
    """Check if an administration has valid mandates"""
    try:
        admin = frappe.get_doc("Administration", administration_name)
        
        if not admin.mollie_customer_id:
            return {
                "success": False,
                "has_mandate": False,
                "message": "No Mollie customer found"
            }
        
        mollie = MollieAPI()
        mandates = mollie.get_mandates(admin.mollie_customer_id)
        
        valid_mandates = [m for m in mandates if m.status in ['valid', 'pending']]
        
        return {
            "success": True,
            "has_mandate": len(valid_mandates) > 0,
            "mandate_count": len(valid_mandates),
            "mandates": [{"id": m.id, "status": m.status, "method": m.method} for m in valid_mandates]
        }
    
    except Exception as e:
        frappe.log_error(f"Error checking mandate status: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def process_first_payment_completion(payment_id):
    """Process completion of first payment and create subscription"""
    try:
        mollie = MollieAPI()
        payment = mollie.get_payment(payment_id)
        
        if payment.status != 'paid':
            return {
                "success": False,
                "message": f"Payment not completed yet. Status: {payment.status}"
            }
        
        # Find subscription from metadata
        metadata = payment.metadata or {}
        subscription_name = metadata.get('subscription_id')
        
        if not subscription_name:
            return {
                "success": False,
                "message": "No subscription found in payment metadata"
            }
        
        subscription = frappe.get_doc("Subscription", subscription_name)
        
        # Get customer's mandates
        mandates = mollie.get_mandates(payment.customer_id)
        valid_mandate = None
        
        for mandate in mandates:
            if mandate.status == 'valid':
                valid_mandate = mandate
                break
        
        if not valid_mandate:
            return {
                "success": False,
                "message": "No valid mandate found after first payment"
            }
        
        # Create subscription now that we have a valid mandate
        result = create_mollie_subscription_with_mandate(subscription_name, valid_mandate.id)
        
        if result["success"]:
            # Update subscription status
            subscription.status = "Active"
            subscription.save()
        
        return result
    
    except Exception as e:
        frappe.log_error(f"Error processing first payment completion: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }
