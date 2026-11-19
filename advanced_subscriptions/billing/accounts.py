"""Billing account, Mollie customer and mandate of an administration."""

import frappe
from frappe import _

from advanced_subscriptions.billing import mollie


DEFAULTS = {
	"collection_delay_days": 4,
	"retry_after_days": 5,
	"vat_rate": 21,
	"reminder_after_days": 7,
	"restrict_after_days": 14,
	"read_only_after_days": 30,
	"collection_after_days": 45,
}


def settings():
	"""Billing Settings, with the defaults for values that were never saved."""
	saved = frappe.db.get_singles_dict("Billing Settings", cast=True)
	return frappe._dict({key: saved[key] if saved.get(key) is not None else default for key, default in DEFAULTS.items()})


def can_manage(administration: str, user: str | None = None) -> bool:
	"""Who may order and pay for an administration. The host app decides through the hook
	`billing_can_manage`; without one, whoever may write the Administration."""
	user = user or frappe.session.user
	if user == "Administrator" or "LegalFyx Finance" in frappe.get_roles(user):
		return True
	hooks = frappe.get_hooks("billing_can_manage")
	if hooks:
		return bool(frappe.get_attr(hooks[-1])(administration, user))
	return bool(frappe.has_permission("Administration", "write", administration, user=user))


def require_member(administration: str) -> None:
	"""Anyone in the administration may look; only who manages it may order and pay."""
	if not administration:
		frappe.throw(_("Administration is required."), frappe.MandatoryError)
	if not can_manage(administration) and not frappe.has_permission("Administration", "read", administration):
		frappe.throw(_("You have no access to this administration."), frappe.PermissionError)


def require_manage(administration: str) -> None:
	if not administration:
		frappe.throw(_("Administration is required."), frappe.MandatoryError)
	if not can_manage(administration):
		frappe.throw(_("You are not allowed to manage the billing of this administration."), frappe.PermissionError)


def get_account(administration: str):
	if frappe.db.exists("Billing Account", administration):
		return frappe.get_doc("Billing Account", administration)
	account = frappe.new_doc("Billing Account")
	account.administration = administration
	account.insert(ignore_permissions=True)
	return account


def ensure_customer(administration: str) -> str:
	"""The Mollie customer of the administration, created on first use."""
	account = get_account(administration)
	if _valid(account.mollie_customer_id):
		return account.mollie_customer_id
	row = frappe.db.get_value("Administration", administration, "*", as_dict=True) or {}
	customer_id = row.get("mollie_customer_id")
	if not _valid(customer_id):
		customer = mollie.create_customer(row.get("company_name") or administration, row.get("email"), administration)
		customer_id = customer["id"]
		if "mollie_customer_id" in row:
			frappe.db.set_value("Administration", administration, "mollie_customer_id", customer_id, update_modified=False)
	account.db_set("mollie_customer_id", customer_id)
	return customer_id


def _valid(customer_id) -> bool:
	return isinstance(customer_id, str) and customer_id.startswith("cst_") and len(customer_id) > 4


def default_mandate(administration: str):
	name = frappe.db.get_value(
		"Payment Mandate",
		{"administration": administration, "status": "Valid"},
		"name",
		order_by="is_default desc, creation desc",
	)
	return frappe.get_doc("Payment Mandate", name) if name else None


def record_mandate(administration: str, customer_id: str, payment: dict) -> None:
	"""Store the mandate a paid first payment created; it becomes the default."""
	mandate_id = payment.get("mandateId")
	if not mandate_id:
		return
	try:
		data = mollie.get_mandate(customer_id, mandate_id)
	except mollie.MollieError:
		frappe.log_error(title="Billing: mandate could not be read", message=f"{administration} {mandate_id}")
		return
	status = {"valid": "Valid", "pending": "Valid", "invalid": "Invalid"}.get(data.get("status"), "Pending")
	details = data.get("details") or {}
	account_number = details.get("consumerAccount") or details.get("cardNumber") or ""
	label = f"•••• {account_number[-4:]}" if account_number else ""
	name = frappe.db.get_value("Payment Mandate", {"mollie_mandate_id": mandate_id}, "name")
	doc = frappe.get_doc("Payment Mandate", name) if name else frappe.new_doc("Payment Mandate")
	doc.update(
		{
			"administration": administration,
			"mollie_mandate_id": mandate_id,
			"status": status,
			"method": data.get("method"),
			"label": label,
			"first_payment": doc.first_payment or payment.get("id"),
			"is_default": 1 if status == "Valid" else 0,
		}
	)
	doc.save(ignore_permissions=True)
	if status == "Valid":
		frappe.db.set_value(
			"Payment Mandate",
			{"administration": administration, "name": ["!=", doc.name], "is_default": 1},
			"is_default",
			0,
		)
