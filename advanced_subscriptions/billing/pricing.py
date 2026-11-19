"""What something costs for an administration.

Prices live in data, not in code:
- a Plan is for individuals or for businesses. Individuals get prices including VAT, businesses excluding.
- a Plan has a price per month and optionally one per year.
- a Plan's usage rates say, per Billing Product, how many are included per month and what an extra one
  costs; both can differ when the plan is paid per year.
- a product without a rate in the plan (or an administration without a plan) costs the product's own
  standard price for that kind of customer.
"""

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from advanced_subscriptions.billing import statements

BLOCKED = ("Restricted", "Read Only", "Collection")


def customer_type(administration: str) -> str:
	"""Individual or Business. The host app may decide through the hook `billing_customer_type`."""
	hooks = frappe.get_hooks("billing_customer_type")
	if hooks:
		return frappe.get_attr(hooks[-1])(administration) or "Business"
	if frappe.get_meta("Administration").has_field("profile_type"):
		if frappe.db.get_value("Administration", administration, "profile_type") == "Individual":
			return "Individual"
	return "Business"


def includes_vat(kind: str) -> bool:
	return kind == "Individual"


def plan_price(plan, period: str) -> float:
	if period == "Year":
		if flt(plan.yearly_price) <= 0 and flt(plan.prijs) > 0:
			frappe.throw(_("Plan {0} cannot be paid per year.").format(plan.naam))
		return flt(plan.yearly_price)
	return flt(plan.prijs)


def active_subscription(administration: str):
	return frappe.db.get_value(
		"Subscription",
		{"administration": administration, "status": "Active"},
		["name", "plan", "billing_period", "startdatum"],
		as_dict=True,
	)


def usage_window(administration: str, day=None) -> tuple:
	"""The month in which included usage counts, anchored on the day the subscription started
	(or the billing account was made)."""
	day = getdate(day or today())
	subscription = active_subscription(administration)
	anchor = getdate(
		(subscription and subscription.startdatum)
		or frappe.db.get_value("Billing Account", administration, "creation")
		or day
	)
	months = (day.year - anchor.year) * 12 + day.month - anchor.month
	start = getdate(add_months(anchor, months))
	if start > day:
		months -= 1
		start = getdate(add_months(anchor, months))
	return start, getdate(add_months(anchor, months + 1))


def rate(administration: str, product_code: str) -> dict:
	"""Unit price, what is included this month and what is left of it."""
	product = frappe.get_cached_doc("Billing Product", product_code)
	if not product.is_active:
		frappe.throw(_("{0} is not available.").format(product.title))
	kind = customer_type(administration)
	subscription = active_subscription(administration)
	unit_price = flt(product.price_individual if kind == "Individual" else product.price_business)
	include_vat, included, source = includes_vat(kind), 0, "standard"
	if subscription:
		plan = frappe.get_cached_doc("Plan", subscription.plan)
		row = next((r for r in plan.usage_rates if r.product == product.name), None)
		if row:
			yearly = subscription.billing_period == "Year"
			unit_price = flt(row.price_yearly) if yearly and flt(row.price_yearly) > 0 else flt(row.price)
			included = (row.included_yearly if yearly and row.included_yearly else row.included) or 0
			include_vat, source = includes_vat(plan.customer_type), "plan"
	start, end = usage_window(administration)
	used = flt(
		frappe.db.sql(
			"""select sum(included_quantity) from `tabBilling Charge`
			where administration=%s and product=%s and status!='Cancelled' and usage_date>=%s and usage_date<%s""",
			(administration, product.name, start, end),
		)[0][0]
	)
	return {
		"product": product.name,
		"title": product.title,
		"unit": product.unit,
		"unit_price": unit_price,
		"price_includes_vat": include_vat,
		"vat_rate": flt(product.vat_rate),
		"included": included,
		"used": used,
		"remaining": max(included - used, 0),
		"resets_on": end,
		"source": source,
	}


def quote(administration: str, product_code: str, quantity=1) -> dict:
	"""What `quantity` of a product would cost now. Nothing is recorded."""
	quantity = flt(quantity)
	if quantity <= 0:
		frappe.throw(_("The quantity must be more than zero."))
	info = rate(administration, product_code)
	free = min(info["remaining"], quantity)
	billable = quantity - free
	net, vat, total = statements.amounts(info["unit_price"], billable, info["vat_rate"], info["price_includes_vat"]) if billable else (0, 0, 0)
	status = frappe.db.get_value("Billing Account", administration, "billing_status") or "Current"
	return {
		**info,
		"quantity": quantity,
		"included_quantity": free,
		"billable_quantity": billable,
		"net_amount": net,
		"vat_amount": vat,
		"amount": total,
		"blocked": bool(billable and status in BLOCKED),
	}


