"""Endpoints for the app and for Mollie. Every call checks who may manage the administration's billing."""

import frappe
from frappe import _

from advanced_subscriptions.billing import accounts, limits, payments, pricing, statements, subscriptions


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


@frappe.whitelist(methods=["POST"])
def add_payment_method(administration: str) -> dict:
	"""Record a payment method without a subscription: a payment of one cent through Mollie's payment page
	gives the mandate that later usage is collected on."""
	accounts.require_manage(administration)
	open_one = frappe.db.get_value(
		"Billing Statement", {"administration": administration, "status": "Issued", "total": 0.01, "subscription": ["is", "not set"]}, "name"
	)
	statement = (
		frappe.get_doc("Billing Statement", open_one)
		if open_one
		else statements.issue(
			administration,
			[statements.line(_("Recording your payment method"), 0.01, include_vat=True, kind="Usage")],
			collect_on=frappe.utils.today(),
		)
	)
	return {"payment_url": payments.start_checkout(statement), "statement": statement.name}


@frappe.whitelist()
def get_limits(administration: str) -> dict:
	"""The spending limits of the administration and of each member, with what they spent this month."""
	accounts.require_manage(administration)
	window = pricing.usage_window(administration)
	members = []
	for method in frappe.get_hooks("billing_members")[-1:]:
		members = frappe.get_attr(method)(administration) or []
	for member in members:
		row = limits.user_row(administration, member["user"])
		member.update(
			{
				"may_order": bool(row.may_order) if row else True,
				"month_limit": (row and row.month_limit) or 0,
				"can_spend": limits.may_spend(administration, member["user"]),
				"spent": limits.spent_by(administration, member["user"], *window),
			}
		)
	own = frappe.db.get_value("Billing Account", administration, ["user_month_limit", "no_confirm_below"], as_dict=True) or {}
	return {
		"effective": limits.of_administration(administration),
		"user_month_limit": own.get("user_month_limit") or 0,
		"no_confirm_below": own.get("no_confirm_below") or 0,
		"members": members,
	}


@frappe.whitelist(methods=["POST"])
def set_limits(administration: str, user_month_limit: float = 0, no_confirm_below: float = 0, members: list | str | None = None) -> dict:
	"""What the administration decides itself. The limit on open usage and the threshold for collecting
	at once bound what LegalFyx is owed, so only LegalFyx changes those."""
	accounts.require_manage(administration)
	members = frappe.parse_json(members) or []
	if frappe.utils.flt(user_month_limit) < 0 or frappe.utils.flt(no_confirm_below) < 0 or any(frappe.utils.flt(m.get("month_limit")) < 0 for m in members):
		frappe.throw(_("A limit cannot be negative."))
	known = {m["user"] for method in frappe.get_hooks("billing_members")[-1:] for m in (frappe.get_attr(method)(administration) or [])}
	account = accounts.get_account(administration)
	account.user_month_limit = frappe.utils.flt(user_month_limit)
	account.no_confirm_below = frappe.utils.flt(no_confirm_below)
	account.set("user_limits", [])
	for member in members:
		if member.get("user") in known and (not member.get("may_order", True) or frappe.utils.flt(member.get("month_limit")) > 0):
			account.append("user_limits", {"user": member["user"], "may_order": 1 if member.get("may_order", True) else 0, "month_limit": frappe.utils.flt(member.get("month_limit"))})
	account.save(ignore_permissions=True)
	return get_limits(administration)


@frappe.whitelist()
def usage_log(administration: str, limit: int = 50) -> list[dict]:
	"""Who used what and when, newest first."""
	accounts.require_member(administration)
	rows = frappe.get_all(
		"Billing Charge",
		filters={"administration": administration, "status": ["!=", "Cancelled"]},
		fields=["name", "usage_date", "product", "description", "quantity", "included_quantity", "amount", "price_includes_vat", "user", "status", "billing_statement", "reference_doctype", "reference_name"],
		order_by="creation desc",
		limit=min(int(limit or 50), 200),
	)
	for row in rows:
		row["user_name"] = frappe.db.get_value("User", row.user, "full_name") if row.user else None
	return rows


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
