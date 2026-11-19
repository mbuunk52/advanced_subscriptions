"""The life of a subscription: start, renew on its own billing day, change plan, stop.

Mollie's Subscriptions API is not used. Each period gets a Billing Statement, collected on the mandate
of the administration; later phases add usage and purchases to the same statement.
"""

import frappe
from frappe import _
from frappe.utils import add_months, date_diff, flt, format_date, getdate, today

from advanced_subscriptions import emails
from advanced_subscriptions.billing import arrears, payments, pricing, statements
from advanced_subscriptions.billing.accounts import default_mandate

MONTHS = {"Month": 1, "Year": 12}


def period_end(start, period: str) -> str:
	return add_months(start, MONTHS.get(period, 1))


def period_line(plan, period: str, start, end, kind="Subscription", price=None) -> dict:
	per = _("per year") if period == "Year" else _("per month")
	description = _("{0} subscription {1}, {2} until {3}").format(plan.naam, per, format_date(start), format_date(end))
	return statements.line(
		description,
		pricing.plan_price(plan, period) if price is None else price,
		include_vat=pricing.includes_vat(plan.customer_type),
		kind=kind,
		plan=plan.name,
		period_start=start,
		period_end=end,
	)


def current(administration: str):
	name = frappe.db.get_value(
		"Subscription", {"administration": administration, "status": ["in", ("Active", "Pending")]}, "name", order_by="creation desc"
	)
	return frappe.get_doc("Subscription", name) if name else None


def start(administration: str, plan_name: str, period: str = "Month") -> dict:
	"""Start a subscription. A free plan is active at once; a paid one after the first payment."""
	plan = frappe.get_doc("Plan", plan_name)
	period = period if period in MONTHS else "Month"
	if not plan.is_active:
		frappe.throw(_("This plan is not available."))
	if plan.customer_type != pricing.customer_type(administration):
		frappe.throw(_("Plan {0} is not meant for this kind of administration.").format(plan.naam))
	price = pricing.plan_price(plan, period)
	existing = current(administration)
	if existing and existing.status == "Active":
		frappe.throw(_("This administration already has an active subscription. Change the plan instead."))
	if existing:
		_drop_pending(existing)

	subscription = frappe.new_doc("Subscription")
	subscription.update(
		{
			"administration": administration,
			"plan": plan.name,
			"billing_period": period,
			"status": "Pending",
			"auto_renew": 1,
			"startdatum": today(),
			"einddatum": period_end(today(), period),
		}
	)
	subscription.insert(ignore_permissions=True)
	if price <= 0:
		_activate(subscription)
		return {"subscription": subscription.name, "status": "Active", "payment_url": None}

	statement = statements.issue(
		administration,
		[period_line(plan, period, subscription.startdatum, subscription.einddatum)],
		subscription=subscription.name,
		collect_on=today(),
	)
	return {"subscription": subscription.name, "status": "Pending", "statement": statement.name, "payment_url": pay(statement)}


def pay(statement) -> str | None:
	"""Collect on the mandate when there is one (returns None), else a checkout link."""
	if default_mandate(statement.administration) and payments.collect(statement):
		return None
	return payments.start_checkout(statement)


def _drop_pending(subscription) -> None:
	for name in frappe.get_all("Billing Statement", filters={"subscription": subscription.name, "status": ["in", ("Issued", "Failed")]}, pluck="name"):
		statements.set_status(frappe.get_doc("Billing Statement", name), "Cancelled", checkout_url=None)
	subscription.status = "Cancelled"
	subscription.save(ignore_permissions=True)


def _activate(subscription) -> None:
	subscription.status = "Active"
	subscription.save(ignore_permissions=True)
	emails.subscription_activated(subscription)


def on_statement_paid(statement) -> None:
	if not statement.subscription:
		return
	subscription = frappe.get_doc("Subscription", statement.subscription)
	if subscription.status == "Pending":
		_activate(subscription)


def _only(filters: dict, administration: str | None) -> dict:
	"""The daily steps take every administration; a test or a support action can name one."""
	return {**filters, "administration": administration} if administration else filters


def renew_due(administration: str | None = None) -> None:
	"""Runs daily. On the day a period ends: stop, or issue the statement for the next period."""
	for name in frappe.get_all("Subscription", filters=_only({"status": "Active", "einddatum": ["<=", today()]}, administration), pluck="name"):
		try:
			renew(frappe.get_doc("Subscription", name))
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: renewal failed", message=name)


def renew(subscription) -> None:
	if subscription.mollie_subscription_id:
		# still billed by Mollie's own subscription; see billing/legacy.py
		return
	if not subscription.auto_renew:
		subscription.status = "Expired"
		subscription.save(ignore_permissions=True)
		return
	if subscription.pending_plan:
		subscription.plan = subscription.pending_plan
		subscription.billing_period = subscription.pending_period or subscription.billing_period
		subscription.pending_plan = subscription.pending_period = None
	plan = frappe.get_doc("Plan", subscription.plan)
	period = subscription.billing_period or "Month"
	start_date = subscription.einddatum
	subscription.einddatum = period_end(start_date, period)
	subscription.save(ignore_permissions=True)
	lines, charges = pricing.open_usage(subscription.administration, today())
	if pricing.plan_price(plan, period) > 0:
		lines.insert(0, period_line(plan, period, start_date, subscription.einddatum))
	_issue_with_usage(subscription.administration, lines, charges, subscription.name)
	emails.subscription_renewed(subscription)


