# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
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
        einddatum: DF.Date | None
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
        """Create Mollie customer and subscription after inserting"""
        if self.betalingsmethode:
            payment_method = frappe.get_doc("Payment Method", self.betalingsmethode)
            if payment_method.payment_provider:
                provider = frappe.get_doc("Payment Provider", payment_method.payment_provider)
                if provider.provider_type == "Mollie":
                    self.create_mollie_subscription()
    
    def handle_plan_change(self):
        # Get the new plan
        new_plan = frappe.get_doc("Plan", self.plan)
        
        # Update end date based on new plan period
        if new_plan.periode == "Month":
            self.einddatum = add_months(self.startdatum, 1)
        elif new_plan.periode == "Year":
            self.einddatum = add_months(self.startdatum, 12)
        
        # Update Mollie subscription if exists
        if self.mollie_subscription_id:
            self.update_mollie_subscription()
    
    def create_mollie_subscription(self):
        """Create subscription in Mollie"""
        try:
            from advanced_subscriptions.integrations.mollie_api import create_mollie_subscription
            result = create_mollie_subscription(self.name)
            
            if result.get("success"):
                self.mollie_subscription_id = result.get("mollie_subscription_id")
                self.db_set("mollie_subscription_id", self.mollie_subscription_id, commit=True)
            else:
                frappe.log_error(f"Failed to create Mollie subscription: {result.get('message')}")
        
        except Exception as e:
            frappe.log_error(f"Error creating Mollie subscription: {str(e)}")
    
    def update_mollie_subscription(self):
        """Update subscription in Mollie"""
        try:
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
            if self.mollie_subscription_id and self.mollie_customer_id:
                from advanced_subscriptions.integrations.mollie_api import MollieAPI
                
                mollie = MollieAPI()
                mollie.cancel_subscription(
                    customer_id=self.mollie_customer_id,
                    subscription_id=self.mollie_subscription_id
                )
        
        except Exception as e:
            frappe.log_error(f"Error cancelling Mollie subscription: {str(e)}")
    
    def on_update(self):
        # Check if subscription is about to expire
        if self.status == "Active" and getdate(self.einddatum) <= getdate(add_days(today(), 7)):
            # Send notification about expiring subscription
            self.send_expiry_notification()
            self.update_mollie_subscription()
        
        # Handle status changes
        if self.has_value_changed("status"):
            if self.status == "Cancelled":
                self.cancel_mollie_subscription()
    
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