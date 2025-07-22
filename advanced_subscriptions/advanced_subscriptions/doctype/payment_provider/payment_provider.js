// Copyright (c) 2025, Buunk Business and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Provider", {
    refresh(frm) {
        // Add custom buttons
        if (!frm.is_new()) {
            frm.add_custom_button(__("Test Connection"), function() {
                test_provider_connection(frm);
            }, __("Actions"));
            
            frm.add_custom_button(__("Sync Payment Methods"), function() {
                sync_payment_methods(frm);
            }, __("Actions"));
        }
        
        // Set webhook URL automatically
        if (frm.doc.provider_type && !frm.doc.webhook_url) {
            let base_url = window.location.protocol + "//" + window.location.host;
            let webhook_path = "";
            
            switch(frm.doc.provider_type) {
                case "Mollie":
                    webhook_path = "/api/method/advanced_subscriptions.api.webhooks.mollie_webhook";
                    break;
                case "Stripe":
                    webhook_path = "/api/method/advanced_subscriptions.api.webhooks.stripe_webhook";
                    break;
                default:
                    webhook_path = "/api/method/advanced_subscriptions.api.webhooks.generic_webhook";
            }
            
            frm.set_value("webhook_url", base_url + webhook_path);
        }
    },
    
    provider_type(frm) {
        // Set default base URL when provider type changes
        if (frm.doc.provider_type) {
            let base_urls = {
                "Mollie": "https://api.mollie.com/v2",
                "Stripe": "https://api.stripe.com/v1",
                "PayPal": "https://api.paypal.com",
                "Adyen": "https://checkout-test.adyen.com/v70",
                "Square": "https://connect.squareup.com",
                "Razorpay": "https://api.razorpay.com/v1"
            };
            
            if (base_urls[frm.doc.provider_type]) {
                frm.set_value("base_url", base_urls[frm.doc.provider_type]);
            }
            
            // Set webhook URL
            let base_url = window.location.protocol + "//" + window.location.host;
            let webhook_endpoints = {
                "Mollie": "/api/method/advanced_subscriptions.api.webhooks.mollie_webhook",
                "Stripe": "/api/method/advanced_subscriptions.api.webhooks.stripe_webhook",
                "PayPal": "/api/method/advanced_subscriptions.api.webhooks.paypal_webhook"
            };
            
            if (webhook_endpoints[frm.doc.provider_type]) {
                frm.set_value("webhook_url", base_url + webhook_endpoints[frm.doc.provider_type]);
            }
        }
    }
});

function test_provider_connection(frm) {
    frappe.call({
        method: "advanced_subscriptions.advanced_subscriptions.doctype.payment_provider.payment_provider.test_provider_connection",
        args: {
            provider_name: frm.doc.name
        },
        callback: function(r) {
            if (r.message) {
                if (r.message.success) {
                    frappe.msgprint({
                        title: __("Connection Successful"),
                        message: r.message.message,
                        indicator: "green"
                    });
                } else {
                    frappe.msgprint({
                        title: __("Connection Failed"),
                        message: r.message.message,
                        indicator: "red"
                    });
                }
            }
        }
    });
}

function sync_payment_methods(frm) {
    frappe.call({
        method: "advanced_subscriptions.advanced_subscriptions.doctype.payment_provider.payment_provider.sync_provider_methods",
        args: {
            provider_name: frm.doc.name
        },
        freeze: true,
        freeze_message: __("Syncing payment methods..."),
        callback: function(r) {
            if (r.message) {
                if (r.message.success) {
                    frappe.msgprint({
                        title: __("Sync Successful"),
                        message: r.message.message,
                        indicator: "green"
                    });
                    frm.reload_doc();
                } else {
                    frappe.msgprint({
                        title: __("Sync Failed"),
                        message: r.message.message,
                        indicator: "red"
                    });
                }
            }
        }
    });
}
