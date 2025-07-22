# Copyright (c) 2025, Buunk Business and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PaymentProviderMethod(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        currencies: DF.Data | None
        is_active: DF.Check
        maximum_amount: DF.Currency
        method_id: DF.Data
        method_name: DF.Data
        minimum_amount: DF.Currency
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
    # end: auto-generated types

    pass
