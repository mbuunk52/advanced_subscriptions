"""Payments on a statement: the checkout that creates a mandate, the collection on the mandate,
and what a status change at Mollie means for the statement."""

import json

import frappe
from frappe import _
from frappe.utils import flt, get_url, today

from advanced_subscriptions.billing import accounts, arrears, mollie
from advanced_subscriptions.billing.statements import set_status

IN_PROGRESS = ("Open", "Pending", "Authorized")
NOT_PAID = ("Failed", "Cancelled", "Expired")


def start_checkout(statement) -> str:
	"""A first payment for the statement: the customer pays in Mollie's checkout and that gives the mandate."""
	_check_collectable(statement)
	payment = _create(statement, "first", redirect_url=get_url(f"/tlp/payment-result?statement={statement.name}"))
	url = mollie.checkout_url(payment)
	if not url:
		frappe.throw(_("Mollie returned no payment page. Try again."))
	statement.db_set("checkout_url", url)
	return url


def collect(statement) -> bool:
	"""Collect the statement on the default mandate. False when there is no valid mandate."""
	_check_collectable(statement)
	mandate = accounts.default_mandate(statement.administration)
	if not mandate:
		return False
	_create(statement, "recurring", mandate_id=mandate.mollie_mandate_id)
	return True


def _check_collectable(statement) -> None:
	if statement.status in ("Paid", "Cancelled", "Draft") or flt(statement.total) <= 0:
		frappe.throw(_("Statement {0} has nothing to collect.").format(statement.name))
	if frappe.db.exists("Payment Record", {"billing_statement": statement.name, "status": ["in", ("Pending", "Authorized")]}):
		frappe.throw(_("A payment for statement {0} is already being processed.").format(statement.name))


def _create(statement, sequence_type: str, *, redirect_url=None, mandate_id=None) -> dict:
	customer_id = accounts.ensure_customer(statement.administration)
	record = frappe.new_doc("Payment Record")
	record.update(
		{
			"amount": statement.total,
			"currency": "EUR",
			"status": "Open",
			"description": _("LegalFyx statement {0}").format(statement.name),
			"billing_statement": statement.name,
			"subscription": statement.subscription,
			"administration": statement.administration,
			"plan": statement.lines[0].plan if statement.lines else None,
			"sequence_type": sequence_type,
		}
	)
	record.insert(ignore_permissions=True)
	try:
		payment = mollie.create_payment(
			amount=statement.total,
			description=record.description,
			customer_id=customer_id,
			sequence_type=sequence_type,
			metadata={"payment_record": record.name, "statement": statement.name, "administration": statement.administration},
			idempotency_key=f"{frappe.local.site}:{record.name}",
			redirect_url=redirect_url,
			mandate_id=mandate_id,
		)
	except Exception:
		record.delete(ignore_permissions=True)
		raise
	record.db_set({"mollie_payment_id": payment["id"], "payment_method": payment.get("method")})
	statement.update(
		{
			"payment_record": record.name,
			"attempts": (statement.attempts or 0) + 1,
			"last_attempt_on": today(),
			"status": "Collecting" if sequence_type == "recurring" else statement.status,
		}
	)
	statement.save(ignore_permissions=True)
	if payment.get("status") not in (None, "open", "pending"):
		process(payment["id"], payment)
	elif sequence_type == "recurring":
		arrears.update(statement.administration)  # a statement that is being collected is no longer overdue
	return payment


def process(payment_id: str, payment: dict | None = None) -> str | None:
	"""Bring a payment in line with Mollie. Only payments this site created are processed: an id without
	a Payment Record, or one whose metadata points elsewhere, is ignored."""
	name = frappe.db.get_value("Payment Record", {"mollie_payment_id": payment_id}, "name", for_update=True)
	if not name:
		return None
	payment = payment or mollie.get_payment(payment_id)
	record = frappe.get_doc("Payment Record", name)
	owner = (payment.get("metadata") or {}).get("payment_record")
	if record.billing_statement and owner != record.name:
		frappe.log_error(title="Billing: payment does not belong to its record", message=f"{payment_id} {record.name} {owner}")
		return None

	status = mollie.STATUS.get(payment.get("status"), "Unknown")
	charged_back = mollie.value(payment.get("amountChargedBack"))
	if status == "Paid" and charged_back > 0:
		status = "Charged Back"
	previous = record.status
	record.update(
		{
			"status": status,
			"payment_method": payment.get("method") or record.payment_method,
			"amount_charged_back": charged_back,
			"amount_refunded": mollie.value(payment.get("amountRefunded")),
			"mollie_payment_data": json.dumps(payment, default=str),
		}
	)
	record.save(ignore_permissions=True)
	if status != previous and record.billing_statement:
		_apply(record, payment)
	return status


def _apply(record, payment: dict) -> None:
	statement = frappe.get_doc("Billing Statement", record.billing_statement)
	if record.status == "Paid":
		set_status(statement, "Paid", paid_on=today(), checkout_url=None)
		accounts.record_mandate(statement.administration, payment.get("customerId") or accounts.ensure_customer(statement.administration), payment)
		from advanced_subscriptions.billing import subscriptions

		subscriptions.on_statement_paid(statement)
	elif record.status == "Charged Back":
		set_status(statement, "Charged Back", paid_on=None)
	elif record.status in NOT_PAID and statement.status not in ("Paid", "Cancelled"):
		# an abandoned checkout leaves the statement as it was: issued and still to pay
		set_status(statement, "Failed" if record.sequence_type == "recurring" or record.status == "Failed" else "Issued")
	arrears.update(statement.administration)


def sync_open() -> None:
	"""Ask Mollie about payments that are still open; covers a missed webhook and sites without one."""
	for payment_id in frappe.get_all(
		"Payment Record",
		filters={"status": ["in", IN_PROGRESS], "billing_statement": ["is", "set"], "mollie_payment_id": ["is", "set"]},
		pluck="mollie_payment_id",
	):
		try:
			process(payment_id)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: payment sync failed", message=payment_id)


def sync_recent_paid(days: int = 70) -> None:
	"""Direct debits can be charged back for eight weeks; look at paid ones again in case a webhook was missed."""
	since = frappe.utils.add_days(today(), -days)
	for payment_id in frappe.get_all(
		"Payment Record",
		filters={"status": "Paid", "billing_statement": ["is", "set"], "payment_method": "directdebit", "creation": [">=", since]},
		pluck="mollie_payment_id",
	):
		try:
			process(payment_id)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: chargeback check failed", message=payment_id)
