"""Billing: statements, collection on the mandate, the webhook, arrears and plan changes.

Mollie is replaced by FakeMollie; nothing leaves the machine.
Run: bench --site tlp-test.localhost run-tests --app advanced_subscriptions --module advanced_subscriptions.tests.test_billing
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, flt, getdate, today
from thelegalportal.tests.utils import make_administration, make_user, unique

from advanced_subscriptions.billing import accounts, api, arrears, payments, pricing, subscriptions


class FakeMollie:
	def __init__(self):
		self.payments = {}
		self.created = []

	def __call__(self, method, path, *, json=None, params=None, idempotency_key=None):
		if method == "POST" and path == "/customers":
			return {"id": f"cst_{frappe.generate_hash(length=10)}"}
		if method == "POST" and path == "/payments":
			first = json["sequenceType"] == "first"
			payment = {
				"id": f"tr_{frappe.generate_hash(length=10)}",
				"status": "open" if first else "pending",
				"amount": json["amount"],
				"metadata": json["metadata"],
				"customerId": json["customerId"],
				"sequenceType": json["sequenceType"],
				"mandateId": json.get("mandateId"),
				"method": None if first else "directdebit",
				"idempotency_key": idempotency_key,
			}
			if first:
				payment["_links"] = {"checkout": {"href": f"https://pay.example/{payment['id']}"}}
			self.payments[payment["id"]] = payment
			self.created.append(payment)
			return dict(payment)
		if method == "GET" and path.startswith("/payments/"):
			return dict(self.payments[path.split("/")[-1]])
		if method == "GET" and "/mandates/" in path:
			return {"id": path.split("/")[-1], "status": "valid", "method": "directdebit", "details": {"consumerAccount": "NL00TEST0123456789"}}
		raise AssertionError(f"unexpected Mollie call {method} {path}")

	def settle(self, payment_id, status="paid", charged_back=0):
		payment = self.payments[payment_id]
		payment["status"] = status
		if status == "paid" and payment["sequenceType"] == "first":
			payment["mandateId"] = f"mdt_{frappe.generate_hash(length=10)}"
			payment["method"] = "ideal"
		if charged_back:
			payment["amountChargedBack"] = {"currency": "EUR", "value": f"{charged_back:.2f}"}
		return payments.process(payment_id)


def make_plan(price, *, yearly=0, kind="Individual", rates=None) -> str:
	plan = frappe.get_doc(
		{
			"doctype": "Plan",
			"naam": unique("Plan"),
			"customer_type": kind,
			"prijs": price,
			"yearly_price": yearly,
			"is_active": 1,
			"features": [{"feature": "Test"}],
			"usage_rates": rates or [],
		}
	).insert(ignore_permissions=True)
	return plan.name


def make_product(individual=2.5, business=2.0) -> str:
	code = f"test.{frappe.generate_hash(length=8)}"
	frappe.get_doc(
		{"doctype": "Billing Product", "code": code, "title": "Brief per post", "unit": "brief", "price_individual": individual, "price_business": business, "vat_rate": 21}
	).insert(ignore_permissions=True)
	return code


def retire_test_products():
	"""Test runs commit; without this the test products would show up in every usage overview."""
	frappe.db.set_value("Billing Product", {"code": ["like", "test.%"]}, "is_active", 0)
	frappe.db.set_value("Plan", {"naam": ["like", "Plan %"], "beschrijving": ["is", "not set"]}, "is_active", 0)


def make_business() -> str:
	administration = make_administration()
	frappe.db.set_value("Administration", administration, "profile_type", "Business")
	return administration


class TestBilling(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.mollie = FakeMollie()
		patcher = patch("advanced_subscriptions.billing.mollie.request", self.mollie)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.administration = make_administration()
		self.plan = make_plan(121)

	def tearDown(self):
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		retire_test_products()
		frappe.db.commit()
		super().tearDownClass()

	# helpers

	def start_paid(self, plan=None):
		"""An active subscription with a mandate, as after a completed first checkout."""
		result = subscriptions.start(self.administration, plan or self.plan)
		self.mollie.settle(self.mine()[-1]["id"])
		return frappe.get_doc("Subscription", result["subscription"])

	def mine(self):
		"""Payments of this test's administration; the daily run also handles what earlier tests left behind."""
		return [p for p in self.mollie.created if p["metadata"]["administration"] == self.administration]

	def freeze_time(self, day):
		# not exactly midnight: Frappe's modified check compares timestamps as text
		return super().freeze_time(f"{getdate(day)} 09:00:00.000001")

	def statements(self, **filters):
		return frappe.get_all(
			"Billing Statement",
			filters={"administration": self.administration, **filters},
			fields=["name", "status", "total", "net_total", "vat_total", "collect_on", "attempts"],
			order_by="creation asc",
		)

	def run_day(self):
		# only this test's administration: test runs commit, and the site may hold other subscriptions
		subscriptions.renew_due(self.administration)
		subscriptions.bill_usage_due(self.administration)
		subscriptions.collect_due(self.administration)
		arrears.update(self.administration)

	# starting

	def test_start_gives_checkout_and_waits_for_payment(self):
		result = subscriptions.start(self.administration, self.plan)
		self.assertEqual(result["status"], "Pending")
		self.assertTrue(result["payment_url"].startswith("https://pay.example/"))
		statement = self.statements()[0]
		self.assertEqual(statement.status, "Issued")
		self.assertEqual((flt(statement.net_total), flt(statement.vat_total), flt(statement.total)), (100.0, 21.0, 121.0))
		payment = self.mine()[-1]
		self.assertEqual(payment["sequenceType"], "first")
		self.assertEqual(payment["amount"]["value"], "121.00")
		self.assertEqual(arrears.update(self.administration), "Current")

	def test_business_plan_is_priced_excluding_vat(self):
		self.administration = make_business()
		subscriptions.start(self.administration, make_plan(121, kind="Business"))
		statement = self.statements()[0]
		self.assertEqual((flt(statement.net_total), flt(statement.vat_total), flt(statement.total)), (121.0, 25.41, 146.41))
		self.assertEqual(self.mine()[-1]["amount"]["value"], "146.41")

	def test_plan_for_the_other_kind_of_customer_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			subscriptions.start(self.administration, make_plan(10, kind="Business"))

	def test_yearly_payment_uses_the_yearly_price(self):
		plan = make_plan(20, yearly=200)
		result = subscriptions.start(self.administration, plan, "Year")
		subscription = frappe.get_doc("Subscription", result["subscription"])
		self.assertEqual(getdate(subscription.einddatum), getdate(add_months(today(), 12)))
		self.assertEqual(flt(self.statements()[0].total), 200.0)
		with self.assertRaises(frappe.ValidationError):
			subscriptions.start(make_administration(), make_plan(20), "Year")  # no yearly price set

	def test_paid_first_payment_activates_and_stores_mandate(self):
		subscription = self.start_paid()
		self.assertEqual(subscription.status, "Active")
		self.assertEqual(self.statements()[0].status, "Paid")
		mandate = accounts.default_mandate(self.administration)
		self.assertEqual((mandate.status, mandate.label), ("Valid", "•••• 6789"))
		# the same webhook again changes nothing
		payment_id = self.mine()[-1]["id"]
		self.assertEqual(payments.process(payment_id), "Paid")
		self.assertEqual(len(frappe.get_all("Payment Mandate", filters={"administration": self.administration})), 1)

	def test_free_plan_is_active_without_payment(self):
		result = subscriptions.start(self.administration, make_plan(0))
		self.assertEqual(result["status"], "Active")
		self.assertIsNone(result["payment_url"])
		self.assertEqual(self.statements(), [])
		self.assertEqual(self.mine(), [])

	def test_abandoned_checkout_can_be_paid_again(self):
		result = subscriptions.start(self.administration, self.plan)
		self.mollie.settle(self.mine()[-1]["id"], "expired")
		self.assertEqual(self.statements()[0].status, "Issued")
		self.assertEqual(frappe.db.get_value("Subscription", result["subscription"], "status"), "Pending")
		self.assertEqual(arrears.update(self.administration), "Current")
		again = api.pay_statement(result["statement"])
		self.assertTrue(again["payment_url"])
		self.mollie.settle(self.mine()[-1]["id"])
		self.assertEqual(frappe.db.get_value("Subscription", result["subscription"], "status"), "Active")

	def test_starting_again_replaces_the_unpaid_attempt(self):
		first = subscriptions.start(self.administration, self.plan)
		second = subscriptions.start(self.administration, make_plan(242))
		self.assertEqual(frappe.db.get_value("Subscription", first["subscription"], "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Billing Statement", first["statement"], "status"), "Cancelled")
		self.assertEqual(frappe.db.get_value("Subscription", second["subscription"], "status"), "Pending")

	# the webhook

	def test_webhook_ignores_payments_it_did_not_create(self):
		self.assertIsNone(payments.process("tr_unknown123"))
		subscriptions.start(self.administration, self.plan)
		payment = self.mine()[-1]
		self.mollie.payments[payment["id"]]["metadata"] = {"payment_record": "PAY-of-someone-else"}
		self.assertIsNone(self.mollie.settle(payment["id"]))
		self.assertEqual(self.statements()[0].status, "Issued")

	# renewing and collecting

	def test_renewal_issues_a_statement_and_collects_on_the_mandate(self):
		subscription = self.start_paid()
		period_end = getdate(subscription.einddatum)
		with self.freeze_time(period_end):
			self.run_day()
			self.run_day()  # a second run the same day must not bill twice
			subscription.reload()
			self.assertEqual(getdate(subscription.einddatum), getdate(add_months(period_end, 1)))
			rows = self.statements()
			self.assertEqual([row.status for row in rows], ["Paid", "Issued"])
			self.assertEqual(getdate(rows[1].collect_on), getdate(add_days(period_end, 4)))
			self.assertEqual(len(self.mine()), 1)
		with self.freeze_time(add_days(period_end, 4)):
			self.run_day()
			self.run_day()
			payment = self.mine()[-1]
			self.assertEqual(len(self.mine()), 2)
			self.assertEqual(payment["sequenceType"], "recurring")
			self.assertEqual(payment["mandateId"], accounts.default_mandate(self.administration).mollie_mandate_id)
			self.assertEqual(self.statements()[1].status, "Collecting")
			self.assertEqual(arrears.status(self.administration), "Current")
			self.mollie.settle(payment["id"])
			self.assertEqual(self.statements()[1].status, "Paid")

	def test_failed_debit_is_retried_once(self):
		subscription = self.start_paid()
		day = getdate(add_days(subscription.einddatum, 4))
		with self.freeze_time(subscription.einddatum):
			self.run_day()
		with self.freeze_time(day):
			self.run_day()
			self.mollie.settle(self.mine()[-1]["id"], "failed")
			self.assertEqual(self.statements()[1].status, "Failed")
			self.assertEqual(arrears.status(self.administration), "Past Due")
			self.run_day()
			self.assertEqual(len(self.mine()), 2)  # not again the same day
		with self.freeze_time(add_days(day, 5)):
			self.run_day()
			self.assertEqual(len(self.mine()), 3)
			self.mollie.settle(self.mine()[-1]["id"], "failed")
		with self.freeze_time(add_days(day, 12)):
			self.run_day()
			self.assertEqual(len(self.mine()), 3)  # two attempts, no third
			self.assertEqual(arrears.status(self.administration), "Reminded")

	def test_no_mandate_gives_a_payment_link_instead(self):
		subscription = self.start_paid()
		frappe.db.set_value("Payment Mandate", {"administration": self.administration}, "status", "Invalid")
		with self.freeze_time(subscription.einddatum):
			self.run_day()
		with self.freeze_time(add_days(subscription.einddatum, 4)):
			self.run_day()
			statement = frappe.get_doc("Billing Statement", self.statements()[1].name)
			self.assertEqual(statement.status, "Issued")
			self.assertTrue(statement.checkout_url)
			self.assertEqual(self.mine()[-1]["sequenceType"], "first")

	def test_subscription_still_billed_by_mollie_is_left_alone(self):
		subscription = self.start_paid()
		subscription.db_set("mollie_subscription_id", "sub_legacy")
		with self.freeze_time(add_days(subscription.einddatum, 10)):
			self.run_day()
			self.assertEqual(len(self.statements()), 1)

	# chargebacks and arrears

	def test_chargeback_reopens_the_statement_and_arrears_escalate(self):
		subscription = self.start_paid()
		payment_id = self.mine()[-1]["id"]
		subscription.db_set("auto_renew", 0)
		self.assertEqual(self.mollie.settle(payment_id, "paid", charged_back=121), "Charged Back")
		self.assertEqual(self.statements()[0].status, "Charged Back")
		account = frappe.get_doc("Billing Account", self.administration)
		self.assertEqual((account.billing_status, flt(account.open_amount)), ("Past Due", 121.0))
		base = getdate(today())
		for days, expected in ((7, "Reminded"), (14, "Restricted"), (30, "Read Only"), (45, "Collection")):
			with self.freeze_time(add_days(base, days)):
				self.assertEqual(arrears.update(self.administration), expected)
		# a chargeback is never collected again by itself
		with self.freeze_time(add_days(base, 20)):
			subscriptions.collect_due(self.administration)
			self.assertEqual(len(self.mine()), 1)

	def test_paying_everything_ends_the_arrears_at_once(self):
		self.start_paid()
		first = self.mine()[-1]["id"]
		self.mollie.settle(first, "paid", charged_back=121)
		with self.freeze_time(add_days(today(), 20)):
			self.assertEqual(arrears.update(self.administration), "Restricted")
			result = api.pay_statement(self.statements()[0].name)
			self.assertIsNone(result["payment_url"])  # collected on the mandate
			self.assertEqual(arrears.status(self.administration), "Current")  # being collected
			self.mollie.settle(self.mine()[-1]["id"])
			self.assertEqual(arrears.status(self.administration), "Current")
			self.assertEqual(self.statements()[0].status, "Paid")

	def test_exemption_lifts_the_restrictions(self):
		self.start_paid()
		self.mollie.settle(self.mine()[-1]["id"], "paid", charged_back=121)
		account = frappe.get_doc("Billing Account", self.administration)
		account.update({"exempt_until": add_days(today(), 60), "exempt_reason": "Afspraak met de klant"})
		account.save()
		with self.freeze_time(add_days(today(), 31)):
			self.assertEqual(arrears.update(self.administration), "Current")
		with self.freeze_time(add_days(today(), 61)):
			self.assertEqual(arrears.update(self.administration), "Collection")

	# changing and stopping

	def test_upgrade_starts_now_with_the_difference_for_the_rest(self):
		subscription = self.start_paid()
		expensive = make_plan(242)
		total_days = (getdate(subscription.einddatum) - getdate(subscription.startdatum)).days
		with self.freeze_time(add_days(subscription.startdatum, 10)):
			result = subscriptions.change_plan(subscription, expensive)
			self.assertEqual(result, {"effective": "now", "payment_url": None})
			self.assertEqual(frappe.db.get_value("Subscription", subscription.name, "plan"), expensive)
			statement = self.statements()[1]
			self.assertEqual(flt(statement.total), flt(121 * (total_days - 10) / total_days, 2))
			self.assertEqual(self.mine()[-1]["sequenceType"], "recurring")

	def test_downgrade_waits_for_the_next_period(self):
		subscription = self.start_paid(make_plan(242))
		result = subscriptions.change_plan(subscription, self.plan)
		self.assertEqual(result["effective"], str(subscription.einddatum))
		self.assertEqual(len(self.statements()), 1)
		with self.freeze_time(subscription.einddatum):
			self.run_day()
			subscription.reload()
			self.assertEqual((subscription.plan, subscription.pending_plan), (self.plan, None))
			self.assertEqual(flt(self.statements()[1].total), 121.0)

	def test_stopped_subscription_ends_with_the_period(self):
		subscription = self.start_paid()
		subscriptions.stop(subscription)
		self.assertEqual(frappe.db.get_value("Subscription", subscription.name, "status"), "Active")
		with self.freeze_time(subscription.einddatum):
			self.run_day()
			self.assertEqual(frappe.db.get_value("Subscription", subscription.name, "status"), "Expired")
			self.assertEqual(len(self.statements()), 1)

	def test_switch_to_yearly_waits_for_the_period_end(self):
		plan = make_plan(20, yearly=200)
		subscription = self.start_paid(plan)
		result = subscriptions.change_plan(subscription, plan, "Year")
		self.assertEqual(result["effective"], str(subscription.einddatum))
		with self.freeze_time(subscription.einddatum):
			self.run_day()
			subscription.reload()
			self.assertEqual(subscription.billing_period, "Year")
			self.assertEqual(getdate(subscription.einddatum), getdate(add_months(today(), 12)))
			self.assertEqual(flt(self.statements()[1].total), 200.0)

	# usage: what the plan includes and what extra costs

	def test_plan_includes_items_and_prices_the_extra_ones(self):
		product = make_product()
		plan = make_plan(20, rates=[{"product": product, "included": 2, "price": 1.5}])
		subscription = self.start_paid(plan)
		self.assertEqual(pricing.quote(self.administration, product)["amount"], 0)
		first = pricing.charge(self.administration, product, 3, idempotency_key=unique("key"))
		self.assertEqual((first.included_quantity, flt(first.amount)), (2, 1.5))
		again = pricing.charge(self.administration, product, 3, idempotency_key=first.idempotency_key)
		self.assertEqual(again.name, first.name)  # a retried action is charged once
		quote = pricing.quote(self.administration, product, 2)
		self.assertEqual((quote["remaining"], quote["included_quantity"], quote["amount"]), (0, 0, 3.0))
		pricing.charge(self.administration, product, 2, idempotency_key=unique("key"))
		with self.freeze_time(subscription.einddatum):
			self.assertEqual(pricing.quote(self.administration, product)["remaining"], 2)  # a new month
			self.run_day()
			statement = frappe.get_doc("Billing Statement", self.statements()[1].name)
			self.assertEqual([(row.kind, row.quantity, flt(row.amount)) for row in statement.lines], [("Subscription", 1, 20.0), ("Usage", 3, 4.5)])
			self.assertEqual(frappe.db.count("Billing Charge", {"administration": self.administration, "status": "Open"}), 0)

	def test_yearly_plan_can_include_more_and_bills_usage_monthly(self):
		product = make_product()
		plan = make_plan(20, yearly=200, rates=[{"product": product, "included": 2, "price": 1.5, "included_yearly": 5, "price_yearly": 1.0}])
		result = subscriptions.start(self.administration, plan, "Year")
		self.mollie.settle(self.mine()[-1]["id"])
		charge = pricing.charge(self.administration, product, 7, idempotency_key=unique("key"))
		self.assertEqual((charge.included_quantity, flt(charge.unit_price), flt(charge.amount)), (5, 1.0, 2.0))
		with self.freeze_time(add_days(add_months(today(), 1), 1)):
			self.run_day()
			rows = self.statements()
			self.assertEqual(len(rows), 2)
			self.assertEqual(flt(rows[1].total), 2.0)
			self.assertEqual(frappe.db.get_value("Subscription", result["subscription"], "status"), "Active")

	def test_without_a_plan_the_standard_price_of_the_kind_of_customer_applies(self):
		product = make_product(individual=2.5, business=2.0)
		private = pricing.quote(self.administration, product)
		self.assertEqual((private["unit_price"], private["price_includes_vat"], private["amount"]), (2.5, True, 2.5))
		business = pricing.quote(make_business(), product)
		self.assertEqual((business["unit_price"], business["price_includes_vat"], business["amount"]), (2.0, False, 2.42))
		pricing.charge(self.administration, product, idempotency_key=unique("key"))
		with self.freeze_time(add_days(add_months(today(), 1), 1)):
			self.run_day()
			self.assertEqual(flt(self.statements()[0].total), 2.5)

	def test_cheaper_plan_makes_items_more_expensive(self):
		product = make_product()
		free = make_plan(0, rates=[{"product": product, "included": 0, "price": 3.0}])
		plus = make_plan(20, rates=[{"product": product, "included": 10, "price": 1.5}])
		subscriptions.start(self.administration, free)
		self.assertEqual(pricing.quote(self.administration, product)["amount"], 3.0)
		other = make_administration()
		self.administration = other
		self.start_paid(plus)
		self.assertEqual(pricing.quote(other, product)["amount"], 0)

	def test_overdue_payments_block_what_costs_money(self):
		product = make_product()
		self.start_paid(make_plan(20, rates=[{"product": product, "included": 1, "price": 1.5}]))
		self.mollie.settle(self.mine()[-1]["id"], "paid", charged_back=20)
		with self.freeze_time(add_days(today(), 15)):
			self.assertEqual(arrears.update(self.administration), "Restricted")
			pricing.charge(self.administration, product, idempotency_key=unique("key"))  # the included one still works
			with self.assertRaises(frappe.ValidationError):
				pricing.charge(self.administration, product, idempotency_key=unique("key"))

	def test_confirmed_amount_protects_against_a_price_that_went_up(self):
		letter, colour = make_product(), make_product(individual=0.5)
		self.start_paid(make_plan(20, rates=[{"product": letter, "included": 1, "price": 1.5}]))
		items = [(letter, 1), (colour, 1)]
		seen = pricing.quote_many(self.administration, items)
		self.assertEqual((seen["amount"], [row["amount"] for row in seen["lines"]]), (0.5, [0, 0.5]))
		pricing.charge(self.administration, letter, idempotency_key=unique("key"))  # a colleague uses the included one
		with self.assertRaises(pricing.PriceChanged):
			pricing.charge_many(self.administration, items, idempotency_key="act-1" + self.administration, expected_amount=seen["amount"])
		self.assertEqual(frappe.db.count("Billing Charge", {"idempotency_key": ["like", "act-1" + self.administration + ":%"]}), 0)
		charges = pricing.charge_many(self.administration, items, idempotency_key="act-1" + self.administration, expected_amount=2.0)
		self.assertEqual(sorted(flt(c.amount) for c in charges), [0.5, 1.5])
		again = pricing.charge_many(self.administration, items, idempotency_key="act-1" + self.administration, expected_amount=0)
		self.assertEqual({c.name for c in again}, {c.name for c in charges})  # a retry is the same charge
		self.assertEqual(pricing.cancel_charges("act-1" + self.administration), 2)
		self.assertEqual(pricing.quote(self.administration, colour)["amount"], 0.5)
		self.assertEqual([row["status"] for row in api.usage_log(self.administration)], ["Open"])

	# who may do this

	def test_only_who_manages_the_administration_may_order(self):
		outsider = make_user(f"billing-outsider-{frappe.generate_hash(length=6)}@example.com", "Legal User")
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			api.start_subscription(self.administration, self.plan)
		with self.assertRaises(frappe.PermissionError):
			api.overview(self.administration)
		frappe.set_user("Administrator")
		result = subscriptions.start(self.administration, self.plan)
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			api.pay_statement(result["statement"])
