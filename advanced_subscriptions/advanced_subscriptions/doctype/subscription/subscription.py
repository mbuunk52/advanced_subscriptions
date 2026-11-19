import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, today

MONTHS = {"Month": 1, "Year": 12}


class Subscription(Document):
	"""One subscription of an administration. Starting, renewing, changing plan and stopping go through
	advanced_subscriptions.billing.subscriptions; this controller only keeps the record consistent."""

	def validate(self):
		if not self.startdatum:
			self.startdatum = today()
		if not self.einddatum:
			self.einddatum = add_months(self.startdatum, MONTHS.get(self.billing_period, 1))
		self.next_payment_date = self.einddatum if self.auto_renew and self.status == "Active" else None
		if self.status in ("Active", "Pending"):
			other = frappe.db.exists(
				"Subscription",
				{"administration": self.administration, "status": ["in", ("Active", "Pending")], "name": ["!=", self.name]},
			)
			if other:
				frappe.throw(_("Administration {0} already has subscription {1}.").format(self.administration, other))

	def send_expiry_notification(self):
		from advanced_subscriptions import emails

		emails.subscription_expiring(self)


def check_expiring_subscriptions():
	"""Daily: tell customers whose subscription stops within a week (it was cancelled, so it does not renew)."""
	for name in frappe.get_all(
		"Subscription",
		filters={"status": "Active", "auto_renew": 0, "einddatum": ["between", [today(), add_days(today(), 7)]]},
		pluck="name",
	):
		frappe.get_doc("Subscription", name).send_expiry_notification()
