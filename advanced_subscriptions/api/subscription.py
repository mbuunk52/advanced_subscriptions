import frappe
from frappe import _
from frappe.utils import today, add_months, getdate

@frappe.whitelist()
def create_subscription(administratie, plan):
    """Create a new subscription"""
    if not administratie or not plan:
        frappe.throw(_("Administratie and plan are required"))
    
    try:
        # Check if a subscription already exists for this administratie
        existing = frappe.get_all("Subscription", 
            filters={"administratie": administratie, "status": "Active"},
            fields=["name"])
        
        if existing:
            frappe.throw(_("An active subscription already exists for this administratie"))
        
        # Get the plan details
        plan_doc = frappe.get_doc("Plan", plan)
        
        # Create the subscription
        subscription = frappe.new_doc("Subscription")
        subscription.administratie = administratie
        subscription.plan = plan
        subscription.status = "Active"
        subscription.startdatum = today()
        
        # Set end date based on plan period
        if plan_doc.periode == "Month":
            subscription.einddatum = add_months(today(), 1)
        elif plan_doc.periode == "Year":
            subscription.einddatum = add_months(today(), 12)
        
        subscription.insert()
        
        return {
            "success": True,
            "message": _("Subscription created successfully"),
            "subscription": subscription.name
        }
    except Exception as e:
        frappe.log_error(f"Error creating subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
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
    """Cancel an existing subscription"""
    if not subscription:
        frappe.throw(_("Subscription is required"))
    
    try:
        subscription_doc = frappe.get_doc("Subscription", subscription)
        
        if subscription_doc.status != "Active":
            frappe.throw(_("Cannot cancel an inactive subscription"))
        
        # Update the status
        subscription_doc.status = "Cancelled"
        subscription_doc.save()
        
        return {
            "success": True,
            "message": _("Subscription cancelled successfully")
        }
    except Exception as e:
        frappe.log_error(f"Error cancelling subscription: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }
    
@frappe.whitelist()
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