import frappe
from frappe import _
from frappe.utils import today, add_months, getdate

@frappe.whitelist()
def create_subscription(administration, plan):
    """
    DEPRECATED: Use subscription_flow.create_subscription_with_payment instead
    Create a new subscription
    """
    frappe.log_error("Deprecated function called: create_subscription", "Deprecated API Usage")
    
    # For backward compatibility, redirect to new flow
    # Note: This requires a payment method to be specified
    return {
        "success": False,
        "message": _("This function is deprecated. Please use the new subscription flow with payment method.")
    }

@frappe.whitelist()
def change_plan(subscription, new_plan):
    """Change the plan of an existing subscription"""
    if not subscription or not new_plan:
        frappe.throw(_("Subscription and new plan are required"))
    
    try:
        subscription_doc = frappe.get_doc("Subscription", subscription)
        
        if subscription_doc.status != "Active":
            frappe.throw(_("Cannot change plan of an inactive subscription"))
        
        # Update the plan
        subscription_doc.plan = new_plan
        
        # Let the document's methods handle the rest (updating end date, etc.)
        subscription_doc.save()
        
        return {
            "success": True,
            "message": _("Plan changed successfully")
        }
    except Exception as e:
        frappe.log_error(f"Error changing plan: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }

@frappe.whitelist()
def cancel_subscription(subscription):
    """
    DEPRECATED: Use payment_management.cancel_subscription instead
    Cancel an existing subscription
    """
    frappe.log_error("Deprecated function called: cancel_subscription", "Deprecated API Usage")
    
    # Redirect to new implementation
    from advanced_subscriptions.api.payment_management import cancel_subscription as new_cancel
    return new_cancel(subscription)
    
@frappe.whitelist(allow_guest=True)
def get_plans_with_features():
    """Get all active plans with their features"""
    try:
        plans = frappe.get_all("Plan", 
            filters=[["is_active", "=", 1]],
            fields=["name", "naam", "beschrijving", "prijs", "periode"]
        )
        
        for plan in plans:
            features = frappe.get_all("Plan Feature", 
                filters={"parent": plan.name},
                fields=["name", "feature"]
            )
            plan["features"] = features

        plans.sort(key=lambda x: x["prijs"])
        
        return plans
    except Exception as e:
        frappe.log_error(f"Error getting plans with features: {str(e)}")
        return []