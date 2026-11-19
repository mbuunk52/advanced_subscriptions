"""Endpoints for the app and for Mollie. Every call checks who may manage the administration's billing."""

import frappe
from frappe import _

from advanced_subscriptions.billing import accounts, payments, pricing, subscriptions


@frappe.whitelist(methods=["POST"])
def start_subscription(administration: str, plan: str, period: str = "Month") -> dict:
	accounts.require_manage(administration)
	return subscriptions.start(administration, plan, period)


@frappe.whitelist(methods=["POST"])
def change_plan(administration: str, plan: str, period: str | None = None) -> dict:
	return subscriptions.change_plan(_subscription(administration), plan, period)


@frappe.whitelist()
def quote(administration: str, product: str, quantity: float = 1) -> dict:
	"""The price to show before an action that costs money. Any member of the administration may ask."""
	accounts.require_member(administration)
	return pricing.quote(administration, product, quantity)


@frappe.whitelist(methods=["POST"])
def stop_subscription(administration: str) -> dict:
	subscriptions.stop(_subscription(administration))
	return overview(administration)


@frappe.whitelist(methods=["POST"])
def resume_subscription(administration: str) -> dict:
	subscriptions.resume(_subscription(administration))
	return overview(administration)


@frappe.whitelist(methods=["POST"])
def pay_statement(statement: str) -> dict:
	"""Pay an open statement now: on the mandate when there is one, else through a payment page."""
	doc = _statement(statement)
	return {"payment_url": subscriptions.pay(doc), "status": doc.reload().status}


@frappe.whitelist()
def payment_status(statement: str) -> dict:
	"""For the page the customer returns to after paying: ask Mollie, then report."""
	doc = _statement(statement)
	if doc.payment_record:
		payment_id = frappe.db.get_value("Payment Record", doc.payment_record, "mollie_payment_id")
		if payment_id and doc.status != "Paid":
			payments.process(payment_id)
			doc.reload()
	subscription_status = frappe.db.get_value("Subscription", doc.subscription, "status") if doc.subscription else None
	return {"statement": doc.name, "status": doc.status, "total": doc.total, "subscription_status": subscription_status}


@frappe.whitelist()
def overview(administration: str) -> dict:
	accounts.require_member(administration)
	subscription = subscriptions.current(administration)
	mandate = accounts.default_mandate(administration)
	account = frappe.db.get_value("Billing Account", administration, ["billing_status", "open_amount", "overdue_since"], as_dict=True)
	return {
		"can_manage": accounts.can_manage(administration),
		"subscription": subscription
		and {
			"name": subscription.name,
			"plan": subscription.plan,
			"period": subscription.billing_period or "Month",
			"price": pricing.plan_price(frappe.get_cached_doc("Plan", subscription.plan), subscription.billing_period or "Month"),
			"pending_plan": subscription.pending_plan,
			"pending_period": subscription.pending_period,
			"status": subscription.status,
			"start": subscription.startdatum,
			"period_end": subscription.einddatum,
			"auto_renew": subscription.auto_renew,
		},
		"customer_type": pricing.customer_type(administration),
		"prices_include_vat": pricing.includes_vat(pricing.customer_type(administration)),
		"usage": [
			pricing.rate(administration, code)
			for code in frappe.get_all("Billing Product", filters={"is_active": 1}, pluck="name", order_by="title asc")
		],
		"mandate": mandate and {"method": mandate.method, "label": mandate.label},
		"billing_status": (account and account.billing_status) or "Current",
		"open_amount": (account and account.open_amount) or 0,
		"overdue_since": account and account.overdue_since,
		"statements": frappe.get_all(
			"Billing Statement",
			filters={"administration": administration, "status": ["!=", "Draft"]},
			fields=["name", "status", "issue_date", "collect_on", "paid_on", "total", "invoice_number", "invoice_pdf"],
			order_by="creation desc",
			limit=24,
		),
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def mollie_webhook() -> str:
	"""Mollie posts only an id. The payment is read back from Mollie with our own key, and only an id
	this site created does anything, so the call needs no secret."""
	payment_id = frappe.form_dict.get("id")
	if isinstance(payment_id, str) and payment_id.startswith("tr_") and len(payment_id) < 40:
		try:
			payments.process(payment_id)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: webhook failed", message=payment_id)
			frappe.local.response.http_status_code = 500  # Mollie retries
	return "OK"


def _subscription(administration: str):
	accounts.require_manage(administration)
	subscription = subscriptions.current(administration)
	if not subscription:
		frappe.throw(_("This administration has no subscription."))
	return subscription


def _statement(name: str):
	administration = frappe.db.get_value("Billing Statement", name, "administration")
	if not administration:
		frappe.throw(_("Statement not found."), frappe.DoesNotExistError)
	accounts.require_manage(administration)
	return frappe.get_doc("Billing Statement", name)
