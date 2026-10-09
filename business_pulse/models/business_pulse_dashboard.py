# -*- coding: utf-8 -*-
"""Business Pulse data service.

Every number shown on the dashboard is computed here, server side, with the
ORM in the current user's environment. Access rights, record rules and
multi-company restrictions therefore apply to every metric, drill-down and
export. No ``sudo()`` is used to read business data.

Each widget is computed independently (``get_widget``) so that a slow or
failing widget never blocks the rest of the dashboard.
"""
import logging
from datetime import date, datetime, time, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import get_lang

_logger = logging.getLogger(__name__)

PRESETS = [
    'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month',
    'this_quarter', 'last_quarter', 'this_year', 'last_year',
    'last_7_days', 'last_30_days', 'last_90_days', 'custom',
]
COMPARISONS = ['previous_period', 'previous_year', 'custom', 'none']
GRANULARITIES = ['day', 'week', 'month', 'quarter']
MAX_RANGE_DAYS = 3700  # ~10 years
MAX_FILTER_IDS = 200
SALE_DONE_STATES = ('sale',)
QUOTATION_STATES = ('draft', 'sent')
INVOICE_TYPES = ('out_invoice', 'out_refund')

# Same-length units used by "previous period" for calendar presets, so that
# "this month" (month to date) is compared with the same days of last month.
PRESET_UNITS = {
    'today': relativedelta(days=1),
    'yesterday': relativedelta(days=1),
    'this_week': relativedelta(weeks=1),
    'last_week': relativedelta(weeks=1),
    'this_month': relativedelta(months=1),
    'last_month': relativedelta(months=1),
    'this_quarter': relativedelta(months=3),
    'last_quarter': relativedelta(months=3),
    'this_year': relativedelta(years=1),
    'last_year': relativedelta(years=1),
}
FULL_UNIT_PRESETS = ('today', 'yesterday', 'last_week', 'last_month', 'last_quarter', 'last_year')

DEFAULT_KPIS = [
    'confirmed_sales', 'order_count', 'avg_order_value',
    'conversion_rate', 'invoiced_revenue', 'overdue_receivables',
]
# Used instead of the financial cards for users without an accounting role.
DEFAULT_SALES_KPIS = [
    'confirmed_sales', 'order_count', 'avg_order_value',
    'conversion_rate', 'open_quotations', 'active_customers',
]

# key -> (sale.report field, sale.order field used for drill-down, comodel)
BREAKDOWN_DIMENSIONS = {
    'categ_id': ('categ_id', 'order_line.product_id.categ_id', 'product.category'),
    'product_id': ('product_id', 'order_line.product_id', 'product.product'),
    'user_id': ('user_id', 'user_id', 'res.users'),
    'team_id': ('team_id', 'team_id', 'crm.team'),
    'commercial_partner_id': ('commercial_partner_id', 'partner_id.commercial_partner_id', 'res.partner'),
    'company_id': ('company_id', 'company_id', 'res.company'),
}
TOP_KINDS = {
    'products': 'product_id',
    'customers': 'commercial_partner_id',
    'salespeople': 'user_id',
}
# Field paths used to apply dimension filters on each source model.
DIMENSION_PATHS = {
    'report': {
        'team_ids': 'team_id', 'user_ids': 'user_id', 'partner_ids': 'partner_id',
        'product_ids': 'product_id', 'categ_ids': 'categ_id',
    },
    'order': {
        'team_ids': 'team_id', 'user_ids': 'user_id', 'partner_ids': 'partner_id',
        'product_ids': 'order_line.product_id', 'categ_ids': 'order_line.product_id.categ_id',
    },
    'invoice': {
        'team_ids': 'team_id', 'user_ids': 'invoice_user_id', 'partner_ids': 'partner_id',
        'product_ids': 'invoice_line_ids.product_id', 'categ_ids': 'invoice_line_ids.product_id.categ_id',
    },
    'invoice_line': {
        'team_ids': 'move_id.team_id', 'user_ids': 'move_id.invoice_user_id',
        'partner_ids': 'move_id.partner_id', 'product_ids': 'product_id',
        'categ_ids': 'product_id.categ_id',
    },
}
HIERARCHICAL_FILTERS = ('partner_ids', 'categ_ids')
DIMENSION_FILTERS = ('team_ids', 'user_ids', 'partner_ids', 'product_ids', 'categ_ids')


