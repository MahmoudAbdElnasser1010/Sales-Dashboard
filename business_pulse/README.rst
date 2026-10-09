==============
Business Pulse
==============

Executive business intelligence dashboard for Odoo 18.0: sales KPIs,
invoiced revenue, receivables aging, period comparisons, rules-based alerts,
drill-down to source records and CSV export.

Requirements
============

* Odoo 18.0 (tested on Community edition)
* Apps: Sales (``sale``) and Invoicing (``account``)
* No extra Python or JavaScript libraries (charts use the Chart.js build shipped
  with Odoo)

Installation
============

1. Copy the ``business_pulse`` folder into an addons path.
2. Update the apps list and install **Business Pulse**.
3. Sales Administrators get access automatically. Give other users the
   *Business Pulse / User* access right (Settings → Users).

Configuration
=============

*Business Pulse → Configuration → Settings* (Administrators):

* Default period and comparison
* Expiring quotation window, stalled quotation age, sales decline threshold
* Maximum exported rows

Each user can choose and order their KPI cards and set a personal default
period and comparison with the **Customize** button.

Security model
==============

* Every figure is computed server side with the ORM in the current user's
  environment. Access rights, record rules and multi-company rules apply to
  KPIs, charts, drill-downs and exports. No ``sudo()`` is used to read business
  data.
* Financial sections (invoiced revenue, receivables, overdue alerts, invoice and
  payment activity) require the *Invoicing* or *Accounting* read role.
* The dashboard service rejects users without the *Business Pulse / User* group.
* All client-supplied filters (dates, ids, modes) are validated server side.

Metric definitions
==================

Confirmed Sales
    Untaxed value of sales order lines in status *Sales Order* whose order date
    falls in the period, from Odoo's ``sale.report``, in the active company
    currency (other currencies at the latest rate). Cancelled orders excluded.
Confirmed Orders
    Distinct confirmed orders in the period. With a product or category
    filter, only orders containing a matching line are counted and only the
    matching lines are valued.
Average Order Value
    Confirmed Sales / Confirmed Orders.
Conversion Rate
    Cohort rate: quotations *created* in the period (any status) that are now
    confirmed, divided by all quotations created in the period. Change shown
    in percentage points.
Open Quotations
    Untaxed value of orders currently in Quotation / Quotation Sent (snapshot).
Active / New Customers
    Distinct commercial partners with a confirmed order in the period; new =
    first ever confirmed order (selected companies) in the period.
Invoiced Revenue
    ``-balance`` of product lines of posted customer invoices and credit notes
    by invoice date, converted per company. Billed revenue, not cash.
Outstanding / Overdue Receivables
    Residual amount of posted customer invoices and credit notes as of today;
    overdue = due date before today. Product filters do not apply.

Period comparison
=================

* *Previous period* for calendar presets compares the same elapsed days of the
  previous unit (month-to-date vs the same days of last month, clamped to the
  end of that month). For other ranges it is the immediately preceding range of
  equal length.
* *Same period last year* shifts both dates by one year.
* *Custom* uses the dates entered.

Tests
=====

::

    odoo-bin -d <db> -i business_pulse --test-tags=/business_pulse --stop-after-init

Known limitations
=================

* Currency conversion uses the latest rate (same as Odoo's Sales Analysis).
* Receivables are a snapshot; unallocated customer payments are not deducted.
* Profitability, inventory, targets and budgets are planned for later versions.
