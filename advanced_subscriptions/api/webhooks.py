"""Kept only because Mollie still has this webhook address on payments created before the billing rebuild."""

import frappe


@frappe.whitelist(allow_guest=True, methods=["POST"])
def mollie_webhook():
	from advanced_subscriptions.billing import api

	return api.mollie_webhook()
