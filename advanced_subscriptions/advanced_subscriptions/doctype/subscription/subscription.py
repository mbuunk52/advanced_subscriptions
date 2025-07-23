# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today, add_months, add_days, getdate

class Subscription(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from advanced_subscriptions.advanced_subscriptions.doctype.subscription_pay_as_you_go_item.subscription_pay_as_you_go_item import SubscriptionPayAsYouGoItem
        from frappe.types import DF

        administration: DF.Link
        auto_renew: DF.Check
        betalingsmethode: DF.Link | None
        billing_address: DF.Link | None
        einddatum: DF.Date | None
        first_payment_id: DF.Data | None
        first_payment_url: DF.Data | None
        mollie_customer_id: DF.Data | None
        mollie_mandate_id: DF.Data | None
        mollie_subscription_id: DF.Data | None
        next_payment_date: DF.Date | None
        pay_as_you_go_items: DF.Table[SubscriptionPayAsYouGoItem]
        payment_failure_count: DF.Int
        plan: DF.Link
        startdatum: DF.Date
        status: DF.Literal["Active", "Pending", "Cancelled", "Expired"]
    # end: auto-generated types

    def validate(self):
        # Set start date to today if not provided
        if not self.startdatum:
            self.startdatum = today()
        
        # Set end date based on plan period if not provided
        if not self.einddatum:
            plan = frappe.get_doc("Plan", self.plan)
            if plan.periode == "Month":
                self.einddatum = add_months(self.startdatum, 1)
            elif plan.periode == "Year":
                self.einddatum = add_months(self.startdatum, 12)
    
    def before_save(self):
        # Check if plan has changed
        if self.has_value_changed("plan"):
            # Handle plan change logic here
            self.handle_plan_change()
        
        # Set next payment date
        if self.auto_renew and self.status == "Active":
            plan = frappe.get_doc("Plan", self.plan)
            if plan.periode == "Month":
                self.next_payment_date = add_months(self.startdatum, 1)
            elif plan.periode == "Year":
                self.next_payment_date = add_months(self.startdatum, 12)
    
    def after_insert(self):
        """Setup recurring payment flow after inserting"""
        # The new subscription flow handles payment setup externally
        # No automatic setup needed here anymore
        pass
    
    def setup_mollie_recurring_payments(self):
        """
        DEPRECATED: Use subscription_flow.create_subscription_with_payment instead
        Setup proper Mollie recurring payment flow
        """
        frappe.log_error("Deprecated method called: setup_mollie_recurring_payments", "Deprecated API Usage")
        return {
            "success": False,
            "message": _("This method is deprecated. Use the new subscription flow.")
        }
    
    def handle_plan_change(self):
        # Get the new plan
        new_plan = frappe.get_doc("Plan", self.plan)
        
        # Update end date based on new plan period
        if new_plan.periode == "Month":
            self.einddatum = add_months(self.startdatum, 1)
        elif new_plan.periode == "Year":
            self.einddatum = add_months(self.startdatum, 12)
        
        # Update Mollie subscription only if we have valid IDs
        if self.has_valid_mollie_data():
            self.update_mollie_subscription()
        else:
            frappe.logger().info(f"Skipping Mollie subscription update for plan change - invalid Mollie data")
    
    def create_mollie_subscription(self):
        """Legacy method - now redirects to proper recurring payment setup"""
        return self.setup_mollie_recurring_payments()
    
    def has_valid_mollie_data(self):
        """Check if subscription has valid Mollie customer and subscription IDs"""
        return (
            self.mollie_customer_id 
            and self.mollie_customer_id.startswith('cst_')
            and self.mollie_subscription_id 
            and self.mollie_subscription_id.startswith('sub_')
        )
    
    def update_mollie_subscription(self):
        """Update subscription in Mollie"""
        try:
            # Skip if no valid Mollie subscription exists
            if not self.has_valid_mollie_data():
                frappe.logger().info(f"Skipping Mollie subscription update - invalid Mollie data (customer: {self.mollie_customer_id}, subscription: {self.mollie_subscription_id})")
                return
            
            from advanced_subscriptions.integrations.mollie_api import MollieAPI
            
            mollie = MollieAPI()
            plan = frappe.get_doc("Plan", self.plan)
            admin = frappe.get_doc("Administration", self.administration)
            
            # Update subscription in Mollie
            mollie.update_subscription(
                customer_id=self.mollie_customer_id,
                subscription_id=self.mollie_subscription_id,
                amount=plan.prijs,
                currency="EUR",
                description=f"Subscription to {plan.naam}"
            )
        
        except Exception as e:
            frappe.log_error(f"Error updating Mollie subscription: {str(e)}")
    
    def cancel_mollie_subscription(self):
        """Cancel subscription in Mollie"""
        try:
            if not self.has_valid_mollie_data():
                frappe.logger().info(f"No valid Mollie subscription to cancel for subscription {self.name} (customer: {self.mollie_customer_id}, subscription: {self.mollie_subscription_id})")
                return
                
            from advanced_subscriptions.integrations.mollie_api import MollieAPI
            
            mollie = MollieAPI()
            result = mollie.cancel_subscription(
                customer_id=self.mollie_customer_id,
                subscription_id=self.mollie_subscription_id
            )
            
            if result.get("success"):
                frappe.logger().info(f"Successfully cancelled Mollie subscription {self.mollie_subscription_id}")
                # Clear Mollie subscription ID to prevent further operations
                self.mollie_subscription_id = None
                self.db_update()
            else:
                frappe.log_error(f"Failed to cancel Mollie subscription: {result.get('message')}")
        
        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}")
            # Don't raise exception here to prevent blocking subscription cancellation
    
    def on_update(self):
        # Check if subscription is about to expire
        if self.status == "Active" and getdate(self.einddatum) <= getdate(add_days(today(), 7)):
            # Send notification about expiring subscription
            self.send_expiry_notification()
            # Only update Mollie subscription if we have valid IDs
            if self.has_valid_mollie_data():
                self.update_mollie_subscription()
        
        # Handle status changes
        if self.has_value_changed("status"):
            if self.status == "Cancelled":
                self.cancel_mollie_subscription()
    
    def on_trash(self):
        """Called when subscription is being deleted - cancel Mollie subscription"""
        try:
            if self.has_valid_mollie_data():
                self.cancel_mollie_subscription()
                frappe.logger().info(f"Cancelled Mollie subscription {self.mollie_subscription_id} for deleted subscription {self.name}")
        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription on delete: {str(e)}")
    
    def before_cancel(self):
        """Called before subscription is cancelled - cancel Mollie subscription"""
        try:
            if self.has_valid_mollie_data():
                self.cancel_mollie_subscription()
                frappe.logger().info(f"Cancelled Mollie subscription {self.mollie_subscription_id} for cancelled subscription {self.name}")
        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription on cancel: {str(e)}")
    
    def send_expiry_notification(self):
        """Send notification about expiring subscription"""
        try:
            admin = frappe.get_doc("Administration", self.administration)
            frappe.sendmail(
                recipients=[admin.email],
                subject=f"Subscription Expiring Soon - {self.plan}",
                message=f"""
                <p>Dear {admin.company_name or admin.name},</p>
                <p>Your subscription to {self.plan} will expire on {self.einddatum}.</p>
                <p>Please ensure your payment method is up to date for automatic renewal.</p>
                <p>If you have any questions, please contact support.</p>
                """
            )
        except Exception as e:
            frappe.log_error(f"Error sending expiry notification: {str(e)}")


