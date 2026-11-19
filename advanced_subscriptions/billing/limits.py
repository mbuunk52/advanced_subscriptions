"""Who may spend how much. Values exist on three levels and the most specific one that is set wins:
the user's row on the Billing Account, the Billing Account of the administration, Billing Settings."""

import frappe
from frappe.utils import flt

from advanced_subscriptions.billing.accounts import can_manage, default_mandate, settings

ADMINISTRATION_FIELDS = ("spending_limit", "collect_now_above", "user_month_limit", "no_confirm_below")


def of_administration(administration: str) -> dict:
	conf = settings()
	account = frappe.db.get_value("Billing Account", administration, list(ADMINISTRATION_FIELDS), as_dict=True) or {}
	return {field: flt(account.get(field)) or flt(conf.get(field)) for field in ADMINISTRATION_FIELDS}


def user_row(administration: str, user: str) -> dict | None:
	rows = frappe.get_all(
		"Billing User Limit",
		filters={"parent": administration, "parenttype": "Billing Account", "user": user},
		fields=["may_order", "month_limit"],
		limit=1,
	)
	return rows[0] if rows else None


def may_spend(administration: str, user: str) -> bool:
	"""The host app says who may spend at all (hook `billing_can_spend`); the administration can switch a
	user off."""
	row = user_row(administration, user)
	if row and not row.may_order:
		return False
	hooks = frappe.get_hooks("billing_can_spend")
	if hooks:
		return bool(frappe.get_attr(hooks[-1])(administration, user))
	return can_manage(administration, user)


def for_user(administration: str, user: str) -> dict:
	values = of_administration(administration)
	row = user_row(administration, user)
	if row and flt(row.month_limit) > 0:
		values["user_month_limit"] = flt(row.month_limit)
	values["may_order"] = may_spend(administration, user)
	return values


def spent_by(administration: str, user: str, start, end) -> float:
	return flt(
		frappe.db.sql(
			"""select sum(amount) from `tabBilling Charge`
			where administration=%s and user=%s and status!='Cancelled' and usage_date>=%s and usage_date<%s""",
			(administration, user, start, end),
		)[0][0]
	)


def open_usage_amount(administration: str) -> float:
	return flt(frappe.db.sql("select sum(amount) from `tabBilling Charge` where administration=%s and status='Open'", administration)[0][0])


def block_reason(administration: str, user: str, amount: float, window: tuple) -> str | None:
	"""Why this user cannot spend `amount` now, or None. Arrears are checked by the caller."""
	if amount <= 0:
		return None
	values = for_user(administration, user)
	if not values["may_order"]:
		return "not_allowed"
	if values["user_month_limit"] > 0 and spent_by(administration, user, *window) + amount > values["user_month_limit"] + 0.005:
		return "user_limit"
	if not default_mandate(administration):
		return "payment_method"
	return None