class PriceChanged(frappe.ValidationError):
	"""The price is higher than what the user confirmed."""


class Blocked(frappe.ValidationError):
	"""The user cannot spend this now: overdue payments, a limit, no permission or no payment method."""


def quote_many(administration: str, items: list[tuple[str, float]]) -> dict:
	"""One action that consists of several products (a letter plus colour printing): the lines and the total."""
	from advanced_subscriptions.billing import limits

	lines = [quote(administration, code, quantity) for code, quantity in items]
	amount = flt(sum(row["amount"] for row in lines), 2)
	# Overdue payments come first; then whether this user may spend this much
	reason = "arrears" if any(row["blocked"] for row in lines) else limits.block_reason(administration, frappe.session.user, amount, usage_window(administration))
	values = limits.of_administration(administration)
	collect_now = amount > values["collect_now_above"] > 0 or (amount > 0 and limits.open_usage_amount(administration) + amount > values["spending_limit"] > 0)
	return {
		"lines": lines,
		"net_amount": flt(sum(row["net_amount"] for row in lines), 2),
		"vat_amount": flt(sum(row["vat_amount"] for row in lines), 2),
		"amount": amount,
		"price_includes_vat": lines[0]["price_includes_vat"] if lines else False,
		"blocked": bool(reason),
		"block_reason": reason,
		"needs_confirmation": amount >= values["no_confirm_below"],
		"collect_now": bool(collect_now and not reason),
		"billed_on": next_statement_date(administration),
	}


BLOCK_MESSAGES = {
	"arrears": "This costs money and there are payments overdue. Pay the open amount first.",
	"not_allowed": "You are not allowed to order things that cost money for this administration.",
	"user_limit": "This goes over your spending limit for this month. Ask an administrator of the administration.",
	"payment_method": "This costs money and there is no payment method yet. Add one under Settings › Subscription.",
}


def next_statement_date(administration: str):
	"""When usage of today lands on a statement: the renewal of a monthly plan, else the end of the usage month."""
	subscription = active_subscription(administration)
	if subscription and (subscription.billing_period or "Month") == "Month":
		return frappe.db.get_value("Subscription", subscription.name, "einddatum")
	return usage_window(administration)[1]


def charge_many(administration: str, items: list[tuple[str, float]], *, idempotency_key: str, reference=None, expected_amount=None, allow_when_blocked=False) -> list:
	"""Charge the products of one action together. `expected_amount` is what the user saw and confirmed:
	when the real total is higher (a colleague just used the last included item), nothing is charged."""
	keys = {code: f"{idempotency_key}:{code}" for code, _quantity in items}
	if all(frappe.db.exists("Billing Charge", {"idempotency_key": key}) for key in keys.values()):
		return [frappe.get_doc("Billing Charge", {"idempotency_key": key}) for key in keys.values()]
	price = quote_many(administration, items)
	total = price["amount"]
	if price["block_reason"] and not allow_when_blocked:
		frappe.throw(_(BLOCK_MESSAGES[price["block_reason"]]), Blocked)
	if expected_amount is not None and total > flt(expected_amount) + 0.005:
		frappe.throw(_("The price has changed to {0}. Check the costs and confirm again.").format(frappe.format_value(total, {"fieldtype": "Currency", "options": "EUR"})), PriceChanged)
	charges = [
		charge(administration, code, quantity, idempotency_key=keys[code], reference=reference, allow_when_blocked=True)
		for code, quantity in items
	]
	_collect_early(administration, [doc.name for doc in charges], total)
	return charges


def _collect_early(administration: str, charges: list[str], amount: float) -> None:
	"""A large single purchase is collected at once, and so is all open usage once it passes the limit of
	the administration. Without a mandate, or when collecting fails, it waits for the next statement."""
	from advanced_subscriptions.billing import limits, subscriptions
	from advanced_subscriptions.billing.accounts import default_mandate

	if amount <= 0 or not default_mandate(administration):
		return
	values = limits.of_administration(administration)
	if amount > values["collect_now_above"] > 0:
		only = charges
	elif limits.open_usage_amount(administration) > values["spending_limit"] > 0:
		only = None
	else:
		return
	try:
		frappe.db.savepoint("billing_collect_early")
		subscriptions.bill_usage_now(administration, only)
	except Exception:
		frappe.db.rollback(save_point="billing_collect_early")
		frappe.log_error(title="Billing: early collection failed", message=administration)


