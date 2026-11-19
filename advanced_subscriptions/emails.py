"""Subscription and payment e-mails, in the LegalFyx house style.

Every place that mails a customer goes through one function here. Each mail is sent at most once per
document and moment (a payment, a period), because several code paths react to the same event: the
Payment Record hook and the Mollie webhook both see a payment change.

The templates in templates/emails/subscription_*.html use the building blocks of thelegalportal
(templates/emails/legalfyx/macros.html), so this app needs thelegalportal installed.
"""

import frappe
from frappe import _
from frappe.utils import format_date, getdate

SENT_KEY_TTL = 60 * 60 * 24 * 40  # longer than a billing period, shorter than forever
SUBSCRIPTION_URL = "/tlp/instellingen/subscription"
FAILED_STATUS = {"Failed": "Failed", "Cancelled": "Cancelled", "Expired": "Expired", "Charged Back": "Charged back"}


def payment_received(payment_record) -> None:
	_send(
		f"payment-paid:{payment_record.name}",
		payment_record.administration,
		_("Payment received: {0} for {1}").format(euro(payment_record.amount), _plan_name(payment_record.plan))
		if payment_record.plan
		else _("Payment received: {0}").format(euro(payment_record.amount)),
		"subscription_payment_received",
		payment=payment_record,
		plan=_plan_name(payment_record.plan),
		amount=euro(payment_record.amount),
		method=payment_record.payment_method,
		paid_on=format_date(payment_record.last_updated or payment_record.creation),
		reference=payment_record.mollie_payment_id or payment_record.name,
	)


def payment_failed(payment_record) -> None:
	_send(
		f"payment-failed:{payment_record.name}",
		payment_record.administration,
		_("Your payment did not go through"),
		"subscription_payment_failed",
		plan=_plan_name(payment_record.plan),
		amount=euro(payment_record.amount),
		status=_(FAILED_STATUS.get(payment_record.status, payment_record.status)),
		active_until=_end_date(payment_record.subscription),
	)


def subscription_activated(subscription) -> None:
	plan = _plan(subscription.plan)
	_send(
		f"subscription-activated:{subscription.name}:{subscription.startdatum}",
		subscription.administration,
		_("Your {0} subscription is active").format(plan.naam),
		"subscription_activated",
		plan=plan.naam,
		price=_price(plan, subscription),
		start=format_date(subscription.startdatum) if subscription.startdatum else None,
		next_payment=format_date(subscription.next_payment_date or subscription.einddatum)
		if (subscription.next_payment_date or subscription.einddatum)
		else None,
		auto_renew=subscription.auto_renew,
	)


def subscription_expiring(subscription) -> None:
	plan = _plan(subscription.plan)
	_send(
		f"subscription-expiring:{subscription.name}:{subscription.einddatum}",
		subscription.administration,
		_("Your subscription ends on {0}").format(format_date(subscription.einddatum)),
		"subscription_expiring",
		plan=plan.naam,
		price=_price(plan, subscription),
		end=format_date(subscription.einddatum),
		days=(getdate(subscription.einddatum) - getdate()).days,
		auto_renew=subscription.auto_renew,
	)


def subscription_renewed(subscription) -> None:
	plan = _plan(subscription.plan)
	_send(
		f"subscription-renewed:{subscription.name}:{subscription.einddatum}",
		subscription.administration,
		_("Your subscription has been renewed until {0}").format(format_date(subscription.einddatum)),
		"subscription_renewed",
		plan=plan.naam,
		price=_price(plan, subscription),
		end=format_date(subscription.einddatum),
	)


def subscription_cancelled(subscription) -> None:
	plan = _plan(subscription.plan)
	_send(
		f"subscription-cancelled:{subscription.name}",
		subscription.administration,
		_("Your subscription has been cancelled"),
		"subscription_cancelled",
		plan=plan.naam,
		end=format_date(subscription.einddatum) if subscription.einddatum else None,
	)


def statement_issued(statement, has_mandate: bool) -> None:
	"""The announcement of a collection, or the request to pay when there is no mandate."""
	_send(
		f"statement-issued:{statement.name}:{int(has_mandate)}",
		statement.administration,
		_("Your LegalFyx statement of {0}").format(euro(statement.total)),
		"billing_statement_issued",
		statement=statement,
		amount=euro(statement.total),
		net=euro(statement.net_total),
		vat=euro(statement.vat_total),
		lines=[(row.description, euro(row.amount)) for row in statement.lines],
		collect_on=format_date(statement.collect_on) if statement.collect_on else None,
		has_mandate=has_mandate,
		pay_url=statement.checkout_url,
	)


def arrears(administration: str, status: str, amount) -> None:
	"""One mail per step of the arrears ladder."""
	subjects = {
		"Reminded": _("Reminder: {0} is still open"),
		"Restricted": _("Paid functions are paused: {0} is still open"),
		"Read Only": _("Your account is read-only: {0} is still open"),
		"Collection": _("Your arrears of {0} are handed over for collection"),
	}
	if status not in subjects:
		return
	_send(
		f"arrears:{administration}:{status}:{getdate().strftime('%Y-%m')}",
		administration,
		subjects[status].format(euro(amount)),
		"billing_arrears",
		status=status,
		amount=euro(amount),
	)


# Helpers


def euro(amount) -> str:
	"""Dutch notation: € 1.234,56"""
	text = f"{float(amount or 0):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
	return f"€ {text}"


def recipients_for(administration: str | None) -> list[str]:
	"""The administration's e-mail address, else its manager's."""
	if not administration:
		return []
	row = frappe.db.get_value("Administration", administration, ["email", "user"], as_dict=True)
	if not row:
		return []
	email = row.email or (row.user and frappe.db.get_value("User", row.user, "email"))
	return [email] if email else []


def _send(key: str, administration: str | None, subject: str, template: str, **context) -> None:
	recipients = recipients_for(administration)
	if not recipients:
		return
	cache_key = f"advanced_subscriptions:mail:{key}"
	if frappe.cache.get_value(cache_key, expires=True):
		return
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			message=frappe.render_template(f"templates/emails/{template}.html", {**context, "manage_url": SUBSCRIPTION_URL}),
		)
		frappe.cache.set_value(cache_key, 1, expires_in_sec=SENT_KEY_TTL)
	except Exception:
		frappe.log_error(title=f"Subscription e-mail not sent: {template}")


def _plan(plan: str | None):
	if plan and frappe.db.exists("Plan", plan):
		return frappe.get_cached_doc("Plan", plan)
	return frappe._dict(naam=plan or "", prijs=0, periode=None)


def _plan_name(plan: str | None) -> str:
	return _plan(plan).naam or plan or ""


def _price(plan, subscription=None) -> str | None:
	yearly = subscription is not None and subscription.get("billing_period") == "Year"
	amount = plan.get("yearly_price") if yearly else plan.prijs
	if not amount:
		return None
	return f"{euro(amount)} {_('per year') if yearly else _('per month')}"


def _end_date(subscription: str | None) -> str | None:
	end = subscription and frappe.db.get_value("Subscription", subscription, "einddatum")
	return format_date(end) if end else None
