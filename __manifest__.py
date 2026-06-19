# -*- coding: utf-8 -*-
{
    'name': 'WooCommerce Connector',

    'summary': 'Synchronize Odoo 18 with WooCommerce — Products, Orders, Customers, Taxes & Stock',

    'description': '''
WooCommerce Connector for Odoo 18
===================================

Production-ready bidirectional sync between Odoo 18 and WooCommerce stores.

Connection:
-----------
* REST API v3 (Consumer Key & Secret)
* Sandbox / Live mode per store
* Webhook support for real-time sync
* Multiple store backends

Import (WooCommerce → Odoo):
-----------------------------
* Products: Simple & Variable (with variants, attributes, images)
* Product Categories, Tags, Attributes
* Tax Rates
* Customers (registered accounts)
* Sale Orders with line items, shipping & payment info
* Shipping Methods & Payment Gateways

Export (Odoo → WooCommerce):
-----------------------------
* Stock Inventory quantities
* Order fulfillment / status updates
* Product data & prices

Core Features:
--------------
* Multi-store support (multiple WooCommerce backends)
* Auto-create missing products when importing orders
* SKU-based product matching to avoid duplicates
* Incremental sync using last-sync timestamps
* Force re-sync option to bypass timestamp filter
* Scheduled cron jobs for automated sync
* OWL-based dashboard with live insights
    ''',

    'author': 'Waqas Mustafa',
    'website': 'https://www.linkedin.com/in/waqas-mustafa-ba5701209/',
    'support': 'mustafawaqas0@gmail.com',

    'price': 49.00,
    'currency': 'USD',

    'version': '18.0.1.0',
    'license': 'LGPL-3',
    'category': 'Sales/Sales',

    'depends': [
        'mail',
        'contacts',
        'sale_management',
        'delivery',
        'stock',
        'account',
    ],

    'external_dependencies': {
        'python': ['woocommerce', 'requests'],
    },

    'data': [
        'security/ir.model.access.csv',
        'data/order_stage_data.xml',
        'data/ir_cron_data.xml',
        'wizard/wc_sync_wizard_view.xml',
        'views/order_stage_views.xml',
        'views/payment_views.xml',
        'views/shipping_views.xml',
        'views/tax_views.xml',
        'views/category_views.xml',
        'views/tag_views.xml',
        'views/attribute_views.xml',
        'views/product_link_views.xml',
        'views/customer_views.xml',
        'views/order_views.xml',
        'views/wc_store_views.xml',
        'views/dashboard_views.xml',
        'views/menu.xml',
    ],

    'images': [
        'static/description/banner.png',
        'static/description/icon.png',
    ],

    'assets': {
        'web.assets_backend': [
            'ad_woocomerce_connector/static/src/css/wc_dashboard.css',
            'ad_woocomerce_connector/static/src/js/wc_dashboard.js',
            'ad_woocomerce_connector/static/src/xml/wc_dashboard.xml',
        ],
    },

    'installable': True,
    'application': True,
    'auto_install': False,
}