def _issue_with_usage(administration: str, lines: list, charges: list, subscription: str | None) -> None:
	statement = None
	if lines:
		statement = statements.issue(administration, lines, subscription=subscription)
		emails.statement_issued(statement, has_mandate=bool(default_mandate(administration)))
	pricing.mark_billed(charges, statement and statement.name)


def bill_usage_now(administration: str, only: list[str] | None = None) -> None:
	"""Put open usage (all of it, or the given charges) on a statement and collect it on the mandate now."""
	lines, charges = pricing.open_usage(administration, only=only)
	if not lines:
		return
	subscription = pricing.active_subscription(administration)
	statement = statements.issue(administration, lines, subscription=subscription and subscription.name, collect_on=today())
	pricing.mark_billed(charges, statement.name)
	payments.collect(statement)


def bill_usage_due(only: str | None = None) -> None:
	"""Runs daily, after the renewals. Usage of a finished month that no renewal picked up (a yearly or
	free plan, or no plan at all) gets its own statement."""
	for administration in set(frappe.get_all("Billing Charge", filters=_only({"status": "Open"}, only), pluck="administration")):
		try:
			window_start, _end = pricing.usage_window(administration)
			lines, charges = pricing.open_usage(administration, window_start)
			if charges:
				subscription = pricing.active_subscription(administration)
				_issue_with_usage(administration, lines, charges, subscription and subscription.name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: usage statement failed", message=administration)


def collect_due(administration: str | None = None) -> None:
	"""Runs daily. Collect issued statements whose collection date has come; one retry of a failed debit."""
	conf = statements.settings()
	pending = set(frappe.get_all("Subscription", filters={"status": "Pending"}, pluck="name"))
	due = frappe.get_all(
		"Billing Statement",
		filters=_only({"status": "Issued", "collect_on": ["<=", today()], "total": [">", 0]}, administration),
		fields=["name", "subscription"],
	)
	retry_before = frappe.utils.add_days(today(), -(conf.retry_after_days or 5))
	retry = frappe.get_all(
		"Billing Statement",
		filters=_only({"status": "Failed", "attempts": ["<", 2], "last_attempt_on": ["<=", retry_before], "total": [">", 0]}, administration),
		fields=["name", "subscription"],
	)
	for row in due + retry:
		if row.subscription in pending:
			continue
		try:
			statement = frappe.get_doc("Billing Statement", row.name)
			if not payments.collect(statement) and not statement.checkout_url:
				payments.start_checkout(statement)
				emails.statement_issued(statement, has_mandate=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Billing: collection failed", message=row.name)


def change_plan(subscription, plan_name: str, period: str | None = None) -> dict:
	"""A more expensive plan with the same payment period starts now, with the difference for the rest of
	the period on a statement; so does any paid plan when coming from a free one. Everything else (a cheaper
	plan, switching between monthly and yearly) takes effect when the current period ends."""
	if subscription.status != "Active":
		frappe.throw(_("Only an active subscription can change plan."))
	new = frappe.get_doc("Plan", plan_name)
	old = frappe.get_doc("Plan", subscription.plan)
	old_period = subscription.billing_period or "Month"
	period = period if period in MONTHS else old_period
	if not new.is_active:
		frappe.throw(_("This plan is not available."))
	if new.customer_type != pricing.customer_type(subscription.administration):
		frappe.throw(_("Plan {0} is not meant for this kind of administration.").format(new.naam))
	new_price, old_price = pricing.plan_price(new, period), pricing.plan_price(old, old_period)
	if new.name == old.name and period == old_period:
		subscription.pending_plan = subscription.pending_period = None
		subscription.save(ignore_permissions=True)
		return {"effective": "now", "payment_url": None}

	from_free = old_price <= 0 and new_price > 0
	upgrade = from_free or (period == old_period and new_price > old_price)
	if not upgrade:
		subscription.pending_plan, subscription.pending_period = new.name, period
		subscription.save(ignore_permissions=True)
		return {"effective": str(subscription.einddatum), "payment_url": None}

	if from_free:
		# a fresh period starts today
		subscription.startdatum = today()
		subscription.einddatum = period_end(today(), period)
		row = period_line(new, period, today(), subscription.einddatum)
	else:
		period_start = add_months(subscription.einddatum, -MONTHS[period])
		total_days = max(date_diff(subscription.einddatum, period_start), 1)
		left = min(max(date_diff(subscription.einddatum, today()), 0), total_days)
		difference = flt((new_price - old_price) * left / total_days, 2)
		row = period_line(new, period, today(), subscription.einddatum, kind="Proration", price=difference)
	subscription.update({"plan": new.name, "billing_period": period, "pending_plan": None, "pending_period": None, "auto_renew": 1})
	subscription.save(ignore_permissions=True)
	payment_url = None
	if flt(row["amount"]) > 0:
		statement = statements.issue(subscription.administration, [row], subscription=subscription.name, collect_on=today())
		payment_url = pay(statement)
	return {"effective": "now", "payment_url": payment_url}


def stop(subscription) -> None:
	"""Stop at the end of the paid period. A subscription that never started is dropped at once."""
	if subscription.status == "Pending":
		_drop_pending(subscription)
	else:
		subscription.auto_renew = 0
		subscription.pending_plan = subscription.pending_period = None
		subscription.save(ignore_permissions=True)
	emails.subscription_cancelled(subscription)


def resume(subscription) -> None:
	if subscription.status != "Active":
		frappe.throw(_("This subscription has ended. Start a new one."))
	subscription.auto_renew = 1
	subscription.save(ignore_permissions=True)


def daily() -> None:
	payments.sync_open()
	payments.sync_recent_paid()
	renew_due()
	bill_usage_due()
	collect_due()
	arrears.update_all()
	frappe.db.commit()