def cancel_charges(key_prefix: str) -> int:
	"""Undo the usage of an action that failed after all. Charges that are already on a statement stay;
	those need a credit."""
	names = frappe.get_all("Billing Charge", filters={"idempotency_key": ["like", f"{key_prefix}:%"], "status": "Open"}, pluck="name")
	if names:
		frappe.db.set_value("Billing Charge", {"name": ["in", names]}, "status", "Cancelled")
	billed = frappe.db.count("Billing Charge", {"idempotency_key": ["like", f"{key_prefix}:%"], "status": "Billed", "amount": [">", 0]})
	if billed:
		frappe.log_error(title="Billing: failed action was already billed, credit needed", message=key_prefix)
	return len(names)


def charge(administration: str, product_code: str, quantity=1, *, idempotency_key: str, reference=None, description: str | None = None, allow_when_blocked=False):
	"""Record usage. The same key gives the same charge back, so a retried action is charged once.
	With payments overdue, anything that costs money is refused, unless the caller finishes something
	that was already running (`allow_when_blocked`)."""
	existing = frappe.db.get_value("Billing Charge", {"idempotency_key": idempotency_key}, "name")
	if existing:
		return frappe.get_doc("Billing Charge", existing)
	price = quote(administration, product_code, quantity)
	if price["blocked"] and not allow_when_blocked:
		frappe.throw(_(BLOCK_MESSAGES["arrears"]), Blocked)
	doc = frappe.new_doc("Billing Charge")
	doc.update(
		{
			"administration": administration,
			"product": price["product"],
			"description": description or price["title"],
			"usage_date": today(),
			"user": frappe.session.user,
			"status": "Open",
			"idempotency_key": idempotency_key,
			"reference_doctype": reference.doctype if reference else None,
			"reference_name": reference.name if reference else None,
			"quantity": price["quantity"],
			"included_quantity": price["included_quantity"],
			"unit_price": price["unit_price"],
			"price_includes_vat": 1 if price["price_includes_vat"] else 0,
			"vat_rate": price["vat_rate"],
			"net_amount": price["net_amount"],
			"vat_amount": price["vat_amount"],
			"amount": price["amount"],
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def cancel_charge(idempotency_key: str) -> None:
	"""Undo usage that did not happen after all (a letter that could not be sent). Not once it is billed."""
	name = frappe.db.get_value("Billing Charge", {"idempotency_key": idempotency_key, "status": "Open"}, "name")
	if name:
		frappe.db.set_value("Billing Charge", name, "status", "Cancelled")


def open_usage(administration: str, before=None, only: list[str] | None = None) -> tuple[list[dict], list[str]]:
	"""Statement lines for unbilled usage, grouped per product and price: everything dated before `before`,
	or just the charges in `only`."""
	filters = {"administration": administration, "status": "Open"}
	if only is not None:
		filters["name"] = ["in", only]
	elif before:
		filters["usage_date"] = ["<", before]
	charges = frappe.get_all(
		"Billing Charge",
		filters=filters,
		fields=["name", "product", "quantity", "included_quantity", "unit_price", "price_includes_vat", "vat_rate", "amount"],
		order_by="usage_date asc",
	)
	groups: dict[tuple, float] = {}
	for row in charges:
		billable = flt(row.quantity) - flt(row.included_quantity)
		if billable > 0:
			key = (row.product, flt(row.unit_price), row.price_includes_vat, flt(row.vat_rate))
			groups[key] = groups.get(key, 0) + billable
	lines = [
		statements.line(
			frappe.get_cached_value("Billing Product", product, "title"),
			unit_price,
			include_vat=bool(include_vat),
			vat_rate=vat_rate,
			quantity=quantity,
			kind="Usage",
		)
		for (product, unit_price, include_vat, vat_rate), quantity in groups.items()
	]
	return lines, [row.name for row in charges]


def mark_billed(charges: list[str], statement: str | None) -> None:
	if charges:
		frappe.db.set_value("Billing Charge", {"name": ["in", charges]}, {"status": "Billed", "billing_statement": statement})
