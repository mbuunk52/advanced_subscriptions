"""Billing statements: what an administration owes for one moment of billing."""

import frappe
from frappe.utils import add_days, flt, today

from advanced_subscriptions.billing.accounts import settings


def amounts(unit_price, quantity, vat_rate, include_vat: bool) -> tuple[float, float, float]:
	"""(net, vat, gross) of a line whose price is given including or excluding VAT."""
	rate = flt(vat_rate) / 100
	base = flt(unit_price) * flt(quantity or 1)
	if include_vat:
		gross = flt(base, 2)
		net = flt(gross / (1 + rate), 2)
	else:
		net = flt(base, 2)
		gross = flt(net * (1 + rate), 2)
	return net, flt(gross - net, 2), gross


def line(description: str, unit_price, *, include_vat: bool, vat_rate=None, kind="Subscription", plan=None, period_start=None, period_end=None, quantity=1) -> dict:
	vat_rate = flt(settings().vat_rate if vat_rate is None else vat_rate)
	net, vat, gross = amounts(unit_price, quantity, vat_rate, include_vat)
	return {
		"description": description,
		"kind": kind,
		"plan": plan,
		"period_start": period_start,
		"period_end": period_end,
		"quantity": quantity,
		"unit_price": flt(unit_price, 2),
		"price_includes_vat": 1 if include_vat else 0,
		"vat_rate": vat_rate,
		"net_amount": net,
		"vat_amount": vat,
		"amount": gross,
	}


def issue(administration: str, lines: list[dict], *, subscription: str | None = None, collect_on=None):
	"""An issued statement. `collect_on` defaults to the configured number of days after today."""
	statement = frappe.new_doc("Billing Statement")
	statement.update(
		{
			"administration": administration,
			"subscription": subscription,
			"status": "Issued",
			"issue_date": today(),
			"collect_on": collect_on or add_days(today(), settings().collection_delay_days or 0),
		}
	)
	for row in lines:
		statement.append("lines", row)
	statement.insert(ignore_permissions=True)
	return statement


def set_status(statement, status: str, **values) -> None:
	statement.update({"status": status, **values})
	statement.save(ignore_permissions=True)
