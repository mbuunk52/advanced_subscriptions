"""Kept only because Mollie still has this webhook address on payments created before the billing rebuild."""

import frappe


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook_handler():
	from advanced_subscriptions.billing.api import mollie_webhook

	return mollie_webhook()
