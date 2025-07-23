# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
import json
import hmac
import hashlib
from frappe import _
from frappe.utils import now


@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Handle Mollie webhook notifications"""
    try:
        # Get the request data
        data = frappe.local.form_dict
        payment_id = data.get("id")
        
        if not payment_id:
            frappe.log_error("Mollie webhook: No payment ID provided")
            return "Invalid request"
        
        # Log the webhook for debugging
        frappe.logger().info(f"Mollie webhook received for payment: {payment_id}")
        
        # Process the payment update
        process_mollie_payment_update(payment_id)
        
        return "OK"
    
    except Exception as e:
        frappe.log_error("Mollie webhook error", str(e))
        return "Error"


def process_mollie_payment_update(payment_id):
    """Process payment status update from Mollie"""
    try:
        from advanced_subscriptions.integrations.mollie_api import MollieAPI
        
        # Get payment details from Mollie
        mollie = MollieAPI()
        payment = mollie.get_payment(payment_id)
        
        # Find the corresponding payment record in our system
        payment_record = find_payment_record(payment)
        
        if payment_record:
            update_payment_status(payment_record, payment)
        else:
            # Create new payment record if it doesn't exist
            create_payment_record(payment)
    
    except Exception as e:
        frappe.log_error("Error processing Mollie payment update", str(e))


def find_payment_record(mollie_payment):
    """Find the payment record in our system"""
    payment_id = mollie_payment.get("id")
    
    # Check if we have a payment record with this Mollie payment ID
    payment_records = frappe.get_all("Payment Record", 
        filters={"mollie_payment_id": payment_id},
        fields=["name"])
    
    if payment_records:
        return frappe.get_doc("Payment Record", payment_records[0].name)
    
    # Check by metadata if available
    metadata = mollie_payment.get("metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    
    subscription_id = metadata.get("subscription_id")
    payment_type = metadata.get("payment_type")
    
    # For first payments, check if the subscription has this payment ID stored
    if payment_type == "first_payment" and subscription_id:
        subscriptions = frappe.get_all("Subscription",
            filters={"name": subscription_id, "first_payment_id": payment_id},
            fields=["name"])
        
        if subscriptions:
            # This is a first payment, we might not have a payment record yet
            return None
    
    if subscription_id:
        # Find payment records for this subscription
        subscription_payments = frappe.get_all("Payment Record",
            filters={
                "subscription": subscription_id,
                "mollie_payment_id": ["in", ["", None]]
            },
            fields=["name"],
            order_by="creation desc",
            limit=1)
        
        if subscription_payments:
            return frappe.get_doc("Payment Record", subscription_payments[0].name)
    
    return None


def update_payment_status(payment_record, mollie_payment):
    """Update payment record status based on Mollie payment"""
    status_mapping = {
        "open": "Pending",
        "pending": "Pending",
        "authorized": "Authorized",
        "expired": "Failed",
        "failed": "Failed",
        "canceled": "Cancelled",
        "paid": "Paid"
    }
    
    mollie_status = mollie_payment.get("status")
    new_status = status_mapping.get(mollie_status, "Unknown")
    
    if payment_record.status != new_status:
        payment_record.status = new_status
        payment_record.mollie_payment_id = mollie_payment.get("id")
        payment_record.mollie_payment_data = json.dumps(mollie_payment)
        payment_record.last_updated = now()
        
        # Handle successful payment
        if new_status == "Paid":
            handle_successful_payment(payment_record, mollie_payment)
        
        # Handle failed payment
        elif new_status in ["Failed", "Cancelled", "Expired"]:
            handle_failed_payment(payment_record, mollie_payment)
        
        payment_record.save(ignore_permissions=True)
        frappe.db.commit()


def create_payment_record(mollie_payment):
    """Create a new payment record from Mollie payment data"""
    try:
        metadata = mollie_payment.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        amount = mollie_payment.get("amount", {})
        
        payment_record = frappe.new_doc("Payment Record")
        payment_record.mollie_payment_id = mollie_payment.get("id")
        payment_record.amount = float(amount.get("value", 0))
        payment_record.currency = amount.get("currency", "EUR")
        payment_record.description = mollie_payment.get("description", "")
        payment_record.status = "Pending"
        payment_record.mollie_payment_data = json.dumps(mollie_payment)
        
        # Link to subscription if available
        subscription_id = metadata.get("subscription_id")
        if subscription_id:
            payment_record.subscription = subscription_id
        
        payment_record.insert(ignore_permissions=True)
        frappe.db.commit()
        
    except Exception as e:
        frappe.log_error("Error creating payment record", str(e))


def handle_successful_payment(payment_record, mollie_payment):
    """Handle successful payment"""
    try:
        metadata = mollie_payment.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        payment_type = metadata.get("payment_type")
        
        # Handle first payment completion - this establishes the mandate
        if payment_type == "first_payment":
            handle_first_payment_success(payment_record, mollie_payment, metadata)
        
        # Update subscription if this is a subscription payment
        if payment_record.subscription:
            subscription = frappe.get_doc("Subscription", payment_record.subscription)
            
            # Update subscription status to active if it was pending
            if subscription.status == "Pending":
                subscription.status = "Active"
                subscription.save(ignore_permissions=True)
            
            # Send payment confirmation email
            send_payment_confirmation(payment_record, subscription)
        
        # Log successful payment
        frappe.logger().info(f"Payment successful: {payment_record.mollie_payment_id}")
    
    except Exception as e:
        frappe.log_error("Error handling successful payment", str(e))


def handle_first_payment_success(payment_record, mollie_payment, metadata):
    """Handle successful first payment - create subscription with mandate"""
    try:
        subscription_id = metadata.get("subscription_id")
        if not subscription_id:
            frappe.log_error("No subscription_id found in first payment metadata")
            return
        
        # Process the first payment completion to create subscription
        from advanced_subscriptions.integrations.mollie_api import process_first_payment_completion
        
        result = process_first_payment_completion(mollie_payment.get("id"))
        
        if result.get("success"):
            frappe.logger().info(f"Successfully created subscription after first payment: {subscription_id}")
            
            # Update the subscription with the payment record
            subscription = frappe.get_doc("Subscription", subscription_id)
            payment_record.subscription = subscription_id
            payment_record.save(ignore_permissions=True)
            
            # Send confirmation email
            send_first_payment_confirmation(payment_record, subscription)
        else:
            frappe.log_error("Failed to create subscription after first payment", result.get('message'))
    
    except Exception as e:
        frappe.log_error("Error handling first payment success", str(e))


def send_first_payment_confirmation(payment_record, subscription):
    """Send first payment confirmation and subscription activation email"""
    try:
        admin = frappe.get_doc("Administration", subscription.administration)
        
        frappe.sendmail(
            recipients=[admin.email],
            subject=_("Subscription Activated - {0}").format(subscription.plan),
            message=f"""
            <p>{_("Dear {0}").format(admin.company_name or admin.name)},</p>
            <p>{_("Thank you for your first payment of €{0}!").format(payment_record.amount)}</p>
            <p>{_("Your {0} subscription has been successfully activated and will renew automatically.").format(subscription.plan)}</p>
            <p>{_("Payment ID: {0}").format(payment_record.mollie_payment_id)}</p>
            <p>{_("Subscription ID: {0}").format(subscription.name)}</p>
            <p>{_("We appreciate your business!")}</p>
            """,
            header=_("Subscription Activated")
        )
    
    except Exception as e:
        frappe.log_error("Error sending first payment confirmation", str(e))


def handle_failed_payment(payment_record, mollie_payment):
    """Handle failed payment"""
    try:
        # Update subscription status if needed
        if payment_record.subscription:
            subscription = frappe.get_doc("Subscription", payment_record.subscription)
            
            # Don't automatically cancel subscription on first failure
            # This should be handled by a separate process with retry logic
            
            # Send payment failure notification
            send_payment_failure_notification(payment_record, subscription)
        
        # Log failed payment
        frappe.logger().info(f"Payment failed: {payment_record.mollie_payment_id} - Status: {mollie_payment.get('status')}")
    
    except Exception as e:
        frappe.log_error("Error handling failed payment", str(e))


def send_payment_confirmation(payment_record, subscription):
    """Send payment confirmation email"""
    try:
        admin = frappe.get_doc("Administration", subscription.administration)
        
        frappe.sendmail(
            recipients=[admin.email],
            subject=_("Payment Confirmation - {0}").format(subscription.plan),
            message=f"""
            <p>{_("Dear {0}").format(admin.company_name or admin.name)},</p>
            <p>{_("We have successfully received your payment of €{0} for your {1} subscription.").format(payment_record.amount, subscription.plan)}</p>
            <p>{_("Payment ID: {0}").format(payment_record.mollie_payment_id)}</p>
            <p>{_("Thank you for your business!")}</p>
            """,
            header=_("Payment Confirmation")
        )
    
    except Exception as e:
        frappe.log_error("Error sending payment confirmation", str(e))


def send_payment_failure_notification(payment_record, subscription):
    """Send payment failure notification"""
    try:
        admin = frappe.get_doc("Administration", subscription.administration)
        
        frappe.sendmail(
            recipients=[admin.email],
            subject=_("Payment Failed - {0}").format(subscription.plan),
            message=f"""
            <p>{_("Dear {0}").format(admin.company_name or admin.name)},</p>
            <p>{_("Unfortunately, your payment of €{0} for your {1} subscription has failed.").format(payment_record.amount, subscription.plan)}</p>
            <p>{_("Payment ID: {0}").format(payment_record.mollie_payment_id)}</p>
            <p>{_("Please update your payment method or contact support for assistance.")}</p>
            """,
            header=_("Payment Failed")
        )
    
    except Exception as e:
        frappe.log_error("Error sending payment failure notification", str(e))


@frappe.whitelist(allow_guest=True)
def stripe_webhook():
    """Handle Stripe webhook notifications"""
    # Placeholder for Stripe webhook handling
    return "OK"


@frappe.whitelist(allow_guest=True)
def generic_webhook():
    """Handle generic payment provider webhooks"""
    # Placeholder for other payment providers
    return "OK"
