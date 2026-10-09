# -*- coding: utf-8 -*-
"""Sales Analytics widgets: quotation funnel, quotation aging, salesperson
performance and target progress. Same rules as the overview service: the ORM
in the user's environment, validated filters, documented definitions."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .business_pulse_dashboard import QUOTATION_STATES, SALE_DONE_STATES
from .business_pulse_target import elapsed_fraction

COHORT_STATES = ('draft', 'sent', 'sale', 'cancel')
AGE_BUCKETS = [
    ('0_7', 0, 7),
    ('8_30', 8, 30),
    ('31_90', 31, 90),
    ('90_plus', 91, None),
]


class BusinessPulseDashboard(models.AbstractModel):
    _inherit = 'business.pulse.dashboard'

    @api.model
    def _widget_names(self):
        return super()._widget_names() + ('funnel', 'quotations', 'salespeople', 'targets')

    @api.model
    def _export_names(self):
        return super()._export_names() + ('quotations', 'salespeople', 'targets')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _order_amounts(self, domain, groupby):
        """Untaxed order totals grouped by ``groupby``, converted to the active
        company currency (sale.order amounts are in the order currency)."""
        rows = self.env['sale.order']._read_group(
            domain, groupby=list(groupby) + ['currency_id'], aggregates=['amount_untaxed:sum', '__count'])
        target = self.env.company.currency_id
        today = fields.Date.context_today(self)
        result = {}
        for *keys, currency, amount, count in rows:
            key = tuple(keys) if len(keys) > 1 else keys[0]
            amount = amount or 0.0
            if currency and currency != target:
                amount = currency._convert(amount, target, self.env.company, today)
            total, total_count = result.get(key, (0.0, 0))
            result[key] = (total + amount, total_count + count)
        return result

    @api.model
    def _cohort_domain(self, filters, date_from, date_to):
        return self._order_domain(filters, date_from, date_to, states=COHORT_STATES, date_field='create_date')

    # ------------------------------------------------------------------
    # Quotation funnel (cohort of quotations created in the period)
    # ------------------------------------------------------------------
    @api.model
    def _funnel_stats(self, filters, date_from, date_to):
        by_state = self._order_amounts(self._cohort_domain(filters, date_from, date_to), ['state'])

        def get(*states):
            return (sum(by_state.get(s, (0.0, 0))[0] for s in states),
                    sum(by_state.get(s, (0.0, 0))[1] for s in states))

        created = get(*COHORT_STATES)
        return {
            'created': created, 'confirmed': get('sale'), 'open': get('draft', 'sent'),
            'sent': get('sent'), 'draft': get('draft'), 'cancelled': get('cancel'),
            'rate': get('sale')[1] / created[1] if created[1] else None,
        }

    @api.model
    def _widget_funnel(self, filters, options):
        d_from, d_to = filters['date_from'], filters['date_to']
        cur = self._funnel_stats(filters, d_from, d_to)
        cmp = self._funnel_stats(filters, filters['cmp_from'], filters['cmp_to']) if filters['cmp_from'] else None
        cohort = self._cohort_domain(filters, d_from, d_to)

        def stage(key, label, states, help_text):
            amount, count = cur[key]
            return {
                'key': key, 'label': label, 'count': count, 'value': amount, 'help': help_text,
                'share': count / cur['created'][1] if cur['created'][1] else 0.0,
                'action': self._orders_act(label, [d for d in cohort if d[0] != 'state']
                                           + [('state', 'in', list(states))]),
            }

        # Average days from creation to confirmation (date_order is set on confirmation)
        confirmed = self.env['sale.order'].search_fetch(
            [d for d in cohort if d[0] != 'state'] + [('state', '=', 'sale')], ['create_date', 'date_order'],
            limit=20000)
        delays = [(o.date_order - o.create_date).total_seconds() / 86400 for o in confirmed
                  if o.date_order and o.create_date and o.date_order >= o.create_date]
        return {
            'stages': [
                stage('created', _("Quotations created"), COHORT_STATES,
                      _("All quotations created in the period, whatever their status today.")),
                stage('confirmed', _("Confirmed"), ('sale',), _("Now a confirmed sales order.")),
                stage('open', _("Still open"), QUOTATION_STATES, _("Not decided yet (Quotation or Quotation Sent).")),
                stage('cancelled', _("Cancelled"), ('cancel',), _("Cancelled or lost.")),
            ],
            'sent_open': cur['sent'][1],
            'rate': cur['rate'],
            'compare_rate': cmp['rate'] if cmp else None,
            'avg_days_to_confirm': sum(delays) / len(delays) if delays else None,
            'empty': not cur['created'][1],
        }

    # ------------------------------------------------------------------
    # Open quotations: aging, expiry and high-value list (snapshot)
    # ------------------------------------------------------------------
    @api.model
    def _widget_quotations(self, filters, options):
        today = filters['today']
        settings = self._settings()
        base = self._order_domain(filters, states=QUOTATION_STATES)
        buckets = []
        for key, low, high in AGE_BUCKETS:
            # age = days since the quotation date, in the user's timezone
            newest = today - timedelta(days=low)
            domain = list(base)
            _start, end = self._utc_bounds(newest, newest)
            domain.append(('date_order', '<', end))
            if high is not None:
                start, _end = self._utc_bounds(today - timedelta(days=high), today)
                domain.append(('date_order', '>=', start))
            amount, count = self._sum_orders(domain)
            label = {'0_7': _("0–7 days"), '8_30': _("8–30 days"), '31_90': _("31–90 days"),
                     '90_plus': _("Over 90 days")}[key]
            buckets.append({'key': key, 'label': label, 'value': amount, 'count': count,
                            'action': self._orders_act(_("Open quotations: %s", label), domain)})
        total_value = sum(b['value'] for b in buckets)
        total_count = sum(b['count'] for b in buckets)
        today_s = fields.Date.to_string(today)
        horizon = fields.Date.to_string(today + timedelta(days=settings['expiring_days']))
        expiring_dom = base + [('validity_date', '>=', today_s), ('validity_date', '<=', horizon)]
        expired_dom = base + [('validity_date', '<', today_s)]
        expiring = self._sum_orders(expiring_dom)
        expired = self._sum_orders(expired_dom)
        top = self.env['sale.order'].search(base, order='amount_untaxed desc, id desc', limit=5)
        return {
            'total': total_value,
            'count': total_count,
            'buckets': buckets,
            'expiring': {'value': expiring[0], 'count': expiring[1], 'days': settings['expiring_days'],
                         'action': self._orders_act(_("Expiring Quotations"), expiring_dom)},
            'expired': {'value': expired[0], 'count': expired[1],
                        'action': self._orders_act(_("Expired Quotations"), expired_dom)},
            'top': [{
                'id': order.id, 'name': order.name,
                'partner': self._name_of(order.partner_id),
                'user': self._name_of(order.user_id) if order.user_id else '',
                'amount': order.amount_untaxed, 'currency_id': order.currency_id.id,
                'state': order.state,
                'age': (today - fields.Datetime.context_timestamp(self, order.date_order).date()).days
                if order.date_order else None,
                'validity_date': fields.Date.to_string(order.validity_date) if order.validity_date else False,
                'expired': bool(order.validity_date and order.validity_date < today),
            } for order in top],
            'action': self._orders_act(_("Open Quotations"), base),
            'empty': not total_count,
        }

    @api.model
    def _sum_orders(self, domain):
        amount = count = 0
        for value, number in self._order_amounts(domain, ['company_id']).values():
            amount += value
            count += number
        return amount, count

    # ------------------------------------------------------------------
    # Salesperson performance
    # ------------------------------------------------------------------
    @api.model
    def _widget_salespeople(self, filters, options):
        d_from, d_to = filters['date_from'], filters['date_to']
        Report = self.env['sale.report']
        rows = Report._read_group(
            self._report_domain(filters, d_from, d_to), groupby=['user_id'],
            aggregates=['price_subtotal:sum', 'order_reference:count_distinct'],
            order='price_subtotal:sum desc', limit=50)
        compare = {}
        if filters['cmp_from']:
            compare = {user.id: amount for user, amount in Report._read_group(
                self._report_domain(filters, filters['cmp_from'], filters['cmp_to']),
                groupby=['user_id'], aggregates=['price_subtotal:sum'])}
        cohort = {}
        for (user, state), (_amount, count) in self._order_amounts(
                self._cohort_domain(filters, d_from, d_to), ['user_id', 'state']).items():
            created, confirmed = cohort.get(user.id, (0, 0))
            cohort[user.id] = (created + count, confirmed + (count if state == 'sale' else 0))
        pipeline = {user.id: value for user, (value, _c) in self._order_amounts(
            self._order_domain(filters, states=QUOTATION_STATES), ['user_id']).items()}
        targets = self._user_targets(filters, [user.id for user, *_r in rows if user])
        total = sum(amount or 0.0 for _u, amount, _c in rows)
        base_orders = self._order_domain(filters, d_from, d_to)
        items = []
        for user, amount, orders in rows:
            amount = amount or 0.0
            created, confirmed = cohort.get(user.id, (0, 0))
            items.append({
                'id': user.id or False,
                'name': self._name_of(user) if user else _("Unassigned"),
                'value': amount,
                'orders': orders or 0,
                'aov': amount / orders if orders else None,
                'conversion': confirmed / created if created else None,
                'quotations': created,
                'pipeline': pipeline.get(user.id, 0.0),
                'share': amount / total if total else 0.0,
                'compare': compare.get(user.id, 0.0) if filters['cmp_from'] else None,
                'target': targets.get(user.id),
                'action': self._orders_act(self._name_of(user) if user else _("Unassigned"),
                                           base_orders + [('user_id', '=', user.id or False)]),
            })
        return {'items': items, 'total': total, 'empty': not items}

    @api.model
    def _user_targets(self, filters, user_ids):
        """Confirmed-sales target per salesperson that covers the end of the
        selected period (most recent first)."""
        if not user_ids:
            return {}
        end = fields.Date.to_string(filters['date_to'])
        targets = self.env['business.pulse.target'].search([
            ('scope', '=', 'user'), ('user_id', 'in', user_ids), ('metric', '=', 'confirmed_sales'),
            ('company_id', 'in', filters['company_ids']),
            ('date_from', '<=', end), ('date_to', '>=', end),
        ], order='date_from desc')
        result = {}
        for target in targets:
            if target.user_id.id not in result:
                result[target.user_id.id] = self._target_progress(target, filters['today'])
        return result

    # ------------------------------------------------------------------
    # Targets
    # ------------------------------------------------------------------
    @api.model
    def _target_progress(self, target, today):
        """Progress of one target, measured with the matching KPI definition
        over the target's own dates, in the target company's currency."""
        if target.company_id not in self.env.user.company_ids:
            raise AccessError(_("You cannot access this target's company."))
        service = self.with_context(allowed_company_ids=[target.company_id.id])
        scope_filters = {
            'company_ids': target.company_id.ids,
            'team_ids': target.team_id.ids if target.scope == 'team' else [],
            'user_ids': target.user_id.ids if target.scope == 'user' else [],
            'partner_ids': [], 'product_ids': [], 'categ_ids': [],
            'today': today,
        }
        start, end = target.date_from, target.date_to
        measured_to = min(end, today)
        if today < start:
            actual = 0.0
        elif target.metric == 'invoiced_revenue':
            if not service._can_finance():
                raise AccessError(_("Finance access required."))
            actual = service._revenue_total(scope_filters, start, measured_to)
        else:
            totals = service._sales_totals(scope_filters, start, measured_to)
            actual = totals['amount'] if target.metric == 'confirmed_sales' else totals['orders']
        fraction = elapsed_fraction(start, end, today) if today >= start else 0.0
        expected = target.amount * fraction
        completion = actual / target.amount if target.amount else 0.0
        if today < start:
            status = 'upcoming'
        elif actual >= target.amount:
            status = 'achieved'
        elif today > end:
            status = 'missed'
        elif actual >= expected:
            status = 'on_track'
        else:
            status = 'behind'
        if target.metric == 'invoiced_revenue':
            action = service._invoices_act(target.name, service._invoice_domain(scope_filters, start, end))
        else:
            action = service._orders_act(target.name, service._order_domain(scope_filters, start, end))
        return {
            'id': target.id,
            'name': target.name,
            'metric': target.metric,
            'kind': 'count' if target.metric == 'order_count' else 'monetary',
            'scope': target.scope,
            'scope_label': target._scope_label(),
            'date_from': fields.Date.to_string(start),
            'date_to': fields.Date.to_string(end),
            'amount': target.amount,
            'actual': actual,
            'expected': expected,
            'remaining': max(target.amount - actual, 0.0),
            'completion': completion,
            'elapsed': fraction,
            'status': status,
            'currency_id': target.currency_id.id,
            'action': action,
        }

    @api.model
    def _widget_targets(self, filters, options):
        Target = self.env['business.pulse.target']
        domain = [
            ('company_id', 'in', filters['company_ids']),
            ('date_from', '<=', fields.Date.to_string(filters['date_to'])),
            ('date_to', '>=', fields.Date.to_string(filters['date_from'])),
        ]
        if not self._can_finance():
            domain.append(('metric', '!=', 'invoiced_revenue'))
        if filters['user_ids'] or filters['team_ids']:
            domain += ['|', '|', ('scope', '=', 'company'),
                       '&', ('scope', '=', 'team'), ('team_id', 'in', filters['team_ids'] or [0]),
                       '&', ('scope', '=', 'user'), ('user_id', 'in', filters['user_ids'] or [0])]
        targets = Target.search(domain, order='scope, date_to desc, id', limit=20)
        items = []
        for target in targets:
            try:
                items.append(self._target_progress(target, filters['today']))
            except AccessError:
                continue
        return {
            'items': items,
            'can_manage': Target.has_access('create'),
            'empty': not items,
        }

    # ------------------------------------------------------------------
    # Export tables
    # ------------------------------------------------------------------
    @api.model
    def _export_table(self, widget, data, options):
        if widget == 'salespeople':
            columns = [(_("Salesperson"), 'text'), (_("Confirmed sales"), 'money'), (_("Orders"), 'count'),
                       (_("Average order value"), 'money'), (_("Conversion"), 'percent'),
                       (_("Quotations created"), 'count'), (_("Open pipeline"), 'money'), (_("Share"), 'percent'),
                       (_("Comparison"), 'money'), (_("Target"), 'money'), (_("Target completion"), 'percent')]
            rows = [[i['name'], i['value'], i['orders'], i['aov'], i['conversion'], i['quotations'],
                     i['pipeline'], i['share'], i['compare'],
                     i['target']['amount'] if i['target'] else None,
                     i['target']['completion'] if i['target'] else None] for i in data['items']]
            return _("Salesperson Performance"), columns, rows
        if widget == 'quotations':
            columns = [(_("Age"), 'text'), (_("Open value"), 'money'), (_("Quotations"), 'count')]
            rows = [[b['label'], b['value'], b['count']] for b in data['buckets']]
            rows.append([_("Total"), data['total'], data['count']])
            return _("Open Quotations by Age"), columns, rows
        if widget == 'targets':
            columns = [(_("Target"), 'text'), (_("Applies to"), 'text'), (_("Metric"), 'text'),
                       (_("Start"), 'date'), (_("End"), 'date'), (_("Target value"), 'number'),
                       (_("Actual"), 'number'), (_("Completion"), 'percent'), (_("Expected to date"), 'number'),
                       (_("Status"), 'text')]
            metrics = dict(self.env['business.pulse.target']._fields['metric']._description_selection(self.env))
            statuses = self._target_status_labels()
            rows = [[t['name'], t['scope_label'], metrics.get(t['metric']), t['date_from'], t['date_to'],
                     t['amount'], t['actual'], t['completion'], t['expected'], statuses[t['status']]]
                    for t in data['items']]
            return _("Targets"), columns, rows
        return super()._export_table(widget, data, options)

    @api.model
    def _target_status_labels(self):
        return {
            'achieved': _("Achieved"), 'on_track': _("On track"), 'behind': _("Behind"),
            'missed': _("Missed"), 'upcoming': _("Not started"),
        }
