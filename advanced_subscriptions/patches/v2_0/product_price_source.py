import frappe


def execute():
	"""Products made before the field existed take their price from the rates."""
	frappe.db.sql("update `tabBilling Product` set price_source='Rates' where ifnull(price_source, '')=''")
