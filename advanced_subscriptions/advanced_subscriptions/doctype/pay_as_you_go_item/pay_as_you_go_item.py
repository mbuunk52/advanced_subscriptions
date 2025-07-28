# Copyright (c) 2025, Buunk Business and contriburors
# MIT License. See license.txt

import frappe
from frappe.model.document import Document

class PayAsYouGoItem(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        description: DF.Text | None
        item_name: DF.Data
        parent: DF.Data
        parentfield: DF.Data
        parenttype: DF.Data
        price: DF.Currency
    # end: auto-generated types

    pass