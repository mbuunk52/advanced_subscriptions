# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, add_months, flt
import json


class SubscriptionFlowManager:
    """Unified subscription flow manager for clean and simple subscription handling"""
    
    def __init__(self):
        self.mollie_api = None
    
    def get_mollie_api(self, provider_name=None):
        """Get MollieAPI instance"""
        if not self.mollie_api:
            from advanced_subscriptions.integrations.mollie_api import MollieAPI
            self.mollie_api = MollieAPI(provider_name)
        return self.mollie_api


@frappe.whitelist()
def create_subscription_with_payment(administration_name, plan_name, payment_method_name):
    """
    Main entry point for subscription creation with Mollie payment flow
    
    Step-by-step process:
    1. Validate inputs and check for existing subscriptions
    2. Create or get Mollie customer
    3. Create subscription record (status: Pending)
    4. Create first payment for mandate establishment
    5. Return payment URL for user to complete
    """
    try:
        flow_manager = SubscriptionFlowManager()
        
        # Step 1: Validate inputs
        validation_result = _validate_subscription_inputs(administration_name, plan_name, payment_method_name)
        if not validation_result["success"]:
            return validation_result
        
        admin, plan, payment_method, provider = validation_result["data"]
        
        # Step 2: Ensure Mollie customer exists
        customer_result = _ensure_mollie_customer(admin, flow_manager)
        if not customer_result["success"]:
            return customer_result
        
        # Step 3: Create subscription record
        subscription = _create_subscription_record(admin, plan, payment_method)
        
        # Step 4: Create first payment
        payment_result = _create_first_payment(subscription, flow_manager)
        if not payment_result["success"]:
            # Clean up subscription if payment creation fails
            subscription.delete()
            return payment_result
        
        # Step 5: Update subscription with payment details
        subscription.first_payment_id = payment_result["payment_id"]
        subscription.first_payment_url = payment_result["payment_url"]
        subscription.save()
        
        return {
            "success": True,
            "subscription_id": subscription.name,
            "payment_url": payment_result["payment_url"],
            "message": _("Subscription created. Please complete payment to activate.")
        }
        
    except Exception as e:
        frappe.log_error(f"Error in subscription flow: {str(e)}", "Subscription Flow Error")
        return {
            "success": False,
            "message": _("An error occurred while creating your subscription. Please try again.")
        }


@frappe.whitelist()
def handle_payment_completion(payment_id):
    """
    Handle successful payment completion
    
    This is called by webhooks or manual check after payment completion:
    1. Verify payment is successful
    2. Create Mollie subscription with established mandate
    3. Activate subscription
    4. Send confirmation email
    """
    try:
        flow_manager = SubscriptionFlowManager()
        mollie = flow_manager.get_mollie_api()
        
        # Step 1: Get payment details from Mollie
        payment = mollie.get_payment(payment_id)
        
        if payment.status != 'paid':
            return {
                "success": False,
                "status": payment.status,
                "message": _("Payment not completed yet. Current status: {0}").format(payment.status)
            }
        
        # Step 2: Find subscription from payment metadata
        metadata = payment.metadata or {}
        subscription_id = metadata.get('subscription_id')
        
        if not subscription_id:
            return {
                "success": False,
                "message": _("Could not find subscription for this payment")
            }
        
        subscription = frappe.get_doc("Subscription", subscription_id)
        
        if subscription.status == "Active":
            return {
                "success": True,
                "message": _("Subscription is already active")
            }
        
        # Step 3: Get valid mandate from Mollie
        admin = frappe.get_doc("Administration", subscription.administration)
        mandates = mollie.get_mandates(admin.mollie_customer_id)
        
        valid_mandate = None
        for mandate in mandates:
            if mandate.status == 'valid':
                valid_mandate = mandate
                break
        
        if not valid_mandate:
            return {
                "success": False,
                "message": _("No valid payment mandate found. Please contact support.")
            }
        
        # Step 4: Create Mollie subscription
        mollie_subscription_result = _create_mollie_subscription(subscription, valid_mandate.id, flow_manager)
        if not mollie_subscription_result["success"]:
            return mollie_subscription_result
        
        # Step 5: Activate subscription
        subscription.status = "Active"
        subscription.mollie_subscription_id = mollie_subscription_result["mollie_subscription_id"]
        subscription.mollie_mandate_id = valid_mandate.id
        subscription.mollie_customer_id = admin.mollie_customer_id
        subscription.save()
        
        # Step 6: Create payment record
        _create_payment_record(payment, subscription)
        
        # Step 7: Send confirmation email
        _send_activation_email(subscription)
        
        return {
            "success": True,
            "message": _("Subscription activated successfully!")
        }
        
    except Exception as e:
        frappe.log_error(f"Error handling payment completion: {str(e)}", "Payment Completion Error")
        return {
            "success": False,
            "message": _("Error processing payment. Please contact support.")
        }


