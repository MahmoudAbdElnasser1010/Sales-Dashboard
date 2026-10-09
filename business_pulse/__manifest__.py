# -*- coding: utf-8 -*-
{
    'name': 'Business Pulse - Executive BI Dashboard',
    'version': '18.0.1.1.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Executive and sales dashboard for Odoo: KPIs, quotation funnel, salesperson targets, '
               'receivables aging, comparisons, drill-down and Excel/PDF export',
    'description': """
Business Pulse
==============
A native Odoo business intelligence dashboard that brings sales, revenue,
receivables and customer insights into a single, fast and secure workspace.

* Executive overview with configurable KPI cards and sparklines
* Previous-period, previous-year and custom comparisons
* Sales trend, breakdowns and top performers
* Receivables and overdue aging (accounting users only)
* Deterministic "needs attention" alerts
* Sales Analytics: quotation funnel, open-pipeline aging, salesperson performance
* Targets per company, team or salesperson with on-track status
* Saved views (named filter sets per user)
* One-click drill-down to the exact underlying records
* Excel, CSV and print/PDF export that follow the active filters and access rights
""",
    'author': 'Mahmoud Abdelnasser',
    'license': 'OPL-1',
    # Commercial listing (Odoo Apps Store). Adjust before publishing.
    'price': 99.0,
    'currency': 'EUR',
    'depends': ['web', 'sale', 'account'],
    'data': [
        'security/business_pulse_security.xml',
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/business_pulse_target_views.xml',
        'views/business_pulse_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'business_pulse/static/src/**/*',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
}
