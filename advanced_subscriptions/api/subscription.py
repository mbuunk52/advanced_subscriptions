import frappe
from frappe.utils import flt


@frappe.whitelist(allow_guest=True)
def get_plans_with_features(customer_type: str | None = None):
	"""Active plans with features, prices and usage rates, cheapest first. Public: the pricing page shows
	them. `customer_type` (Individual or Business) narrows the list."""
	filters = {"is_active": 1}
	if customer_type in ("Individual", "Business"):
		filters["customer_type"] = customer_type
	plans = frappe.get_all(
		"Plan",
		filters=filters,
		fields=["name", "naam", "beschrijving", "prijs", "yearly_price", "customer_type"],
		order_by="prijs asc",
	)
	for plan in plans:
		plan["periode"] = "Month"  # older screens read this
		plan["prices_include_vat"] = plan.customer_type == "Individual"
		plan["yearly_saving"] = max(flt(plan.prijs) * 12 - flt(plan.yearly_price), 0) if flt(plan.yearly_price) > 0 else 0
		plan["features"] = frappe.get_all(
			"Plan Feature", filters={"parent": plan.name, "parenttype": "Plan"}, fields=["name", "feature"], order_by="idx asc"
		)
		plan["usage_rates"] = [
			row | {"title": frappe.get_cached_value("Billing Product", row.product, "title"), "unit": frappe.get_cached_value("Billing Product", row.product, "unit")}
			for row in frappe.get_all(
				"Plan Usage Rate",
				filters={"parent": plan.name, "parenttype": "Plan"},
				fields=["product", "included", "price", "included_yearly", "price_yearly"],
				order_by="idx asc",
			)
		]
	return plans