@frappe.whitelist()
def retry_failed_payment(subscription_name):
    """
    Retry payment for a failed subscription
    Creates a new payment URL for the user to try again
    """
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        
        if subscription.status == "Active":
            return {
                "success": False,
                "message": _("Subscription is already active")
            }
        
        flow_manager = SubscriptionFlowManager()
        
        # Create new first payment
        payment_result = _create_first_payment(subscription, flow_manager)
        if not payment_result["success"]:
            return payment_result
        
        # Update subscription with new payment details
        subscription.first_payment_id = payment_result["payment_id"]
        subscription.first_payment_url = payment_result["payment_url"]
        subscription.save()
        
        return {
            "success": True,
            "payment_url": payment_result["payment_url"],
            "message": _("New payment link created. Please complete payment to activate.")
        }
        
    except Exception as e:
        frappe.log_error(f"Error retrying payment: {str(e)}", "Payment Retry Error")
        return {
            "success": False,
            "message": _("Error creating new payment. Please try again.")
        }


@frappe.whitelist()
def get_subscription_status(subscription_name):
    """Get current subscription status with payment info if needed"""
    try:
        subscription = frappe.get_doc("Subscription", subscription_name)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        response = {
            "subscription_id": subscription.name,
            "status": subscription.status,
            "plan_name": plan.naam,
            "plan_price": plan.prijs,
            "start_date": subscription.startdatum,
            "end_date": subscription.einddatum
        }
        
        # If pending, include payment info
        if subscription.status == "Pending" and subscription.first_payment_url:
            response["payment_url"] = subscription.first_payment_url
            response["payment_id"] = subscription.first_payment_id
        
        return {
            "success": True,
            "data": response
        }
        
    except Exception as e:
        frappe.log_error(f"Error getting subscription status: {str(e)}", "Subscription Status Error")
        return {
            "success": False,
            "message": _("Error getting subscription status")
        }


# Helper Functions

def _validate_subscription_inputs(administration_name, plan_name, payment_method_name):
    """Validate all inputs for subscription creation"""
    try:
        # Check if subscription already exists
        existing = frappe.get_all("Subscription",
            filters={
                "administration": administration_name,
                "status": ["in", ["Active", "Pending"]]
            })
        
        if existing:
            return {
                "success": False,
                "message": _("An active or pending subscription already exists for this administration")
            }
        
        # Validate all required documents exist
        admin = frappe.get_doc("Administration", administration_name)
        plan = frappe.get_doc("Plan", plan_name)
        payment_method = frappe.get_doc("Payment Method", payment_method_name)
        provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
        
        # Validate provider type
        if provider.provider_type != "Mollie":
            return {
                "success": False,
                "message": _("Only Mollie payment provider is currently supported")
            }
        
        # Validate plan is active
        if not plan.is_active:
            return {
                "success": False,
                "message": _("Selected plan is not available")
            }
        
        return {
            "success": True,
            "data": (admin, plan, payment_method, provider)
        }
        
    except frappe.DoesNotExistError as e:
        return {
            "success": False,
            "message": _("Invalid input: {0}").format(str(e))
        }


def _ensure_mollie_customer(admin, flow_manager):
    """Ensure Mollie customer exists for the administration"""
    if admin.mollie_customer_id:
        return {"success": True}
    
    try:
        mollie = flow_manager.get_mollie_api()
        
        customer_data = mollie.create_customer(
            name=admin.company_name or admin.name,
            email=admin.email,
            metadata={
                "administration_id": admin.name,
                "created_from": "Legal Portal Subscription"
            }
        )
        
        # Update administration with customer ID
        admin.mollie_customer_id = customer_data.id
        admin.db_update()
        
        return {"success": True}
        
    except Exception as e:
        frappe.log_error(f"Error creating Mollie customer: {str(e)}", "Mollie Customer Creation")
        return {
            "success": False,
            "message": _("Error setting up payment account. Please try again.")
        }


def _create_subscription_record(admin, plan, payment_method):
    """Create subscription record in Pending status"""
    subscription = frappe.new_doc("Subscription")
    subscription.administration = admin.name
    subscription.plan = plan.name
    subscription.betalingsmethode = payment_method.name
    subscription.status = "Pending"
    subscription.auto_renew = 1
    subscription.startdatum = today()
    
    # Set end date based on plan period
    if plan.periode == "Month":
        subscription.einddatum = add_months(today(), 1)
    elif plan.periode == "Year":
        subscription.einddatum = add_months(today(), 12)
    
    subscription.insert()
    return subscription


