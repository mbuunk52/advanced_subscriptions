# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now


class PaymentRecord(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        administration: DF.Link | None
        amount: DF.Currency
        created_at: DF.Datetime | None
        currency: DF.Link
        description: DF.Text | None
        last_updated: DF.Datetime | None
        mollie_payment_data: DF.JSON | None
        mollie_payment_id: DF.Data | None
        payment_method: DF.Data | None
        plan: DF.Link | None
        status: DF.Literal["Pending", "Paid", "Failed", "Cancelled", "Expired", "Authorized", "Unknown"]
        subscription: DF.Link | None
        webhook_logs: DF.LongText | None
    # end: auto-generated types

    def before_insert(self):
        if not self.created_at:
            self.created_at = now()
        self.last_updated = now()
    
    def before_save(self):
        self.last_updated = now()
        
        # Auto-populate subscription details if subscription is set
        if self.subscription and not self.administration:
            subscription = frappe.get_doc("Subscription", self.subscription)
            self.administration = subscription.administration
            self.plan = subscription.plan
    
    def on_update(self):
        # Send notifications on status change
        if self.has_value_changed("status"):
            self.send_status_notification()
    
    def send_status_notification(self):
        """Send notification when payment status changes"""
        if self.status == "Paid":
            self.send_payment_success_notification()
        elif self.status in ["Failed", "Cancelled", "Expired"]:
            self.send_payment_failure_notification()
    
    def send_payment_success_notification(self):
        """Send payment success notification"""
        if self.administration:
            admin = frappe.get_doc("Administration", self.administration)
            frappe.sendmail(
                recipients=[admin.email],
                subject=f"Payment Confirmation - €{self.amount}",
                message=f"""
                <p>Dear {admin.company_name or admin.name},</p>
                <p>Your payment of €{self.amount} has been successfully processed.</p>
                <p>Payment ID: {self.name}</p>
                <p>Thank you for your business!</p>
                """
            )
    
    def send_payment_failure_notification(self):
        """Send payment failure notification"""
        if self.administration:
            admin = frappe.get_doc("Administration", self.administration)
            frappe.sendmail(
                recipients=[admin.email],
                subject=f"Payment Failed - €{self.amount}",
                message=f"""
                <p>Dear {admin.company_name or admin.name},</p>
                <p>Unfortunately, your payment of €{self.amount} has failed.</p>
                <p>Payment ID: {self.name}</p>
                <p>Please try again or contact support for assistance.</p>
                """
            )
