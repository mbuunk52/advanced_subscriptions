# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, flt, cint


@frappe.whitelist()
def create_payment_for_subscription(subscription_name, amount=None, description=None):
    """
    DEPRECATED: Use subscription_flow.retry_failed_payment instead
    Create a one-time payment for a subscription
    """
    frappe.log_error("Deprecated function called: create_payment_for_subscription", "Deprecated API Usage")
    
    # Redirect to new flow
    from advanced_subscriptions.api.subscription_flow import retry_failed_payment
    return retry_failed_payment(subscription_name)


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
    """
    DEPRECATED: Use subscription_flow.create_subscription_with_payment instead
    Set up a complete subscription with Mollie integration
    """
    frappe.log_error("Deprecated function called: setup_subscription_with_mollie", "Deprecated API Usage")
    
    # Redirect to new unified flow
    from advanced_subscriptions.api.subscription_flow import create_subscription_with_payment
    return create_subscription_with_payment(administration_name, plan_name, payment_method_name)


@frappe.whitelist()
def create_mandate_for_subscription(subscription_name, consumer_name, consumer_account, consumer_bic=None):
    """
    DEPRECATED: Mandate creation is now handled automatically in the subscription flow
    Create a SEPA mandate for recurring payments
    """
    return {
        "success": False,
        "message": _("Manual mandate creation is no longer supported. Mandates are created automatically during subscription setup.")
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
            # Add amount-based filtering logic here if needed
            pass
        
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
    """Cancel a subscription - simplified version"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        
        if subscription.status == "Cancelled":
            return {
                "success": False,
                "message": _("Subscription is already cancelled")
            }
        
        # Cancel in Mollie if exists
        if subscription.mollie_subscription_id:
            try:
                from advanced_subscriptions.integrations.mollie_api import MollieAPI
                mollie = MollieAPI()
                mollie.cancel_subscription(subscription.mollie_customer_id, subscription.mollie_subscription_id)
            except Exception as e:
                frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}")
                # Continue with cancellation even if Mollie fails
        
        # Update subscription status
        subscription.status = "Cancelled"
        if reason:
            subscription.cancellation_reason = reason
        
        subscription.save()
        
        # Send cancellation notification
        try:
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
        except Exception as e:
            frappe.log_error(f"Error sending cancellation email: {str(e)}")
        
        return {
            "success": True,
            "message": _("Subscription cancelled successfully")
        }
    
    except Exception as e:
        frappe.log_error(f"Error cancelling subscription: {str(e)}")
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