# Standalone functions for scheduled tasks
def check_expiring_subscriptions():
    """Check for subscriptions that are about to expire and send notifications"""
    from frappe.utils import add_days, today, getdate
    
    # Get subscriptions expiring in the next 7 days
    expiring_subscriptions = frappe.get_all("Subscription", 
        filters={
            "status": "Active",
            "einddatum": ["between", [today(), add_days(today(), 7)]]
        },
        fields=["name", "administration", "plan", "einddatum", "mollie_subscription_id"]
    )
    
    for subscription_data in expiring_subscriptions:
        subscription = frappe.get_doc("Subscription", subscription_data.name)
        subscription.send_expiry_notification()


def process_renewals():
    """Process subscription renewals"""
    from frappe.utils import add_months, today, getdate
    
    # Get subscriptions that expired in the last month but are still active
    # (assuming auto-renewal is enabled)
    expired_subscriptions = frappe.get_all("Subscription", 
        filters={
            "status": "Active",
            "auto_renew": 1,
            "einddatum": ["<", today()]
        },
        fields=["name", "administration", "plan", "startdatum", "einddatum", "mollie_subscription_id"]
    )
    
    for subscription_data in expired_subscriptions:
        subscription = frappe.get_doc("Subscription", subscription_data.name)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        # Check if payment was successful (this should be handled by webhooks)
        recent_payments = frappe.get_all("Payment Record",
            filters={
                "subscription": subscription.name,
                "status": "Paid",
                "created_at": [">=", add_days(today(), -7)]
            })
        
        if recent_payments:
            # Renew the subscription
            if plan.periode == "Month":
                subscription.einddatum = add_months(subscription.einddatum, 1)
            elif plan.periode == "Year":
                subscription.einddatum = add_months(subscription.einddatum, 12)
            
            subscription.payment_failure_count = 0
            subscription.save()
            
            # Send renewal notification
            admin = frappe.get_doc("Administration", subscription.administration)
            frappe.sendmail(
                recipients=[admin.email],
                subject=f"Subscription Renewed - {subscription.plan}",
                message=f"""
                <p>Dear {admin.company_name or admin.name},</p>
                <p>Your subscription to the {subscription.plan} plan has been renewed until {subscription.einddatum}.</p>
                <p>Thank you for your continued business!</p>
                """
            )
        else:
            # Handle payment failure
            subscription.payment_failure_count += 1
            if subscription.payment_failure_count >= 3:
                subscription.status = "Cancelled"
                subscription.cancel_mollie_subscription()
            subscription.save()