def _create_first_payment(subscription, flow_manager):
    """Create first payment to establish mandate"""
    try:
        mollie = flow_manager.get_mollie_api()
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        # Create first payment with sequenceType: 'first'
        payment_data = mollie.create_payment(
            amount=plan.prijs,
            currency="EUR",
            description=_("First payment for {0} subscription").format(plan.naam),
            redirect_url=f"{frappe.utils.get_url()}/tlp/payment-result?subscription_id={subscription.name}",
            webhook_url=f"{frappe.utils.get_url()}/api/method/advanced_subscriptions.api.subscription_flow.webhook_handler",
            customer_id=admin.mollie_customer_id,
            sequence_type="first",
            metadata={
                "subscription_id": subscription.name,
                "payment_type": "first_payment",
                "administration_id": admin.name,
                "plan_id": plan.name
            }
        )
        
        # Extract checkout URL
        checkout_url = None
        if hasattr(payment_data, '_links') and payment_data._links and 'checkout' in payment_data._links:
            checkout_url = payment_data._links['checkout']['href']
        elif hasattr(payment_data, 'checkout_url'):
            checkout_url = payment_data.checkout_url
        
        if not checkout_url:
            raise Exception("Could not get checkout URL from Mollie")
        
        return {
            "success": True,
            "payment_id": payment_data.id,
            "payment_url": checkout_url
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating first payment: {str(e)}", "First Payment Creation")
        return {
            "success": False,
            "message": _("Error creating payment. Please try again.")
        }


def _create_mollie_subscription(subscription, mandate_id, flow_manager):
    """Create Mollie subscription with established mandate"""
    try:
        mollie = flow_manager.get_mollie_api()
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
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
            description=_("Subscription to {0}").format(plan.naam),
            webhook_url=f"{frappe.utils.get_url()}/api/method/advanced_subscriptions.api.subscription_flow.webhook_handler",
            metadata={
                "subscription_id": subscription.name,
                "plan_id": plan.name,
                "administration_id": admin.name
            }
        )
        
        return {
            "success": True,
            "mollie_subscription_id": mollie_subscription.id
        }
        
    except Exception as e:
        frappe.log_error(f"Error creating Mollie subscription: {str(e)}", "Mollie Subscription Creation")
        return {
            "success": False,
            "message": _("Error setting up recurring payments. Please contact support.")
        }


def _create_payment_record(payment, subscription):
    """Create payment record for successful payment"""
    try:
        amount_data = payment.amount if hasattr(payment, 'amount') else {}
        amount = float(amount_data.get('value', 0)) if isinstance(amount_data, dict) else float(amount_data or 0)
        
        payment_record = frappe.new_doc("Payment Record")
        payment_record.mollie_payment_id = payment.id
        payment_record.amount = amount
        payment_record.currency = "EUR"
        payment_record.description = payment.description
        payment_record.status = "Paid"
        payment_record.subscription = subscription.name
        payment_record.administration = subscription.administration
        payment_record.plan = subscription.plan
        payment_record.mollie_payment_data = json.dumps(payment.__dict__ if hasattr(payment, '__dict__') else str(payment))
        payment_record.insert()
        
        return payment_record
        
    except Exception as e:
        frappe.log_error(f"Error creating payment record: {str(e)}", "Payment Record Creation")


def _send_activation_email(subscription):
    """Send subscription activation email"""
    try:
        admin = frappe.get_doc("Administration", subscription.administration)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        frappe.sendmail(
            recipients=[admin.email],
            subject=_("Subscription Activated - {0}").format(plan.naam),
            message=f"""
            <h3>{_("Subscription Successfully Activated!")}</h3>
            <p>{_("Dear {0},").format(admin.company_name or admin.name)}</p>
            <p>{_("Your {0} subscription has been successfully activated.").format(plan.naam)}</p>
            <p><strong>{_("Subscription Details:")}</strong></p>
            <ul>
                <li>{_("Plan: {0}").format(plan.naam)}</li>
                <li>{_("Price: €{0} per {1}").format(plan.prijs, plan.periode.lower())}</li>
                <li>{_("Start Date: {0}").format(subscription.startdatum)}</li>
                <li>{_("Next Payment: {0}").format(subscription.einddatum)}</li>
            </ul>
            <p>{_("Your subscription will renew automatically. You can manage your subscription in your account settings.")}</p>
            <p>{_("Thank you for choosing our services!")}</p>
            """,
            header=_("Subscription Activated")
        )
        
    except Exception as e:
        frappe.log_error(f"Error sending activation email: {str(e)}", "Activation Email")


@frappe.whitelist(allow_guest=True)
def webhook_handler():
    """Handle webhooks from Mollie for payments and subscriptions"""
    try:
        # Get payment ID from webhook
        payment_id = frappe.request.form.get('id')
        if not payment_id:
            return
        
        # Handle payment completion
        result = handle_payment_completion(payment_id)
        
        # Log webhook processing
        frappe.logger().info(f"Webhook processed for payment {payment_id}: {result}")
        
    except Exception as e:
        frappe.log_error(f"Error processing webhook: {str(e)}", "Webhook Error")