class BusinessPulseDashboard(models.AbstractModel):
    _name = 'business.pulse.dashboard'
    _description = 'Business Pulse Dashboard Service'

    # ------------------------------------------------------------------
    # Catalogs (translated at call time)
    # ------------------------------------------------------------------
    @api.model
    def _kpi_catalog(self):
        return {
            'confirmed_sales': {
                'label': _("Confirmed Sales"), 'kind': 'monetary', 'group': 'sales', 'better': 'up',
                'icon': 'fa-shopping-cart',
                'definition': _("Untaxed value of confirmed sales order lines (status 'Sales Order') "
                                "whose order date falls in the period. Converted to the current "
                                "company currency at the latest rate. Cancelled orders are excluded."),
            },
            'order_count': {
                'label': _("Confirmed Orders"), 'kind': 'count', 'group': 'sales', 'better': 'up',
                'icon': 'fa-file-text-o',
                'definition': _("Number of confirmed sales orders whose order date falls in the period. "
                                "With a product filter, only orders containing that product are counted."),
            },
            'avg_order_value': {
                'label': _("Average Order Value"), 'kind': 'monetary', 'group': 'sales', 'better': 'up',
                'icon': 'fa-balance-scale',
                'definition': _("Confirmed Sales divided by Confirmed Orders for the same period and filters."),
            },
            'conversion_rate': {
                'label': _("Conversion Rate"), 'kind': 'rate', 'group': 'sales', 'better': 'up',
                'icon': 'fa-exchange',
                'definition': _("Cohort rate: of all quotations created in the period, the share that is "
                                "now a confirmed sales order. Changes are shown in percentage points (pp)."),
            },
            'open_quotations': {
                'label': _("Open Quotations"), 'kind': 'monetary', 'group': 'sales', 'better': 'up',
                'icon': 'fa-hourglass-half', 'snapshot': True,
                'definition': _("Untaxed value of all quotations currently in Quotation or Quotation Sent "
                                "status, as of today. The date range does not apply."),
            },
            'active_customers': {
                'label': _("Active Customers"), 'kind': 'count', 'group': 'sales', 'better': 'up',
                'icon': 'fa-users',
                'definition': _("Distinct customer entities (companies or individuals) with at least one "
                                "confirmed order in the period."),
            },
            'new_customers': {
                'label': _("New Customers"), 'kind': 'count', 'group': 'sales', 'better': 'up',
                'icon': 'fa-user-plus',
                'definition': _("Active customers whose first ever confirmed order (in the selected "
                                "companies) falls in the period."),
            },
            'invoiced_revenue': {
                'label': _("Invoiced Revenue"), 'kind': 'monetary', 'group': 'finance', 'better': 'up',
                'icon': 'fa-money',
                'definition': _("Untaxed amount of posted customer invoices minus posted credit notes, "
                                "by invoice date, in company currency. This is billed revenue, not cash "
                                "collected."),
            },
            'receivables': {
                'label': _("Outstanding Receivables"), 'kind': 'monetary', 'group': 'finance',
                'better': 'down', 'icon': 'fa-inbox', 'snapshot': True,
                'definition': _("Residual (unpaid) amount of posted customer invoices and credit notes, "
                                "as of today. Unallocated payments are not deducted."),
            },
            'overdue_receivables': {
                'label': _("Overdue Receivables"), 'kind': 'monetary', 'group': 'finance',
                'better': 'down', 'icon': 'fa-exclamation-triangle', 'snapshot': True,
                'definition': _("Outstanding receivables whose due date is before today."),
            },
        }

    @api.model
    def _preset_labels(self):
        return {
            'today': _("Today"), 'yesterday': _("Yesterday"),
            'this_week': _("This week"), 'last_week': _("Last week"),
            'this_month': _("This month"), 'last_month': _("Last month"),
            'this_quarter': _("This quarter"), 'last_quarter': _("Last quarter"),
            'this_year': _("This year"), 'last_year': _("Last year"),
            'last_7_days': _("Last 7 days"), 'last_30_days': _("Last 30 days"),
            'last_90_days': _("Last 90 days"), 'custom': _("Custom range"),
        }

    @api.model
    def _dimension_labels(self):
        return {
            'categ_id': _("Product Category"), 'product_id': _("Product"),
            'user_id': _("Salesperson"), 'team_id': _("Sales Team"),
            'commercial_partner_id': _("Customer"), 'company_id': _("Company"),
        }

    # ------------------------------------------------------------------
    # Settings, permissions and time helpers
    # ------------------------------------------------------------------
    @api.model
    def _settings(self):
        ICP = self.env['ir.config_parameter'].sudo()

        def _int(key, default, low, high):
            try:
                return min(max(int(ICP.get_param(key, default)), low), high)
            except (TypeError, ValueError):
                return default

        def _float(key, default):
            try:
                return max(float(ICP.get_param(key, default)), 0.0)
            except (TypeError, ValueError):
                return default

        preset = ICP.get_param('business_pulse.default_preset', 'this_month')
        comparison = ICP.get_param('business_pulse.default_comparison', 'previous_period')
        return {
            'default_preset': preset if preset in PRESETS and preset != 'custom' else 'this_month',
            'default_comparison': comparison if comparison in COMPARISONS and comparison != 'custom'
            else 'previous_period',
            'expiring_days': _int('business_pulse.expiring_days', 7, 1, 365),
            'stale_days': _int('business_pulse.stale_days', 30, 1, 3650),
            'sales_drop_threshold': _float('business_pulse.sales_drop_threshold', 20.0),
            'export_limit': _int('business_pulse.export_limit', 10000, 100, 1000000),
        }

    @api.model
    def _can_sales(self):
        return self.env['sale.report'].has_access('read')

    @api.model
    def _can_finance(self):
        user = self.env.user
        return (
            (user.has_group('account.group_account_invoice') or user.has_group('account.group_account_readonly'))
            and self.env['account.move'].has_access('read')
        )

    @api.model
    def _tz_name(self):
        tz = self.env.context.get('tz') or self.env.user.tz or 'UTC'
        return tz if tz in pytz.all_timezones_set else 'UTC'

    @api.model
    def _today(self):
        return datetime.now(pytz.timezone(self._tz_name())).date()

    @api.model
    def _first_weekday(self):
        """0 = Monday ... 6 = Sunday, consistent with ``_read_group`` week buckets."""
        return int(get_lang(self.env).week_start) - 1

    @api.model
    def _week_start(self, day):
        return day - timedelta(days=(day.weekday() - self._first_weekday()) % 7)

    @api.model
    def _preset_range(self, preset, today):
        if preset == 'today':
            return today, today
        if preset == 'yesterday':
            day = today - timedelta(days=1)
            return day, day
        if preset == 'this_week':
            return self._week_start(today), today
        if preset == 'last_week':
            start = self._week_start(today) - timedelta(days=7)
            return start, start + timedelta(days=6)
        if preset == 'this_month':
            return today.replace(day=1), today
        if preset == 'last_month':
            end = today.replace(day=1) - timedelta(days=1)
            return end.replace(day=1), end
        quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        if preset == 'this_quarter':
            return quarter_start, today
        if preset == 'last_quarter':
            return quarter_start - relativedelta(months=3), quarter_start - timedelta(days=1)
        if preset == 'this_year':
            return date(today.year, 1, 1), today
        if preset == 'last_year':
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        if preset in ('last_7_days', 'last_30_days', 'last_90_days'):
            days = int(preset.split('_')[1])
            return today - timedelta(days=days - 1), today
        raise UserError(_("Unknown date preset."))

    @api.model
    def _comparison_range(self, comparison, preset, date_from, date_to):
        if comparison == 'previous_year':
            return date_from - relativedelta(years=1), date_to - relativedelta(years=1)
        if comparison != 'previous_period':
            return None
        unit = PRESET_UNITS.get(preset)
        if unit:
            cmp_from = date_from - unit
            if preset in FULL_UNIT_PRESETS:
                return cmp_from, date_from - timedelta(days=1)
            # Period-to-date: compare the same elapsed days of the previous unit.
            return cmp_from, min(cmp_from + (date_to - date_from), date_from - timedelta(days=1))
        length = (date_to - date_from).days
        cmp_to = date_from - timedelta(days=1)
        return cmp_to - timedelta(days=length), cmp_to

    @api.model
    def _utc_bounds(self, date_from, date_to):
        """Local-day boundaries [start, end) converted to UTC datetime strings."""
        tz = pytz.timezone(self._tz_name())
        start = tz.localize(datetime.combine(date_from, time.min)).astimezone(pytz.utc)
        end = tz.localize(datetime.combine(date_to + timedelta(days=1), time.min)).astimezone(pytz.utc)
        return (
            fields.Datetime.to_string(start.replace(tzinfo=None)),
            fields.Datetime.to_string(end.replace(tzinfo=None)),
        )

    @api.model
    def _auto_granularity(self, date_from, date_to):
        days = (date_to - date_from).days + 1
        if days <= 31:
            return 'day'
        if days <= 120:
            return 'week'
        if days <= 731:
            return 'month'
        return 'quarter'

    @api.model
    def _bucket_start(self, day, granularity):
        if isinstance(day, datetime):
            day = day.date()
        if granularity == 'week':
            return self._week_start(day)
        if granularity == 'month':
            return day.replace(day=1)
        if granularity == 'quarter':
            return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
        return day

    @api.model
    def _buckets(self, date_from, date_to, granularity):
        step = {
            'day': relativedelta(days=1), 'week': relativedelta(weeks=1),
            'month': relativedelta(months=1), 'quarter': relativedelta(months=3),
        }[granularity]
        current = self._bucket_start(date_from, granularity)
        buckets = []
        while current <= date_to and len(buckets) < 1000:
            buckets.append(current)
            current += step
        return buckets

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------
    @api.model
    def _parse_date(self, value, label):
        try:
            return fields.Date.to_date(value)
        except (TypeError, ValueError):
            raise UserError(_("%s is not a valid date.", label))

    @api.model
    def _parse_ids(self, value):
        if not value:
            return []
        if not isinstance(value, (list, tuple)):
            raise UserError(_("Invalid filter value."))
        ids = []
        for item in value[:MAX_FILTER_IDS]:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise UserError(_("Invalid filter value."))
            ids.append(item)
        return ids

    @api.model
    def _parse_filters(self, raw):
        """Validate client-supplied filters. Never trust the browser."""
        raw = raw if isinstance(raw, dict) else {}
        today = self._today()
        preset = raw.get('preset') or 'this_month'
        if preset not in PRESETS:
            raise UserError(_("Unknown date preset."))
        if preset == 'custom':
            date_from = self._parse_date(raw.get('date_from'), _("Start date"))
            date_to = self._parse_date(raw.get('date_to'), _("End date"))
            if not date_from or not date_to:
                raise UserError(_("Select both a start and an end date."))
        else:
            date_from, date_to = self._preset_range(preset, today)
        if date_from > date_to:
            raise UserError(_("The start date must be before the end date."))
        if (date_to - date_from).days > MAX_RANGE_DAYS:
            raise UserError(_("The selected period is too long (maximum 10 years)."))

        comparison = raw.get('comparison') or 'previous_period'
        if comparison not in COMPARISONS:
            raise UserError(_("Unknown comparison mode."))
        if comparison == 'custom':
            cmp_from = self._parse_date(raw.get('compare_from'), _("Comparison start date"))
            cmp_to = self._parse_date(raw.get('compare_to'), _("Comparison end date"))
            if not cmp_from or not cmp_to:
                raise UserError(_("Select both comparison dates."))
            if cmp_from > cmp_to:
                raise UserError(_("The comparison start date must be before its end date."))
            if (cmp_to - cmp_from).days > MAX_RANGE_DAYS:
                raise UserError(_("The comparison period is too long (maximum 10 years)."))
            comparison_range = (cmp_from, cmp_to)
        else:
            comparison_range = self._comparison_range(comparison, preset, date_from, date_to)

        allowed = self.env.companies
        company_ids = self._parse_ids(raw.get('company_ids'))
        if company_ids:
            if not set(company_ids) <= set(allowed.ids):
                raise AccessError(_("You cannot access one of the selected companies."))
            # keep the active company first so it drives the display currency
            companies = allowed.filtered(lambda c: c.id in company_ids)
        else:
            companies = allowed

        granularity = raw.get('granularity') or 'auto'
        if granularity not in GRANULARITIES:
            granularity = self._auto_granularity(date_from, date_to)

        filters = {
            'preset': preset,
            'date_from': date_from,
            'date_to': date_to,
            'comparison': comparison,
            'cmp_from': comparison_range and comparison_range[0],
            'cmp_to': comparison_range and comparison_range[1],
            'company_ids': companies.ids,
            'granularity': granularity,
            'today': today,
        }
        for key in DIMENSION_FILTERS:
            filters[key] = self._parse_ids(raw.get(key))
        return filters

    @api.model
    def _dimension_domain(self, filters, target, skip=()):
        domain = []
        for key, path in DIMENSION_PATHS[target].items():
            if key in skip or not filters.get(key):
                continue
            operator = 'child_of' if key in HIERARCHICAL_FILTERS else 'in'
            domain.append((path, operator, filters[key]))
        return domain

    @api.model
    def _ignored_filters(self, filters, skip):
        labels = {
            'team_ids': _("Sales Team"), 'user_ids': _("Salesperson"), 'partner_ids': _("Customer"),
            'product_ids': _("Product"), 'categ_ids': _("Product Category"),
        }
        return [labels[key] for key in skip if filters.get(key)]

    # Domains --------------------------------------------------------------
    @api.model
    def _report_domain(self, filters, date_from=None, date_to=None, states=SALE_DONE_STATES):
        domain = [('state', 'in', list(states)), ('company_id', 'in', filters['company_ids'])]
        if date_from:
            start, end = self._utc_bounds(date_from, date_to)
            domain += [('date', '>=', start), ('date', '<', end)]
        return domain + self._dimension_domain(filters, 'report')

    @api.model
    def _order_domain(self, filters, date_from=None, date_to=None, states=SALE_DONE_STATES,
                      date_field='date_order'):
        domain = [('state', 'in', list(states)), ('company_id', 'in', filters['company_ids'])]
        if date_from:
            start, end = self._utc_bounds(date_from, date_to)
            domain += [(date_field, '>=', start), (date_field, '<', end)]
        return domain + self._dimension_domain(filters, 'order')

    @api.model
    def _invoice_line_domain(self, filters, date_from, date_to):
        return [
            ('move_id.move_type', 'in', list(INVOICE_TYPES)),
            ('parent_state', '=', 'posted'),
            ('display_type', '=', 'product'),
            ('company_id', 'in', filters['company_ids']),
            ('move_id.invoice_date', '>=', fields.Date.to_string(date_from)),
            ('move_id.invoice_date', '<=', fields.Date.to_string(date_to)),
        ] + self._dimension_domain(filters, 'invoice_line')

    @api.model
    def _invoice_domain(self, filters, date_from, date_to):
        return [
            ('move_type', 'in', list(INVOICE_TYPES)),
            ('state', '=', 'posted'),
            ('company_id', 'in', filters['company_ids']),
            ('invoice_date', '>=', fields.Date.to_string(date_from)),
            ('invoice_date', '<=', fields.Date.to_string(date_to)),
        ] + self._dimension_domain(filters, 'invoice')

    @api.model
    def _receivable_domain(self, filters):
        return [
            ('move_type', 'in', list(INVOICE_TYPES)),
            ('state', '=', 'posted'),
            ('amount_residual', '!=', 0),
            ('company_id', 'in', filters['company_ids']),
        ] + self._dimension_domain(filters, 'invoice', skip=('product_ids', 'categ_ids'))

    # Actions ---------------------------------------------------------------
    @api.model
    def _act(self, name, model, domain, context=None, views=None):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'domain': domain,
            'views': views or [[False, 'list'], [False, 'form']],
            'context': dict({'create': False}, **(context or {})),
            'target': 'current',
        }

    @api.model
    def _orders_act(self, name, domain, group_by=None):
        context = {'group_by': group_by} if group_by else {}
        return self._act(name, 'sale.order', domain, context)

    @api.model
    def _invoices_act(self, name, domain):
        list_view = self.env.ref('account.view_out_invoice_tree', raise_if_not_found=False)
        form_view = self.env.ref('account.view_move_form', raise_if_not_found=False)
        views = [[list_view.id if list_view else False, 'list'], [form_view.id if form_view else False, 'form']]
        return self._act(name, 'account.move', domain, {'default_move_type': 'out_invoice'}, views)

    # ------------------------------------------------------------------
    # Aggregation primitives
    # ------------------------------------------------------------------
    @api.model
    def _convert_by_company(self, rows):
        """Sum ``(company, amount)`` pairs into the active company currency."""
        target = self.env.company.currency_id
        today = fields.Date.context_today(self)
        total = 0.0
        for company, amount in rows:
            amount = amount or 0.0
            currency = company.currency_id if company else target
            if currency and currency != target:
                amount = currency._convert(amount, target, self.env.company, today)
            total += amount
        return total

    @api.model
    def _sales_totals(self, filters, date_from, date_to):
        (amount, orders, customers), = self.env['sale.report']._read_group(
            self._report_domain(filters, date_from, date_to),
            aggregates=['price_subtotal:sum', 'order_reference:count_distinct',
                        'commercial_partner_id:count_distinct'],
        )
        return {'amount': amount or 0.0, 'orders': orders or 0, 'customers': customers or 0}

    @api.model
    def _sales_series(self, filters, date_from, date_to, granularity):
        rows = self.env['sale.report']._read_group(
            self._report_domain(filters, date_from, date_to),
            groupby=[f'date:{granularity}'],
            aggregates=['price_subtotal:sum', 'order_reference:count_distinct'],
        )
        by_bucket = {self._bucket_start(day, granularity): (amount or 0.0, count or 0)
                     for day, amount, count in rows if day}
        return [(bucket,) + by_bucket.get(bucket, (0.0, 0))
                for bucket in self._buckets(date_from, date_to, granularity)]

    @api.model
    def _revenue_total(self, filters, date_from, date_to):
        rows = self.env['account.move.line']._read_group(
            self._invoice_line_domain(filters, date_from, date_to),
            groupby=['company_id'], aggregates=['balance:sum'],
        )
        return -self._convert_by_company(rows)

    @api.model
    def _revenue_series(self, filters, date_from, date_to, granularity):
        rows = self.env['account.move.line']._read_group(
            self._invoice_line_domain(filters, date_from, date_to),
            groupby=[f'invoice_date:{granularity}', 'company_id'], aggregates=['balance:sum'],
        )
        per_bucket = {}
        for day, company, balance in rows:
            if day:
                per_bucket.setdefault(self._bucket_start(day, granularity), []).append((company, balance))
        return [(bucket, -self._convert_by_company(per_bucket.get(bucket, [])))
                for bucket in self._buckets(date_from, date_to, granularity)]

    @api.model
    def _conversion(self, filters, date_from, date_to):
        rows = self.env['sale.order']._read_group(
            self._order_domain(filters, date_from, date_to,
                               states=('draft', 'sent', 'sale', 'cancel'), date_field='create_date'),
            groupby=['state'], aggregates=['__count'],
        )
        counts = dict(rows)
        total = sum(counts.values())
        return {
            'rate': counts.get('sale', 0) / total if total else None,
            'created': total,
            'confirmed': counts.get('sale', 0),
        }

    @api.model
    def _receivable_totals(self, filters, extra_domain=None):
        rows = self.env['account.move']._read_group(
            self._receivable_domain(filters) + (extra_domain or []),
            groupby=['company_id'], aggregates=['amount_residual_signed:sum', '__count'],
        )
        return {
            'amount': self._convert_by_company([(company, amount) for company, amount, _count in rows]),
            'count': sum(count for _company, _amount, count in rows),
        }

    @api.model
    def _customer_ids(self, filters, date_from, date_to):
        rows = self.env['sale.report']._read_group(
            self._report_domain(filters, date_from, date_to), groupby=['commercial_partner_id'],
        )
        return {partner.id for partner, in rows if partner}

    @api.model
    def _new_customer_ids(self, filters, date_from, date_to):
        active = self._customer_ids(filters, date_from, date_to)
        if not active:
            return set()
        start, _end = self._utc_bounds(date_from, date_to)
        earlier = self.env['sale.report']._read_group(
            [('state', 'in', list(SALE_DONE_STATES)), ('company_id', 'in', filters['company_ids']),
             ('date', '<', start), ('commercial_partner_id', 'in', list(active))],
            groupby=['commercial_partner_id'],
        )
        return active - {partner.id for partner, in earlier}

    @api.model
    def _name_of(self, record):
        if not record:
            return _("Undefined")
        try:
            return record.display_name
        except AccessError:
            return _("Restricted record")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @api.model
    def _check_dashboard_access(self):
        if not self.env.user.has_group('business_pulse.group_business_pulse_user'):
            raise AccessError(_("You are not allowed to use Business Pulse."))

    @api.model
    def get_bootstrap(self):
        self._check_dashboard_access()
        settings = self._settings()
        today = self._today()
        catalog = self._kpi_catalog()
        labels = self._preset_labels()
        presets = []
        for key in PRESETS:
            entry = {'key': key, 'label': labels[key]}
            if key != 'custom':
                start, end = self._preset_range(key, today)
                entry.update(date_from=fields.Date.to_string(start), date_to=fields.Date.to_string(end))
            presets.append(entry)
        can_finance = self._can_finance()
        return {
            'today': fields.Date.to_string(today),
            'presets': presets,
            'comparisons': [
                {'key': 'previous_period', 'label': _("Previous period")},
                {'key': 'previous_year', 'label': _("Same period last year")},
                {'key': 'custom', 'label': _("Custom period")},
                {'key': 'none', 'label': _("No comparison")},
            ],
            'kpi_catalog': [
                dict(meta, key=key, available=meta['group'] != 'finance' or can_finance)
                for key, meta in catalog.items()
            ],
            'default_kpis': DEFAULT_KPIS if can_finance else DEFAULT_SALES_KPIS,
            'dimensions': [{'key': key, 'label': label} for key, label in self._dimension_labels().items()],
            'companies': [{'id': c.id, 'name': c.name} for c in self.env.companies],
            'currency_id': self.env.company.currency_id.id,
            'company_name': self.env.company.name,
            'settings': {k: settings[k] for k in ('default_preset', 'default_comparison')},
            'permissions': {
                'sales': self._can_sales(),
                'finance': can_finance,
                'configure': self.env.user.has_group('base.group_system'),
            },
            'preferences': self.env['business.pulse.preference'].get_preferences(),
        }

    @api.model
    def get_widget(self, widget, raw_filters, options=None):
        """Compute one widget. Always returns a dict with a ``status`` key."""
        if widget not in self._widget_names():
            return {'status': 'error', 'message': _("Unknown widget.")}
        try:
            self._check_dashboard_access()
            # sale.report is an SQL view: make pending ORM writes visible to it.
            self.env.flush_all()
            filters = self._parse_filters(raw_filters)
            service = self.with_context(allowed_company_ids=filters['company_ids'], tz=self._tz_name())
            handler = getattr(service, f'_widget_{widget}')
            data = handler(filters, options if isinstance(options, dict) else {})
        except AccessError:
            return {'status': 'forbidden', 'message': _("You do not have access to this information.")}
        except UserError as error:
            return {'status': 'invalid', 'message': error.args[0] if error.args else str(error)}
        except Exception:  # noqa: BLE001 - never leak tracebacks to the UI
            _logger.exception("Business Pulse: failed to compute widget %s", widget)
            return {'status': 'error', 'message': _("This section could not be loaded. Please try again.")}
        data['status'] = data.get('status', 'ok')
        data['currency_id'] = service.env.company.currency_id.id
        data['period'] = self._period_info(filters)
        return data

    @api.model
    def _widget_names(self):
        return ('kpis', 'trend', 'breakdown', 'top', 'receivables', 'attention', 'activity')

    @api.model
    def _export_names(self):
        return ('kpis', 'trend', 'breakdown', 'top', 'receivables')

    @api.model
    def get_drill_action(self, kind, raw_filters, options=None):
        """Return the records behind one chart point, using the same domains as the metric."""
        self._check_dashboard_access()
        options = options if isinstance(options, dict) else {}
        if kind != 'trend':
            raise UserError(_("Unknown drill-down."))
        self.env.flush_all()
        filters = self._parse_filters(raw_filters)
        service = self.with_context(allowed_company_ids=filters['company_ids'], tz=self._tz_name())
        return service._drill_trend(filters, options)

    @api.model
    def _drill_trend(self, filters, options):
        bucket = self._parse_date(options.get('bucket'), _("Period"))
        if not bucket:
            raise UserError(_("Select a period to open."))
        step = {'day': relativedelta(days=1), 'week': relativedelta(weeks=1),
                'month': relativedelta(months=1), 'quarter': relativedelta(months=3)}[filters['granularity']]
        start = max(bucket, filters['date_from'])
        end = min(bucket + step - timedelta(days=1), filters['date_to'])
        if start > end:
            raise UserError(_("This period is outside the selected range."))
        title = start.isoformat() if start == end else f"{start.isoformat()} → {end.isoformat()}"
        if options.get('metric') == 'revenue':
            if not self._can_finance():
                raise AccessError(_("Finance access required."))
            return self._invoices_act(_("Invoices: %s", title), self._invoice_domain(filters, start, end))
        return self._orders_act(_("Confirmed Sales: %s", title), self._order_domain(filters, start, end))

    @api.model
    def _period_info(self, filters):
        return {
            'date_from': fields.Date.to_string(filters['date_from']),
            'date_to': fields.Date.to_string(filters['date_to']),
            'cmp_from': fields.Date.to_string(filters['cmp_from']) if filters['cmp_from'] else False,
            'cmp_to': fields.Date.to_string(filters['cmp_to']) if filters['cmp_to'] else False,
            'granularity': filters['granularity'],
        }

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------
    @api.model
    def _widget_kpis(self, filters, options):
        catalog = self._kpi_catalog()
        keys = [k for k in (options.get('keys') or DEFAULT_KPIS) if k in catalog][:12]
        can_sales, can_finance = self._can_sales(), self._can_finance()
        d_from, d_to, c_from, c_to = filters['date_from'], filters['date_to'], filters['cmp_from'], filters['cmp_to']
        spark_gran = 'day' if (d_to - d_from).days <= 45 else 'week' if (d_to - d_from).days <= 200 else 'month'
        cache = {}

        def cached(key, func):
            if key not in cache:
                cache[key] = func()
            return cache[key]

        sales = lambda: cached('sales', lambda: self._sales_totals(filters, d_from, d_to))  # noqa: E731
        sales_cmp = lambda: cached('sales_cmp', lambda: c_from and self._sales_totals(filters, c_from, c_to))  # noqa: E731
        series = lambda: cached('series', lambda: self._sales_series(filters, d_from, d_to, spark_gran))  # noqa: E731
        orders_dom = self._order_domain(filters, d_from, d_to)
        receivable_dom = self._receivable_domain(filters)
        overdue_extra = [('invoice_date_due', '<', fields.Date.to_string(filters['today']))]

        def card_sales():
            cmp = sales_cmp()
            return {
                'value': sales()['amount'], 'compare': cmp and cmp['amount'],
                'spark': [amount for _b, amount, _c in series()],
                'action': self._orders_act(_("Confirmed Sales"), orders_dom),
            }

        def card_orders():
            cmp = sales_cmp()
            return {
                'value': sales()['orders'], 'compare': cmp and cmp['orders'],
                'spark': [count for _b, _a, count in series()],
                'action': self._orders_act(_("Confirmed Orders"), orders_dom),
            }

        def card_aov():
            cur, cmp = sales(), sales_cmp()
            aov = lambda s: s['amount'] / s['orders'] if s and s['orders'] else None  # noqa: E731
            return {
                'value': aov(cur), 'compare': aov(cmp) if cmp else None,
                'spark': [(a / c if c else 0.0) for _b, a, c in series()],
                'action': self._orders_act(_("Confirmed Orders"), orders_dom),
            }

        def card_conversion():
            cur = self._conversion(filters, d_from, d_to)
            cmp = c_from and self._conversion(filters, c_from, c_to)
            cohort = self._order_domain(filters, d_from, d_to, states=('draft', 'sent', 'sale', 'cancel'),
                                        date_field='create_date')
            return {
                'value': cur['rate'], 'compare': cmp['rate'] if cmp else None,
                'note': _("%(confirmed)s of %(created)s quotations confirmed", **cur),
                'action': self._orders_act(_("Quotations created in period"), cohort, group_by=['state']),
            }

        def card_open_quotations():
            (amount, count), = self.env['sale.report']._read_group(
                self._report_domain(filters, states=QUOTATION_STATES),
                aggregates=['price_subtotal:sum', 'order_reference:count_distinct'])
            return {
                'value': amount or 0.0, 'compare': None,
                'note': (_("1 open quotation") if count == 1 else _("%s open quotations", count or 0)),
                'action': self._orders_act(_("Open Quotations"),
                                           self._order_domain(filters, states=QUOTATION_STATES)),
            }

        def card_active_customers():
            cmp = sales_cmp()
            return {
                'value': sales()['customers'], 'compare': cmp and cmp['customers'],
                'action': self._orders_act(_("Orders by customer"), orders_dom, group_by=['partner_id']),
            }

        def card_new_customers():
            new = self._new_customer_ids(filters, d_from, d_to)
            cmp = self._new_customer_ids(filters, c_from, c_to) if c_from else None
            return {
                'value': len(new), 'compare': len(cmp) if cmp is not None else None,
                'action': self._act(_("New Customers"), 'res.partner', [('id', 'in', sorted(new)[:1000])]),
            }

        def card_revenue():
            return {
                'value': self._revenue_total(filters, d_from, d_to),
                'compare': self._revenue_total(filters, c_from, c_to) if c_from else None,
                'spark': [v for _b, v in self._revenue_series(filters, d_from, d_to, spark_gran)],
                'action': self._invoices_act(_("Invoices and credit notes"),
                                             self._invoice_domain(filters, d_from, d_to)),
            }

        def card_receivables():
            totals = self._receivable_totals(filters)
            return {
                'value': totals['amount'], 'compare': None,
                'note': (_("1 open invoice") if totals['count'] == 1 else _("%s open invoices", totals['count'])),
                'ignored_filters': self._ignored_filters(filters, ('product_ids', 'categ_ids')),
                'action': self._invoices_act(_("Outstanding Receivables"), receivable_dom),
            }

        def card_overdue():
            totals = self._receivable_totals(filters, overdue_extra)
            return {
                'value': totals['amount'], 'compare': None,
                'note': (_("1 overdue invoice") if totals['count'] == 1 else _("%s overdue invoices", totals['count'])),
                'ignored_filters': self._ignored_filters(filters, ('product_ids', 'categ_ids')),
                'action': self._invoices_act(_("Overdue Receivables"), receivable_dom + overdue_extra),
            }

        builders = {
            'confirmed_sales': card_sales, 'order_count': card_orders, 'avg_order_value': card_aov,
            'conversion_rate': card_conversion, 'open_quotations': card_open_quotations,
            'active_customers': card_active_customers, 'new_customers': card_new_customers,
            'invoiced_revenue': card_revenue, 'receivables': card_receivables,
            'overdue_receivables': card_overdue,
        }
        cards = []
        for key in keys:
            meta = catalog[key]
            card = {'key': key}
            allowed = can_finance if meta['group'] == 'finance' else can_sales
            if not allowed:
                card['status'] = 'forbidden'
            else:
                try:
                    card.update(builders[key]())
                    card['status'] = 'ok'
                except AccessError:
                    card['status'] = 'forbidden'
                except Exception:  # noqa: BLE001
                    _logger.exception("Business Pulse: failed to compute KPI %s", key)
                    card['status'] = 'error'
            cards.append(card)
        return {'cards': cards}

    @api.model
    def _widget_trend(self, filters, options):
        metric = options.get('metric') if options.get('metric') in ('sales', 'orders', 'revenue') else 'sales'
        gran = filters['granularity']
        d_from, d_to, c_from, c_to = filters['date_from'], filters['date_to'], filters['cmp_from'], filters['cmp_to']
        if metric == 'revenue':
            if not self._can_finance():
                raise AccessError(_("Finance access required."))
            current = self._revenue_series(filters, d_from, d_to, gran)
            compare = self._revenue_series(filters, c_from, c_to, gran) if c_from else []
            points = [(b, v) for b, v in current]
            cmp_points = [(b, v) for b, v in compare]
        else:
            idx = 1 if metric == 'sales' else 2
            current = self._sales_series(filters, d_from, d_to, gran)
            compare = self._sales_series(filters, c_from, c_to, gran) if c_from else []
            points = [(row[0], row[idx]) for row in current]
            cmp_points = [(row[0], row[idx]) for row in compare]
        total = sum(v for _b, v in points)
        return {
            'metric': metric,
            'granularity': gran,
            'labels': [fields.Date.to_string(b) for b, _v in points],
            'current': [v for _b, v in points],
            'compare_labels': [fields.Date.to_string(b) for b, _v in cmp_points],
            'compare': [v for _b, v in cmp_points],
            'total': total,
            'compare_total': sum(v for _b, v in cmp_points) if c_from else None,
            'empty': not any(points_value for _b, points_value in points),
        }

    @api.model
    def _widget_breakdown(self, filters, options):
        dimension = options.get('dimension') if options.get('dimension') in BREAKDOWN_DIMENSIONS else 'categ_id'
        report_field, order_field, _comodel = BREAKDOWN_DIMENSIONS[dimension]
        limit = 8
        Report = self.env['sale.report']
        domain = self._report_domain(filters, filters['date_from'], filters['date_to'])
        rows = Report._read_group(domain, groupby=[report_field], aggregates=['price_subtotal:sum'],
                                  order='price_subtotal:sum desc')
        total = sum(amount or 0.0 for _rec, amount in rows)
        top, rest = rows[:limit], rows[limit:]
        compare = {}
        if filters['cmp_from'] and top:
            cmp_domain = self._report_domain(filters, filters['cmp_from'], filters['cmp_to'])
            cmp_domain.append((report_field, 'in', [rec.id for rec, _a in top if rec]))
            compare = {rec.id: amount for rec, amount in Report._read_group(
                cmp_domain, groupby=[report_field], aggregates=['price_subtotal:sum'])}
        base_orders = self._order_domain(filters, filters['date_from'], filters['date_to'])
        items = []
        for record, amount in top:
            amount = amount or 0.0
            items.append({
                'id': record.id or False,
                'name': self._name_of(record),
                'value': amount,
                'compare': compare.get(record.id, 0.0) if filters['cmp_from'] else None,
                'share': amount / total if total else 0.0,
                'action': self._orders_act(self._name_of(record),
                                           base_orders + [(order_field, '=', record.id or False)]),
            })
        others = sum(amount or 0.0 for _rec, amount in rest)
        return {
            'dimension': dimension,
            'items': items,
            'others': {'value': others, 'share': others / total if total else 0.0, 'count': len(rest)}
            if rest else None,
            'total': total,
            'action': self._orders_act(_("Confirmed Sales"), base_orders),
            'empty': not rows,
        }

    @api.model
    def _widget_top(self, filters, options):
        kind = options.get('kind') if options.get('kind') in TOP_KINDS else 'products'
        field = TOP_KINDS[kind]
        limit = 10 if options.get('limit') == 10 else 5
        Report = self.env['sale.report']
        domain = self._report_domain(filters, filters['date_from'], filters['date_to'])
        (grand_total,), = Report._read_group(domain, aggregates=['price_subtotal:sum'])
        grand_total = grand_total or 0.0
        rows = Report._read_group(
            domain, groupby=[field],
            aggregates=['price_subtotal:sum', 'product_uom_qty:sum', 'order_reference:count_distinct'],
            order='price_subtotal:sum desc', limit=limit,
        )
        compare = {}
        if filters['cmp_from'] and rows:
            cmp_domain = self._report_domain(filters, filters['cmp_from'], filters['cmp_to'])
            cmp_domain.append((field, 'in', [rec.id for rec, *_rest in rows if rec]))
            compare = {rec.id: amount for rec, amount in Report._read_group(
                cmp_domain, groupby=[field], aggregates=['price_subtotal:sum'])}
        base_orders = self._order_domain(filters, filters['date_from'], filters['date_to'])
        order_field = BREAKDOWN_DIMENSIONS[field][1]
        items = []
        for rank, (record, amount, qty, orders) in enumerate(rows, start=1):
            amount = amount or 0.0
            item = {
                'rank': rank,
                'id': record.id or False,
                'name': self._name_of(record),
                'value': amount,
                'orders': orders or 0,
                'compare': compare.get(record.id, 0.0) if filters['cmp_from'] else None,
                'share': amount / grand_total if grand_total else 0.0,
                'action': self._orders_act(self._name_of(record),
                                           base_orders + [(order_field, '=', record.id or False)]),
            }
            if kind == 'products':
                item['quantity'] = qty or 0.0
                item['uom'] = record.uom_id.name if record else ''
            items.append(item)
        return {'kind': kind, 'items': items, 'total': grand_total, 'empty': not rows}

    @api.model
    def _widget_receivables(self, filters, options):
        if not self._can_finance():
            raise AccessError(_("Finance access required."))
        today = filters['today']
        base = self._receivable_domain(filters)

        def due(days):
            return fields.Date.to_string(today - timedelta(days=days))

        buckets_def = [
            ('not_due', _("Not yet due"), ['|', ('invoice_date_due', '>=', due(0)), ('invoice_date_due', '=', False)]),
            ('1_30', _("1–30 days"), [('invoice_date_due', '<', due(0)), ('invoice_date_due', '>=', due(30))]),
            ('31_60', _("31–60 days"), [('invoice_date_due', '<', due(30)), ('invoice_date_due', '>=', due(60))]),
            ('61_90', _("61–90 days"), [('invoice_date_due', '<', due(60)), ('invoice_date_due', '>=', due(90))]),
            ('90_plus', _("Over 90 days"), [('invoice_date_due', '<', due(90))]),
        ]
        buckets = []
        for key, label, extra in buckets_def:
            totals = self._receivable_totals(filters, extra)
            buckets.append({
                'key': key, 'label': label, 'value': totals['amount'], 'count': totals['count'],
                'action': self._invoices_act(_("Receivables: %s", label), base + extra),
            })
        total = sum(b['value'] for b in buckets)
        overdue_extra = [('invoice_date_due', '<', due(0))]
        overdue = sum(b['value'] for b in buckets[1:])
        # Customers with the largest overdue balance
        rows = self.env['account.move']._read_group(
            base + overdue_extra, groupby=['commercial_partner_id', 'company_id'],
            aggregates=['amount_residual_signed:sum'],
        )
        per_partner = {}
        for partner, company, amount in rows:
            per_partner.setdefault(partner, []).append((company, amount))
        debtors = sorted(
            ((partner, self._convert_by_company(values)) for partner, values in per_partner.items()),
            key=lambda item: item[1], reverse=True,
        )[:5]
        return {
            'as_of': fields.Date.to_string(today),
            'total': total,
            'overdue': overdue,
            'overdue_share': overdue / total if total else 0.0,
            'buckets': buckets,
            'debtors': [{
                'id': partner.id, 'name': self._name_of(partner), 'value': amount,
                'action': self._invoices_act(self._name_of(partner),
                                             base + overdue_extra + [('commercial_partner_id', '=', partner.id)]),
            } for partner, amount in debtors],
            'ignored_filters': self._ignored_filters(filters, ('product_ids', 'categ_ids')),
            'action': self._invoices_act(_("Outstanding Receivables"), base),
            'empty': not total and not any(b['count'] for b in buckets),
        }

    @api.model
    def _widget_attention(self, filters, options):
        settings = self._settings()
        today = filters['today']
        items = []
        if self._can_sales():
            Order = self.env['sale.order']
            open_quotes = self._order_domain(filters, states=QUOTATION_STATES)
            horizon = fields.Date.to_string(today + timedelta(days=settings['expiring_days']))
            expiring = open_quotes + [('validity_date', '>=', fields.Date.to_string(today)),
                                      ('validity_date', '<=', horizon)]
            (count, amount), = Order._read_group(expiring, aggregates=['__count', 'amount_untaxed:sum'])
            if count:
                items.append({
                    'key': 'expiring_quotations', 'severity': 'warning',
                    'title': (_("1 quotation expires within %s days", settings['expiring_days']) if count == 1
                              else _("%s quotations expire within %s days", count, settings['expiring_days'])),
                    'explanation': _("Follow up before they lapse to protect the pipeline."),
                    'count': count, 'value': None,
                    'next_step': _("Review expiring quotations"),
                    'action': self._orders_act(_("Expiring Quotations"), expiring),
                })
            expired = open_quotes + [('validity_date', '<', fields.Date.to_string(today))]
            count = Order.search_count(expired)
            if count:
                items.append({
                    'key': 'expired_quotations', 'severity': 'info',
                    'title': (_("1 open quotation has expired") if count == 1
                              else _("%s open quotations have expired", count)),
                    'explanation': _("They are still open past their expiration date. Renew or cancel them "
                                     "to keep the pipeline accurate."),
                    'count': count, 'value': None,
                    'next_step': _("Clean up expired quotations"),
                    'action': self._orders_act(_("Expired Quotations"), expired),
                })
            stale_limit, _end = self._utc_bounds(today - timedelta(days=settings['stale_days']), today)
            stale = self._order_domain(filters, states=('sent',)) + [('date_order', '<', stale_limit)]
            count = Order.search_count(stale)
            if count:
                items.append({
                    'key': 'stale_quotations', 'severity': 'info',
                    'title': (_("1 sent quotation is older than %s days", settings['stale_days']) if count == 1
                              else _("%s sent quotations are older than %s days", count, settings['stale_days'])),
                    'explanation': _("No decision yet. A quick follow-up often unblocks them."),
                    'count': count, 'value': None,
                    'next_step': _("Follow up stalled quotations"),
                    'action': self._orders_act(_("Stalled Quotations"), stale),
                })
            if filters['cmp_from'] and settings['sales_drop_threshold']:
                cur = self._sales_totals(filters, filters['date_from'], filters['date_to'])['amount']
                cmp = self._sales_totals(filters, filters['cmp_from'], filters['cmp_to'])['amount']
                if cmp > 0 and (cur - cmp) / cmp * 100 <= -settings['sales_drop_threshold']:
                    items.append({
                        'key': 'sales_drop', 'severity': 'critical',
                        'title': _("Confirmed sales are down %s%% versus the comparison period",
                                   round((cmp - cur) / cmp * 100)),
                        'explanation': _("Check the breakdown to see which category, product or "
                                         "salesperson drives the decline."),
                        'count': None, 'value': cur - cmp,
                        'next_step': _("Open confirmed sales"),
                        'action': self._orders_act(_("Confirmed Sales"), self._order_domain(
                            filters, filters['date_from'], filters['date_to'])),
                    })
        if self._can_finance():
            base = self._receivable_domain(filters)
            severe_extra = [('invoice_date_due', '<', fields.Date.to_string(today - timedelta(days=90)))]
            severe = self._receivable_totals(filters, severe_extra)
            if severe['count']:
                items.append({
                    'key': 'overdue_90', 'severity': 'critical',
                    'title': (_("1 invoice is more than 90 days overdue") if severe['count'] == 1
                              else _("%s invoices are more than 90 days overdue", severe['count'])),
                    'explanation': _("Long-overdue balances are the hardest to collect."),
                    'count': severe['count'], 'value': severe['amount'],
                    'next_step': _("Start collection on these invoices"),
                    'action': self._invoices_act(_("Over 90 days overdue"), base + severe_extra),
                })
            overdue_extra = [('invoice_date_due', '<', fields.Date.to_string(today))]
            overdue = self._receivable_totals(filters, overdue_extra)
            if overdue['count'] and overdue['count'] != severe['count']:
                items.append({
                    'key': 'overdue', 'severity': 'warning',
                    'title': (_("1 customer invoice is overdue") if overdue['count'] == 1
                              else _("%s customer invoices are overdue", overdue['count'])),
                    'explanation': _("Send reminders to keep cash flowing."),
                    'count': overdue['count'], 'value': overdue['amount'],
                    'next_step': _("Review overdue invoices"),
                    'action': self._invoices_act(_("Overdue Receivables"), base + overdue_extra),
                })
        order = {'critical': 0, 'warning': 1, 'info': 2}
        items.sort(key=lambda item: order[item['severity']])
        return {'items': items, 'empty': not items}

    @api.model
    def _widget_activity(self, filters, options):
        events = []
        company_domain = [('company_id', 'in', filters['company_ids'])]
        if self._can_sales():
            Order = self.env['sale.order']
            for order in Order.search(company_domain + [('state', '=', 'sale')], order='date_order desc', limit=8):
                events.append({
                    'type': 'order', 'icon': 'fa-check-circle', 'label': _("Order confirmed"),
                    'title': order.name, 'partner': self._name_of(order.partner_id),
                    'amount': order.amount_untaxed, 'currency_id': order.currency_id.id,
                    'when': fields.Datetime.to_string(order.date_order),
                    'res_model': 'sale.order', 'res_id': order.id,
                })
            for order in Order.search(company_domain + [('state', 'in', list(QUOTATION_STATES))],
                                      order='create_date desc', limit=6):
                events.append({
                    'type': 'quotation', 'icon': 'fa-pencil-square-o', 'label': _("New quotation"),
                    'title': order.name, 'partner': self._name_of(order.partner_id),
                    'amount': order.amount_untaxed, 'currency_id': order.currency_id.id,
                    'when': fields.Datetime.to_string(order.create_date),
                    'res_model': 'sale.order', 'res_id': order.id,
                })
        if self._can_finance():
            Move = self.env['account.move']
            for move in Move.search(company_domain + [('move_type', 'in', list(INVOICE_TYPES)),
                                                      ('state', '=', 'posted')],
                                    order='invoice_date desc, id desc', limit=6):
                events.append({
                    'type': 'invoice', 'icon': 'fa-file-text',
                    'label': _("Credit note posted") if move.move_type == 'out_refund' else _("Invoice posted"),
                    'title': move.name, 'partner': self._name_of(move.partner_id),
                    'amount': move.amount_untaxed_signed if move.move_type == 'out_refund' else move.amount_untaxed,
                    'currency_id': move.currency_id.id,
                    'when': fields.Date.to_string(move.invoice_date),
                    'res_model': 'account.move', 'res_id': move.id,
                })
            if self.env['account.payment'].has_access('read'):
                for payment in self.env['account.payment'].search(
                        company_domain + [('payment_type', '=', 'inbound'), ('partner_type', '=', 'customer'),
                                          ('state', 'in', ('in_process', 'paid'))],
                        order='date desc, id desc', limit=6):
                    events.append({
                        'type': 'payment', 'icon': 'fa-money', 'label': _("Payment received"),
                        'title': payment.name, 'partner': self._name_of(payment.partner_id),
                        'amount': payment.amount, 'currency_id': payment.currency_id.id,
                        'when': fields.Date.to_string(payment.date),
                        'res_model': 'account.payment', 'res_id': payment.id,
                    })
        events.sort(key=lambda e: e['when'] or '', reverse=True)
        return {'events': events[:12], 'empty': not events}

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    @api.model
    def _export_options(self, widget, options):
        if widget == 'kpis':
            return dict(options, keys=options.get('keys') or DEFAULT_KPIS)
        if widget == 'top':
            return dict(options, limit=10)
        return options

    @api.model
    def get_export(self, widget, raw_filters, options=None):
        """Return a typed, permission-checked table for a widget.

        ``columns`` is a list of ``(header, kind)`` where kind is one of
        ``text``, ``money``, ``count``, ``number``, ``percent`` (ratio 0-1)
        or ``date``; CSV and XLSX writers format cells from it.
        """
        if widget not in self._export_names():
            raise UserError(_("This section cannot be exported."))
        options = self._export_options(widget, options if isinstance(options, dict) else {})
        data = self.get_widget(widget, raw_filters, options)
        if data.get('status') != 'ok':
            raise UserError(data.get('message') or _("This report cannot be exported."))
        currency = self.env['res.currency'].browse(data['currency_id'])
        period = data['period']
        title, columns, rows = self._export_table(widget, data, options)
        rows = [[self._export_cell(value, kind, currency) for value, (_h, kind) in zip(row, columns)]
                for row in rows[:self._settings()['export_limit']]]
        has_cmp = bool(period['cmp_from'])
        companies = self.env['res.company'].browse(self._parse_filters(raw_filters)['company_ids'])
        meta = [
            (_("Report"), title),
            (_("Company"), ', '.join(companies.mapped('name'))),
            (_("Period"), f"{period['date_from']} → {period['date_to']}"),
            (_("Comparison"), f"{period['cmp_from']} → {period['cmp_to']}" if has_cmp else _("None")),
            (_("Currency"), currency.name),
            (_("Generated"), fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now()))),
        ]
        return {
            'title': title, 'meta': meta,
            'headers': [header for header, _kind in columns],
            'kinds': [kind for _header, kind in columns],
            'rows': rows,
            'currency': {'name': currency.name, 'symbol': currency.symbol, 'position': currency.position,
                         'decimals': currency.decimal_places},
        }

    @api.model
    def _export_cell(self, value, kind, currency):
        if value is None or value is False:
            return ''
        if kind == 'money' and isinstance(value, (int, float)):
            return currency.round(value)
        if kind in ('percent', 'number') and isinstance(value, float):
            return round(value, 4)
        return value

    @api.model
    def _export_table(self, widget, data, options):
        """Return ``(title, columns, rows)`` for an exportable widget."""
        catalog = self._kpi_catalog()
        has_cmp = bool(data['period']['cmp_from'])

        def diff(value, compare):
            return None if value is None or compare is None else value - compare

        if widget == 'kpis':
            # values of different kinds share a column: one row per metric with its own unit
            columns = [(_("Metric"), 'text'), (_("Value"), 'number'), (_("Comparison"), 'number'),
                       (_("Change"), 'number'), (_("Unit"), 'text'), (_("Definition"), 'text')]
            units = {'monetary': self.env['res.currency'].browse(data['currency_id']).name,
                     'count': _("count"), 'rate': _("ratio (0-1)")}
            rows = []
            for card in data['cards']:
                if card['status'] != 'ok':
                    continue
                meta = catalog[card['key']]
                rows.append([meta['label'], card.get('value'), card.get('compare'),
                             diff(card.get('value'), card.get('compare')), units[meta['kind']],
                             meta['definition']])
            return _("KPI Summary"), columns, rows
        if widget == 'trend':
            kind = 'count' if data['metric'] == 'orders' else 'money'
            columns = [(_("Period start"), 'date'), (_("Value"), kind)]
            if has_cmp:
                columns += [(_("Comparison start"), 'date'), (_("Comparison value"), kind)]
            rows = []
            for i, label in enumerate(data['labels']):
                row = [label, data['current'][i]]
                if has_cmp:
                    row += [data['compare_labels'][i] if i < len(data['compare_labels']) else None,
                            data['compare'][i] if i < len(data['compare']) else None]
                rows.append(row)
            return _("Sales Trend"), columns, rows
        if widget == 'breakdown':
            columns = [(_("Name"), 'text'), (_("Confirmed sales"), 'money'), (_("Share"), 'percent')]
            if has_cmp:
                columns += [(_("Comparison"), 'money'), (_("Change"), 'money')]
            rows = []
            for item in data['items']:
                row = [item['name'], item['value'], item['share']]
                if has_cmp:
                    row += [item['compare'], diff(item['value'], item['compare'])]
                rows.append(row)
            if data.get('others'):
                rows.append([_("Others"), data['others']['value'], data['others']['share']] + ([None, None] if has_cmp else []))
            return _("Sales by %s", self._dimension_labels()[data['dimension']]), columns, rows
        if widget == 'top':
            columns = [(_("Rank"), 'count'), (_("Name"), 'text'), (_("Confirmed sales"), 'money'),
                       (_("Orders"), 'count'), (_("Share"), 'percent')]
            if data['kind'] == 'products':
                columns += [(_("Quantity"), 'number'), (_("Unit"), 'text')]
            if has_cmp:
                columns += [(_("Comparison"), 'money'), (_("Change"), 'money')]
            rows = []
            for item in data['items']:
                row = [item['rank'], item['name'], item['value'], item['orders'], item['share']]
                if data['kind'] == 'products':
                    row += [item['quantity'], item['uom']]
                if has_cmp:
                    row += [item['compare'], diff(item['value'], item['compare'])]
                rows.append(row)
            labels = {'products': _("Top Products"), 'customers': _("Top Customers"),
                      'salespeople': _("Top Salespeople")}
            return labels[data['kind']], columns, rows
        if widget == 'receivables':
            columns = [(_("Bucket"), 'text'), (_("Amount"), 'money'), (_("Invoices"), 'count')]
            rows = [[b['label'], b['value'], b['count']] for b in data['buckets']]
            rows.append([_("Total"), data['total'], sum(b['count'] for b in data['buckets'])])
            return _("Receivables Aging"), columns, rows
        raise UserError(_("This section cannot be exported."))
