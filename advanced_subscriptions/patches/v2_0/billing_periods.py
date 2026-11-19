import frappe


def execute():
	"""A plan used to be monthly or yearly; now a plan has both prices and the subscription says which."""
	for plan in frappe.get_all("Plan", fields=["name", "prijs", "periode", "yearly_price"]):
		if plan.periode == "Year" and not plan.yearly_price:
			frappe.db.set_value("Plan", plan.name, {"yearly_price": plan.prijs, "prijs": 0}, update_modified=False)
	for row in frappe.db.sql(
		"""select s.name, p.periode from `tabSubscription` s join `tabPlan` p on p.name = s.plan
		where ifnull(s.billing_period, '') = '' or p.periode = 'Year'""",
		as_dict=True,
	):
		frappe.db.set_value("Subscription", row.name, "billing_period", row.periode or "Month", update_modified=False)
