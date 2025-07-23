# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, add_months, now
from advanced_subscriptions.integrations.mollie_api import MollieAPI


class SubscriptionService:
    """Centralized subscription management service"""
    
    def __init__(self):
        self.mollie = MollieAPI()
    
    def create_subscription(self, administration_name, plan_name, payment_method_name=None):
        """
        Create a new subscription with the following flow:
        1. Validate inputs
        2. Check for existing subscription
        3. Create subscription record (status=Pending)
        4. Ensure Mollie customer exists
        5. Create first payment
        6. Return payment URL for customer to complete
        """
        try:
            # Step 1: Validate inputs
            admin = frappe.get_doc("Administration", administration_name)
            plan = frappe.get_doc("Plan", plan_name)
            
            if payment_method_name:
                payment_method = frappe.get_doc("Payment Method", payment_method_name)
                provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
                
                if provider.provider_type != "Mollie":
                    frappe.throw(_("Only Mollie payments are supported"))
            
            # Step 2: Check for existing active subscription
            existing = frappe.get_value("Subscription", {
                "administration": administration_name,
                "status": ["in", ["Active", "Pending"]]
            })
            
            if existing:
                frappe.throw(_("An active subscription already exists"))
            
            # Step 3: Create subscription record (status=Pending)
            subscription = frappe.new_doc("Subscription")
            subscription.administration = administration_name
            subscription.plan = plan_name
            subscription.startdatum = today()
            subscription.status = "Pending"
            subscription.auto_renew = 1
            
            if payment_method_name:
                subscription.betalingsmethode = payment_method_name
            
            # Set end date based on plan period
            if plan.periode == "Month":
                subscription.einddatum = add_months(subscription.startdatum, 1)
            elif plan.periode == "Year":
                subscription.einddatum = add_months(subscription.startdatum, 12)
            
            subscription.insert()
            
            # Step 4 & 5: Handle Mollie payment if payment method provided
            payment_url = None
            if payment_method_name:
                payment_url = self._create_first_payment(subscription, admin, plan, payment_method)
            
            return {
                "success": True,
                "subscription_id": subscription.name,
                "payment_url": payment_url,
                "message": _("Subscription created. Please complete payment to activate.")
            }
            
        except Exception as e:
            frappe.log_error(f"Error creating subscription: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def _create_first_payment(self, subscription, admin, plan, payment_method):
        """Create first payment for subscription"""
        try:
            # Step 1: Ensure Mollie customer exists
            if not admin.mollie_customer_id:
                customer_result = self._ensure_mollie_customer(admin)
                if not customer_result["success"]:
                    frappe.throw(customer_result["message"])
                admin.reload()
            
            # Step 2: Create first payment
            payment_data = self.mollie.create_payment(
                amount=plan.prijs,
                currency="EUR",
                description=_("First payment for {0} subscription").format(plan.naam),
                redirect_url=self._get_payment_redirect_url("first_payment"),
                webhook_url=self._get_webhook_url(),
                customer_id=admin.mollie_customer_id,
                sequence_type="first",
                metadata={
                    "subscription_id": subscription.name,
                    "plan_id": plan.name,
                    "administration_id": admin.name,
                    "payment_type": "first_payment"
                }
            )
            
            # Step 3: Create payment record
            payment_record = frappe.new_doc("Payment Record")
            payment_record.mollie_payment_id = payment_data.id
            payment_record.amount = plan.prijs
            payment_record.currency = "EUR"
            payment_record.description = payment_data.description
            payment_record.status = "Pending"
            payment_record.subscription = subscription.name
            payment_record.administration = admin.name
            payment_record.plan = plan.name
            payment_record.mollie_payment_data = frappe.as_json(payment_data.__dict__ if hasattr(payment_data, '__dict__') else str(payment_data))
            payment_record.insert()
            
            # Step 4: Store payment ID in subscription
            subscription.first_payment_id = payment_data.id
            subscription.save()
            
            # Step 5: Get checkout URL
            checkout_url = self._get_checkout_url(payment_data)
            
            return checkout_url
            
        except Exception as e:
            frappe.log_error(f"Error creating first payment: {str(e)}")
            frappe.throw(_("Failed to create payment: {0}").format(str(e)))
    
    def _ensure_mollie_customer(self, admin):
        """Ensure Mollie customer exists for administration"""
        try:
            customer_data = self.mollie.create_customer(
                name=admin.company_name or admin.name,
                email=admin.email,
                metadata={
                    "administration_id": admin.name,
                    "created_from": "Legal Portal"
                }
            )
            
            admin.mollie_customer_id = customer_data.id
            admin.db_update()
            
            return {
                "success": True,
                "customer_id": customer_data.id
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def process_first_payment_success(self, payment_id):
        """Process successful first payment and activate subscription"""
        try:
            # Step 1: Get payment and subscription details
            payment = self.mollie.get_payment(payment_id)
            
            if payment.status != 'paid':
                return {
                    "success": False,
                    "message": _("Payment not completed")
                }
            
            metadata = payment.metadata or {}
            subscription_name = metadata.get('subscription_id')
            
            if not subscription_name:
                frappe.throw(_("No subscription found in payment metadata"))
            
            subscription = frappe.get_doc("Subscription", subscription_name)
            admin = frappe.get_doc("Administration", subscription.administration)
            
            # Step 2: Update payment record
            payment_record = frappe.get_value("Payment Record", {
                "mollie_payment_id": payment_id
            })
            
            if payment_record:
                payment_doc = frappe.get_doc("Payment Record", payment_record)
                payment_doc.status = "Paid"
                payment_doc.save()
            
            # Step 3: Check if mandate was created
            mandates = self.mollie.get_mandates(admin.mollie_customer_id)
            valid_mandate = None
            
            for mandate in mandates:
                if mandate.status == 'valid':
                    valid_mandate = mandate
                    break
            
            if not valid_mandate:
                return {
                    "success": False,
                    "message": _("No valid mandate found after payment")
                }
            
            # Step 4: Create Mollie subscription
            result = self._create_mollie_subscription(subscription, admin, valid_mandate.id)
            
            if result["success"]:
                # Step 5: Activate subscription
                subscription.status = "Active"
                subscription.mollie_subscription_id = result["mollie_subscription_id"]
                subscription.mollie_customer_id = admin.mollie_customer_id
                subscription.mollie_mandate_id = valid_mandate.id
                subscription.save()
                
                # Step 6: Send confirmation email
                self._send_activation_email(subscription, admin)
            
            return result
            
        except Exception as e:
            frappe.log_error(f"Error processing first payment success: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def _create_mollie_subscription(self, subscription, admin, mandate_id):
        """Create subscription in Mollie"""
        try:
            plan = frappe.get_doc("Plan", subscription.plan)
            
            # Map plan period to Mollie interval
            interval_mapping = {
                "Month": "1 month",
                "Year": "1 year"
            }
            interval = interval_mapping.get(plan.periode, "1 month")
            
            mollie_subscription = self.mollie.create_subscription(
                customer_id=admin.mollie_customer_id,
                amount=plan.prijs,
                currency="EUR",
                interval=interval,
                description=_("Subscription to {0}").format(plan.naam),
                webhook_url=self._get_webhook_url(),
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
            return {
                "success": False,
                "message": str(e)
            }
    
    def handle_payment_failure(self, payment_id):
        """Handle failed payment"""
        try:
            # Update payment record
            payment_record = frappe.get_value("Payment Record", {
                "mollie_payment_id": payment_id
            })
            
            if payment_record:
                payment_doc = frappe.get_doc("Payment Record", payment_record)
                payment_doc.status = "Failed"
                payment_doc.save()
                
                # Get subscription and provide retry option
                if payment_doc.subscription:
                    subscription = frappe.get_doc("Subscription", payment_doc.subscription)
                    
                    # Create new payment for retry
                    admin = frappe.get_doc("Administration", subscription.administration)  
                    plan = frappe.get_doc("Plan", subscription.plan)
                    payment_method = frappe.get_doc("Payment Method", subscription.betalingsmethode) if subscription.betalingsmethode else None
                    
                    if payment_method:
                        retry_url = self._create_first_payment(subscription, admin, plan, payment_method)
                        subscription.first_payment_url = retry_url
                        subscription.save()
                        
                        return {
                            "success": True,
                            "retry_url": retry_url,
                            "message": _("Payment failed. Please try again.")
                        }
            
            return {
                "success": False,
                "message": _("Payment failed")
            }
            
        except Exception as e:
            frappe.log_error(f"Error handling payment failure: {str(e)}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def cancel_subscription(self, subscription_name):
        """Cancel subscription"""
        try:
            subscription = frappe.get_doc("Subscription", subscription_name)
            
            if subscription.status == "Cancelled":
                return {
                    "success": False,
                    "message": _("Subscription is already cancelled")
                }
            
            # Cancel in Mollie if exists
            if subscription.mollie_subscription_id and subscription.mollie_customer_id:
                try:
                    self.mollie.cancel_subscription(subscription.mollie_customer_id, subscription.mollie_subscription_id)
                except Exception as e:
                    frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}")
            
            # Update subscription status
            subscription.status = "Cancelled"
            subscription.save()
            
            # Send cancellation email
            admin = frappe.get_doc("Administration", subscription.administration)
            self._send_cancellation_email(subscription, admin)
            
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
    
    def get_subscription_status(self, subscription_name):
        """Get current subscription status with payment info"""
        try:
            subscription = frappe.get_doc("Subscription", subscription_name)
            
            result = {
                "subscription": subscription.as_dict(),
                "status": subscription.status
            }
            
            # If pending, check if there's a payment URL
            if subscription.status == "Pending" and subscription.first_payment_url:
                result["payment_url"] = subscription.first_payment_url
                result["message"] = _("Please complete your payment to activate the subscription")
            
            # Get recent payments
            recent_payments = frappe.get_all("Payment Record",
                filters={"subscription": subscription_name},
                fields=["name", "status", "amount", "created_at", "mollie_payment_id"],
                order_by="created_at desc",
                limit=5
            )
            result["recent_payments"] = recent_payments
            
            return {
                "success": True,
                "data": result
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": str(e)
            }
    
    def _get_checkout_url(self, payment_data):
        """Extract checkout URL from Mollie payment data"""
        try:
            # Try different methods to get checkout URL
            if hasattr(payment_data, '_links') and payment_data._links and 'checkout' in payment_data._links:
                return payment_data._links['checkout']['href']
            elif hasattr(payment_data, 'checkout_url'):
                return payment_data.checkout_url
            elif hasattr(payment_data, 'links') and 'checkout' in payment_data.links:
                return payment_data.links['checkout']['href']
            else:
                frappe.throw(_("Could not retrieve checkout URL from payment"))
        except Exception as e:
            frappe.log_error(f"Error getting checkout URL: {str(e)}")
            frappe.throw(_("Could not retrieve payment URL"))
    
    def _get_payment_redirect_url(self, payment_type):
        """Get redirect URL for payment completion"""
        base_url = frappe.utils.get_url()
        return f"{base_url}/tlp/payment-result?payment_id={{id}}&type={payment_type}"
    
    def _get_webhook_url(self):
        """Get webhook URL (only for non-localhost environments)"""
        base_url = frappe.utils.get_url()
        if "localhost" in base_url or "127.0.0.1" in base_url:
            return None
        return f"{base_url}/api/method/advanced_subscriptions.api.webhooks.mollie_webhook"
    
    def _send_activation_email(self, subscription, admin):
        """Send subscription activation email"""
        try:
            plan = frappe.get_doc("Plan", subscription.plan)
            
            frappe.sendmail(
                recipients=[admin.email],
                subject=_("Subscription Activated - {0}").format(plan.naam),
                message=f"""
                <p>{_("Dear {0}").format(admin.company_name or admin.name)},</p>
                <p>{_("Your {0} subscription has been successfully activated!").format(plan.naam)}</p>
                <p>{_("Subscription will renew automatically on {0}").format(subscription.einddatum)}</p>
                <p>{_("Thank you for your business!")}</p>
                """
            )
        except Exception as e:
            frappe.log_error(f"Error sending activation email: {str(e)}")
    
    def _send_cancellation_email(self, subscription, admin):
        """Send subscription cancellation email"""
        try:
            plan = frappe.get_doc("Plan", subscription.plan)
            
            frappe.sendmail(
                recipients=[admin.email],
                subject=_("Subscription Cancelled - {0}").format(plan.naam),
                message=f"""
                <p>{_("Dear {0}").format(admin.company_name or admin.name)},</p>
                <p>{_("Your {0} subscription has been cancelled.").format(plan.naam)}</p>
                <p>{_("Your subscription will remain active until {0}").format(subscription.einddatum)}</p>
                <p>{_("Thank you for using our services.")}</p>
                """
            )
        except Exception as e:
            frappe.log_error(f"Error sending cancellation email: {str(e)}")


# Convenience functions for API endpoints
@frappe.whitelist()
def create_subscription(administration_name, plan_name, payment_method_name=None):
    """API endpoint to create subscription"""
    service = SubscriptionService()
    return service.create_subscription(administration_name, plan_name, payment_method_name)


@frappe.whitelist()
def get_subscription_status(subscription_name):
    """API endpoint to get subscription status"""
    service = SubscriptionService()
    return service.get_subscription_status(subscription_name)


@frappe.whitelist()
def cancel_subscription(subscription_name):
    """API endpoint to cancel subscription"""
    service = SubscriptionService()
    return service.cancel_subscription(subscription_name)


@frappe.whitelist()
def process_payment_completion(payment_id, payment_status):
    """API endpoint to process payment completion"""
    service = SubscriptionService()
    
    if payment_status == "paid":
        return service.process_first_payment_success(payment_id)
    else:
        return service.handle_payment_failure(payment_id)
