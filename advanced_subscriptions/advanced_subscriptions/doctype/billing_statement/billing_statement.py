import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class BillingStatement(Document):
	def validate(self):
		self.net_total = flt(sum(flt(row.net_amount) for row in self.lines), 2)
		self.vat_total = flt(sum(flt(row.vat_amount) for row in self.lines), 2)
		self.total = flt(sum(flt(row.amount) for row in self.lines), 2)
		if not self.is_new() and self.get_doc_before_save().status in ("Paid", "Collecting"):
			if self.has_value_changed("total"):
				frappe.throw(_("A statement that is being collected or has been paid cannot change."))

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Only a draft statement can be deleted. Cancel it instead."))
