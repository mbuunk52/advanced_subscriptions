# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, flt, cint


@frappe.whitelist()
def create_payment_for_subscription(subscription_name, amount=None, description=None):
    """Create a one-time payment for a subscription"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        plan = frappe.get_doc("Plan", subscription.plan)
        admin = frappe.get_doc("Administration", subscription.administration)
        
        if not amount:
            amount = plan.prijs
        
        if not description:
            description = f"Payment for {plan.naam} subscription"
        
        # Get payment method
        if not subscription.betalingsmethode:
            return {
                "success": False,
                "message": "No payment method configured for this subscription"
            }
        
        payment_method = frappe.get_doc("Payment Method", subscription.betalingsmethode)
        provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
        
        if provider.provider_type == "Mollie":
            from advanced_subscriptions.integrations.mollie_api import MollieAPI
            
            mollie = MollieAPI(provider.name)
            
            # Ensure customer exists
            if not admin.mollie_customer_id:
                from advanced_subscriptions.integrations.mollie_api import create_mollie_customer
                customer_result = create_mollie_customer(admin.name)
                if not customer_result["success"]:
                    return customer_result
                admin.reload()
            
            # Create payment
            payment_data = mollie.create_payment(
                amount=amount,
                currency=payment_method.currency or "EUR",
                description=description,
                customer_id=admin.mollie_customer_id,
                redirect_url=f"{frappe.utils.get_url()}/tlp/instellingen/{subscription.name}",
                webhook_url=f"{frappe.utils.get_url()}/api/method/advanced_subscriptions.api.webhooks.mollie_webhook",
                metadata={
                    "subscription_id": subscription.name,
                    "administration_id": admin.name,
                    "plan_id": plan.name
                }
            )
            
            # Create payment record
            payment_record = frappe.new_doc("Payment Record")
            payment_record.mollie_payment_id = payment_data["id"]
            payment_record.amount = flt(amount)
            payment_record.currency = payment_method.currency or "EUR"
            payment_record.description = description
            payment_record.status = "Pending"
            payment_record.subscription = subscription.name
            payment_record.administration = admin.name
            payment_record.plan = plan.name
            payment_record.mollie_payment_data = frappe.as_json(payment_data)
            payment_record.insert()
            
            return {
                "success": True,
                "payment_id": payment_record.name,
                "checkout_url": payment_data["_links"]["checkout"]["href"],
                "message": "Payment created successfully"
            }
        
        else:
            return {
                "success": False,
                "message": f"Payment provider {provider.provider_type} not yet implemented"
            }
    
    except Exception as e:
        frappe.log_error(f"Error creating payment: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_subscription_payments(subscription_name):
    """Get all payments for a subscription"""
    try:
        payments = frappe.get_all("Payment Record",
            filters={"subscription": subscription_name},
            fields=["name", "amount", "currency", "status", "description", "created_at", "mollie_payment_id"],
            order_by="created_at desc"
        )
        
        return {
            "success": True,
            "payments": payments
        }
    
    except Exception as e:
        frappe.log_error(f"Error getting subscription payments: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def setup_subscription_with_mollie(administration_name, plan_name, payment_method_name):
    """Set up a complete subscription with Mollie integration"""
    try:
        # Validate inputs
        admin = frappe.get_doc("Administration", administration_name)
        plan = frappe.get_doc("Plan", plan_name)
        payment_method = frappe.get_doc("Payment Method", payment_method_name)
        provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
        
        if provider.provider_type != "Mollie":
            return {
                "success": False,
                "message": "This function only supports Mollie payment provider"
            }
        
        # Check if subscription already exists
        existing = frappe.get_all("Subscription",
            filters={
                "administration": administration_name,
                "status": ["in", ["Active", "Pending"]]
            })
        
        if existing:
            return {
                "success": False,
                "message": "An active subscription already exists for this administration"
            }
        
        # Create subscription
        subscription = frappe.new_doc("Subscription")
        subscription.administration = administration_name
        subscription.plan = plan_name
        subscription.betalingsmethode = payment_method_name
        subscription.status = "Pending"
        subscription.auto_renew = 1
        subscription.insert()
        
        # Create initial payment
        payment_result = create_payment_for_subscription(
            subscription.name,
            amount=plan.prijs,
            description=f"Initial payment for {plan.naam} subscription"
        )
        
        if payment_result["success"]:
            return {
                "success": True,
                "subscription_id": subscription.name,
                "payment_id": payment_result["payment_id"],
                "checkout_url": payment_result["checkout_url"],
                "message": "Subscription and payment created successfully"
            }
        else:
            # Rollback subscription creation
            subscription.delete()
            return payment_result
    
    except Exception as e:
        frappe.log_error(f"Error setting up subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def create_mandate_for_subscription(subscription_name, consumer_name, consumer_account, consumer_bic=None):
    """Create a SEPA mandate for recurring payments"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        admin = frappe.get_doc("Administration", subscription.administration)
        payment_method = frappe.get_doc("Payment Method", subscription.betalingsmethode)
        provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
        
        if provider.provider_type != "Mollie":
            return {
                "success": False,
                "message": "Mandate creation only supported for Mollie"
            }
        
        from advanced_subscriptions.integrations.mollie_api import MollieAPI
        
        mollie = MollieAPI(provider.name)
        
        # Ensure customer exists
        if not admin.mollie_customer_id:
            from advanced_subscriptions.integrations.mollie_api import create_mollie_customer
            customer_result = create_mollie_customer(admin.name)
            if not customer_result["success"]:
                return customer_result
            admin.reload()
        
        # Create mandate
        mandate_data = mollie.create_mandate(
            customer_id=admin.mollie_customer_id,
            method="directdebit",
            consumer_name=consumer_name,
            consumer_account=consumer_account,
            consumer_bic=consumer_bic,
            signature_date=today(),
            mandate_reference=f"SUB-{subscription.name}"
        )
        
        # Update subscription with mandate ID
        subscription.mollie_mandate_id = mandate_data["id"]
        subscription.save()
        
        return {
            "success": True,
            "mandate_id": mandate_data["id"],
            "message": "Mandate created successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error creating mandate: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def get_available_payment_methods(currency="EUR", amount=None):
    """Get available payment methods for a currency and amount"""
    try:
        filters = [
            ["is_active", "=", 1],
            ["currency", "=", currency]
        ]
        
        payment_methods = frappe.get_all("Payment Method",
            filters=filters,
            fields=["name", "method_name", "payment_provider", "provider_method_id", "description"]
        )
        
        # Filter by amount if provided
        if amount:
            available_methods = []
            for method in payment_methods:
                method_doc = frappe.get_doc("Payment Method", method.name)
                if method_doc.is_method_available(amount, currency):
                    available_methods.append(method)
            payment_methods = available_methods
        
        return {
            "success": True,
            "payment_methods": payment_methods
        }
    
    except Exception as e:
        frappe.log_error(f"Error getting payment methods: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@frappe.whitelist()
def cancel_subscription(subscription_name, reason=None):
    """Cancel a subscription"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        
        if subscription.status == "Cancelled":
            return {
                "success": False,
                "message": "Subscription is already cancelled"
            }
        
        # Cancel in Mollie if exists
        if subscription.mollie_subscription_id:
            subscription.cancel_mollie_subscription()
        
        # Update subscription status
        subscription.status = "Cancelled"
        if reason:
            subscription.add_comment("Comment", f"Cancellation reason: {reason}")
        
        subscription.save()
        
        # Send cancellation notification
        admin = frappe.get_doc("Administration", subscription.administration)
        frappe.sendmail(
            recipients=[admin.email],
            subject=f"Subscription Cancelled - {subscription.plan}",
            message=f"""
            <p>Dear {admin.company_name or admin.name},</p>
            <p>Your subscription to {subscription.plan} has been cancelled.</p>
            <p>Your subscription will remain active until {subscription.einddatum}.</p>
            <p>Thank you for using our services.</p>
            """
        )
        
        return {
            "success": True,
            "message": "Subscription cancelled successfully"
        }
    
    except Exception as e:
        frappe.log_error(f"Error cancelling subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }
