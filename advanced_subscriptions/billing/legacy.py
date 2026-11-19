"""Subscriptions that were started on Mollie's Subscriptions API.

Until one is taken over, Mollie keeps charging it and the daily run leaves it alone, so nobody is charged
twice. Taking over stops the Mollie subscription and continues on the same mandate. Run per site, by hand:

	bench --site <site> execute advanced_subscriptions.billing.legacy.take_over_all
"""

import frappe

from advanced_subscriptions.billing import accounts, mollie


def take_over(subscription_name: str) -> str:
	subscription = frappe.get_doc("Subscription", subscription_name)
	if not subscription.mollie_subscription_id:
		return "nothing to do"
	customer_id = subscription.mollie_customer_id or accounts.ensure_customer(subscription.administration)
	path = f"/customers/{customer_id}/subscriptions/{subscription.mollie_subscription_id}"
	try:
		data = mollie.request("GET", path)
		if data.get("status") in ("active", "pending", "suspended"):
			mollie.request("DELETE", path)
	except mollie.MollieError as error:
		if error.status_code not in (404, 410):
			raise
		data = {}
	account = accounts.get_account(subscription.administration)
	if not account.mollie_customer_id:
		account.db_set("mollie_customer_id", customer_id)
	mandate_id = data.get("mandateId") or subscription.mollie_mandate_id
	if mandate_id:
		accounts.record_mandate(subscription.administration, customer_id, {"mandateId": mandate_id})
	values = {"mollie_subscription_id": None}
	if data.get("nextPaymentDate") and subscription.status == "Active":
		values["einddatum"] = data["nextPaymentDate"]
	subscription.db_set(values)
	return "taken over"


def take_over_all() -> dict:
	result = {}
	for name in frappe.get_all("Subscription", filters={"mollie_subscription_id": ["is", "set"]}, pluck="name"):
		try:
			result[name] = take_over(name)
			frappe.db.commit()
		except Exception as error:
			frappe.db.rollback()
			result[name] = f"failed: {error}"
	return result
