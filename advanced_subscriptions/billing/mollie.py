"""The one place that talks to Mollie for LegalFyx's own billing.

Plain REST calls on the platform's API key (Payment Provider of type Mollie). Tests replace `request`.
"""

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.utils import flt, get_url

API = "https://api.mollie.com/v2"
WEBHOOK_METHOD = "advanced_subscriptions.billing.api.mollie_webhook"

# Mollie's payment status -> Payment Record status
STATUS = {
	"open": "Open",
	"pending": "Pending",
	"authorized": "Authorized",
	"paid": "Paid",
	"failed": "Failed",
	"canceled": "Cancelled",
	"expired": "Expired",
}


def api_key() -> str:
	name = frappe.db.get_value("Payment Provider", {"provider_type": "Mollie", "is_active": 1}, "name")
	if not name:
		frappe.throw(_("No active Mollie payment provider is set up."))
	provider = frappe.get_cached_doc("Payment Provider", name)
	field = "live_api_key" if provider.api_mode == "live" else "test_api_key"
	key = provider.get_password(field, raise_exception=False)
	if not key:
		frappe.throw(_("The Mollie payment provider has no API key for {0} mode.").format(provider.api_mode))
	return key


def request(method: str, path: str, *, json: dict | None = None, params: dict | None = None, idempotency_key: str | None = None) -> dict:
	import requests

	headers = {"Authorization": f"Bearer {api_key()}"}
	if idempotency_key:
		headers["Idempotency-Key"] = idempotency_key
	response = requests.request(method, f"{API}{path}", headers=headers, json=json, params=params, timeout=20)
	if response.status_code >= 400:
		detail = ""
		try:
			detail = response.json().get("detail") or ""
		except ValueError:
			pass
		raise MollieError(detail or str(response.status_code), response.status_code)
	return response.json() if response.content else {}


class MollieError(Exception):
	def __init__(self, message: str, status_code: int = 0):
		super().__init__(message)
		self.status_code = status_code


def money(amount) -> dict:
	return {"currency": "EUR", "value": f"{flt(amount):.2f}"}


def value(amount: dict | None) -> float:
	return flt((amount or {}).get("value"))


def webhook_url() -> str | None:
	"""Mollie refuses a webhook it cannot reach, so a local site gets none and polls instead."""
	url = get_url(f"/api/method/{WEBHOOK_METHOD}")
	host = urlparse(url).hostname or ""
	if host in ("localhost", "127.0.0.1") or host.endswith((".localhost", ".test")):
		return None
	return url


def create_customer(name: str, email: str | None, administration: str) -> dict:
	body = {"name": name, "metadata": {"administration": administration}}
	if email:
		body["email"] = email
	return request("POST", "/customers", json=body)


def create_payment(
	*,
	amount,
	description: str,
	customer_id: str,
	sequence_type: str,
	metadata: dict,
	idempotency_key: str,
	redirect_url: str | None = None,
	mandate_id: str | None = None,
) -> dict:
	body = {
		"amount": money(amount),
		"description": description[:255],
		"customerId": customer_id,
		"sequenceType": sequence_type,
		"metadata": metadata,
	}
	if redirect_url:
		body["redirectUrl"] = redirect_url
	if mandate_id:
		body["mandateId"] = mandate_id
	if hook := webhook_url():
		body["webhookUrl"] = hook
	return request("POST", "/payments", json=body, idempotency_key=idempotency_key)


def get_payment(payment_id: str) -> dict:
	return request("GET", f"/payments/{payment_id}", params={"embed": "chargebacks,refunds"})


def get_mandate(customer_id: str, mandate_id: str) -> dict:
	return request("GET", f"/customers/{customer_id}/mandates/{mandate_id}")


def checkout_url(payment: dict) -> str | None:
	return ((payment.get("_links") or {}).get("checkout") or {}).get("href")
