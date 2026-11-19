"""Arrears per administration as a whole: every unpaid statement counts, whatever it is for."""

import frappe
from frappe.utils import date_diff, flt, getdate, today

from advanced_subscriptions.billing.accounts import get_account, settings

OPEN = ("Issued", "Failed", "Charged Back")


def overdue_statements(administration: str) -> list[dict]:
	"""Unpaid statements past their collection date. A statement that is being collected is not overdue,
	and neither is the first statement of a subscription that never started."""
	rows = frappe.get_all(
		"Billing Statement",
		filters={"administration": administration, "status": ["in", OPEN], "total": [">", 0]},
		fields=["name", "status", "collect_on", "total", "subscription"],
	)
	pending = set(
		frappe.get_all("Subscription", filters={"administration": administration, "status": "Pending"}, pluck="name")
	)
	now = getdate(today())
	return [
		row
		for row in rows
		if row.subscription not in pending and (row.status != "Issued" or getdate(row.collect_on) < now)
	]


def stage(days: int) -> str:
	conf = settings()
	steps = [
		(conf.collection_after_days, "Collection"),
		(conf.read_only_after_days, "Read Only"),
		(conf.restrict_after_days, "Restricted"),
		(conf.reminder_after_days, "Reminded"),
	]
	for threshold, name in steps:
		if threshold and days >= threshold:
			return name
	return "Past Due"


def update(administration: str) -> str:
	"""Recompute the billing status. Paying everything brings it back to Current at once."""
	account = get_account(administration)
	overdue = overdue_statements(administration)
	if overdue:
		since = min(getdate(row.collect_on) for row in overdue)
		status = stage(date_diff(today(), since))
		if account.exempt_until and getdate(account.exempt_until) >= getdate(today()):
			status = "Current"
	else:
		since, status = None, "Current"
	previous = account.billing_status
	account.db_set(
		{"billing_status": status, "overdue_since": since, "open_amount": flt(sum(row.total for row in overdue), 2)}
	)
	if status != previous:
		from advanced_subscriptions import emails

		emails.arrears(administration, status, account.open_amount)
		for method in frappe.get_hooks("billing_status_changed"):
			frappe.get_attr(method)(administration=administration, status=status, previous=previous)
	return status


def update_all() -> None:
	names = set(frappe.get_all("Billing Statement", filters={"status": ["in", OPEN]}, pluck="administration"))
	names |= set(frappe.get_all("Billing Account", filters={"billing_status": ["!=", "Current"]}, pluck="name"))
	for administration in names:
		update(administration)


def status(administration: str) -> str:
	return frappe.db.get_value("Billing Account", administration, "billing_status") or "Current"
