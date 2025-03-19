# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, add_months, add_days, getdate

class Subscription(Document):
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
    
    def handle_plan_change(self):
        # Get the new plan
        new_plan = frappe.get_doc("Plan", self.plan)
        
        # Update end date based on new plan period
        if new_plan.periode == "Month":
            self.einddatum = add_months(self.startdatum, 1)
        elif new_plan.periode == "Year":
            self.einddatum = add_months(self.startdatum, 12)
        
        # You might want to add payment processing logic here
        
    def on_update(self):
        # Check if subscription is about to expire
        if self.status == "Active" and getdate(self.einddatum) <= getdate(add_days(today(), 7)):
            # Send notification about expiring subscription
            self.send_expiry_notification()
    
    def send_expiry_notification(self):
        # Logic to send notification about expiring subscription
        pass

# Standalone functions for scheduled tasks
def check_expiring_subscriptions():
    """Check for subscriptions that are about to expire and send notifications"""
    from frappe.utils import add_days, today, getdate
    
    # Get subscriptions that expire in the next 7 days
    expiring_subscriptions = frappe.get_all("Subscription", 
        filters={
            "status": "Active",
            "einddatum": ["between", today(), add_days(today(), 7)]
        },
        fields=["name", "administratie", "plan", "einddatum"]
    )
    
    for subscription in expiring_subscriptions:
        # Send notification
        frappe.sendmail(
            recipients=frappe.get_value("Administratie", subscription.administratie, "email"),
            subject=f"Your subscription is about to expire",
            message=f"""
            <p>Dear customer,</p>
            <p>Your subscription to the {subscription.plan} plan will expire on {subscription.einddatum}.</p>
            <p>Please renew your subscription to continue using our services.</p>
            <p>Thank you for your business!</p>
            """
        )

def process_renewals():
    """Process subscription renewals"""
    from frappe.utils import add_months, today, getdate
    
    # Get subscriptions that expired in the last month but are still active
    # (assuming auto-renewal is enabled)
    expired_subscriptions = frappe.get_all("Subscription", 
        filters={
            "status": "Active",
            "einddatum": ["<", today()]
        },
        fields=["name", "administratie", "plan", "startdatum", "einddatum"]
    )
    
    for subscription_data in expired_subscriptions:
        subscription = frappe.get_doc("Subscription", subscription_data.name)
        plan = frappe.get_doc("Plan", subscription.plan)
        
        # Renew the subscription
        if plan.periode == "Month":
            subscription.einddatum = add_months(subscription.einddatum, 1)
        elif plan.periode == "Year":
            subscription.einddatum = add_months(subscription.einddatum, 12)
        
        subscription.save()
        
        # Send notification
        frappe.sendmail(
            recipients=frappe.get_value("Administratie", subscription.administratie, "email"),
            subject=f"Your subscription has been renewed",
            message=f"""
            <p>Dear customer,</p>
            <p>Your subscription to the {subscription.plan} plan has been renewed until {subscription.einddatum}.</p>
            <p>Thank you for your continued business!</p>
            """
        )