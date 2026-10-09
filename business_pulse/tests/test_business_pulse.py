# -*- coding: utf-8 -*-
from datetime import date

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BusinessPulseCase


@tagged('post_install', '-at_install')
class TestBusinessPulse(BusinessPulseCase):

    # ------------------------------------------------------------------
    def test_confirmed_sales_orders_and_aov(self):
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-05')               # 200
        self._order(self.customer_b, [(self.product_y, 4)], '2026-03-20')               # 200
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-25', confirm=False)  # quotation
        self._order(self.customer_a, [(self.product_x, 9)], '2026-04-02')               # outside
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'),
                            ['confirmed_sales', 'order_count', 'avg_order_value', 'active_customers'])
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 400.0)
        self.assertEqual(cards['order_count']['value'], 2)
        self.assertAlmostEqual(cards['avg_order_value']['value'], 200.0)
        self.assertEqual(cards['active_customers']['value'], 2)
        self.assertIsNone(cards['confirmed_sales']['compare'])

    def test_cancelled_orders_excluded(self):
        order = self._order(self.customer_a, [(self.product_x, 3)], '2026-03-05')
        order._action_cancel()
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'), ['confirmed_sales', 'order_count'])
        self.assertEqual(cards['confirmed_sales']['value'], 0.0)
        self.assertEqual(cards['order_count']['value'], 0)

    def test_previous_period_and_year_comparison(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-02-10')  # 100 previous period
        self._order(self.customer_a, [(self.product_x, 3)], '2026-03-10')  # 300 current
        self._order(self.customer_a, [(self.product_x, 5)], '2025-03-10')  # 500 previous year
        cards = self._cards(self._custom('2026-03-01', '2026-03-31', comparison='previous_period'), ['confirmed_sales'])
        # March has 31 days: the previous period is the 31 days before (Jan 29 - Feb 28)
        self.assertAlmostEqual(cards['confirmed_sales']['compare'], 100.0)
        cards = self._cards(self._custom('2026-03-01', '2026-03-31', comparison='previous_year'), ['confirmed_sales'])
        self.assertAlmostEqual(cards['confirmed_sales']['compare'], 500.0)

    @freeze_time('2026-03-15')
    def test_month_to_date_compares_same_elapsed_days(self):
        filters = self.Dashboard._parse_filters({'preset': 'this_month', 'comparison': 'previous_period'})
        self.assertEqual(filters['date_from'], date(2026, 3, 1))
        self.assertEqual(filters['date_to'], date(2026, 3, 15))
        self.assertEqual(filters['cmp_from'], date(2026, 2, 1))
        self.assertEqual(filters['cmp_to'], date(2026, 2, 15))
        filters = self.Dashboard._parse_filters({'preset': 'last_month', 'comparison': 'previous_period'})
        self.assertEqual((filters['date_from'], filters['date_to']), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual((filters['cmp_from'], filters['cmp_to']), (date(2026, 1, 1), date(2026, 1, 31)))

    @freeze_time('2026-03-31')
    def test_month_to_date_comparison_is_clamped(self):
        filters = self.Dashboard._parse_filters({'preset': 'this_month', 'comparison': 'previous_period'})
        self.assertEqual((filters['cmp_from'], filters['cmp_to']), (date(2026, 2, 1), date(2026, 2, 28)))

    def test_conversion_rate_uses_creation_cohort(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-02')
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-03', confirm=False)
        self._order(self.customer_b, [(self.product_x, 1)], '2026-03-04', confirm=False)
        self._order(self.customer_b, [(self.product_x, 1)], '2026-03-05')
        self._order(self.customer_b, [(self.product_x, 1)], '2026-04-05')  # other cohort
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'), ['conversion_rate'])
        self.assertAlmostEqual(cards['conversion_rate']['value'], 0.5)

    def test_dimension_filters(self):
        self._order(self.customer_a, [(self.product_x, 1), (self.product_y, 2)], '2026-03-05')
        self._order(self.customer_b, [(self.product_y, 1)], '2026-03-06')
        cards = self._cards(self._custom('2026-03-01', '2026-03-31', categ_ids=[self.categ_x.id]),
                            ['confirmed_sales', 'order_count'])
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 100.0)
        self.assertEqual(cards['order_count']['value'], 1)
        # drill-down domain returns exactly the orders behind the metric
        orders = self.env['sale.order'].search(cards['order_count']['action']['domain'])
        self.assertEqual(len(orders), 1)
        cards = self._cards(self._custom('2026-03-01', '2026-03-31', partner_ids=[self.customer_b.id]),
                            ['confirmed_sales'])
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 50.0)

    def test_new_customers(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-01-10')
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-10')
        self._order(self.customer_b, [(self.product_x, 1)], '2026-03-11')
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'), ['new_customers', 'active_customers'])
        self.assertEqual(cards['active_customers']['value'], 2)
        self.assertEqual(cards['new_customers']['value'], 1)

    def test_trend_buckets_and_drilldown(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-02')
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-04')
        trend = self.Dashboard.get_widget('trend', self._custom('2026-03-01', '2026-03-07', granularity='day'))
        self.assertEqual(trend['status'], 'ok')
        self.assertEqual(len(trend['labels']), 7)
        self.assertEqual(trend['current'], [0.0, 100.0, 0.0, 200.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(trend['total'], 300.0)
        action = self.Dashboard.get_drill_action(
            'trend', self._custom('2026-03-01', '2026-03-07', granularity='day'), {'bucket': '2026-03-04'})
        self.assertEqual(self.env['sale.order'].search_count(action['domain']), 1)

    def test_breakdown_and_top(self):
        self._order(self.customer_a, [(self.product_x, 3)], '2026-03-02')
        self._order(self.customer_b, [(self.product_y, 1)], '2026-03-03')
        breakdown = self.Dashboard.get_widget('breakdown', self._custom('2026-03-01', '2026-03-31'),
                                              {'dimension': 'categ_id'})
        self.assertEqual([i['name'] for i in breakdown['items']][:2],
                         [self.categ_x.display_name, self.categ_y.display_name])
        self.assertAlmostEqual(sum(i['share'] for i in breakdown['items']), 1.0)
        top = self.Dashboard.get_widget('top', self._custom('2026-03-01', '2026-03-31'), {'kind': 'customers'})
        self.assertEqual(top['items'][0]['id'], self.customer_a.id)
        self.assertAlmostEqual(top['items'][0]['value'], 300.0)

    @freeze_time('2026-06-30')
    def test_receivables_aging(self):
        def invoice(amount, inv_date, due):
            move = self.init_invoice('out_invoice', partner=self.customer_a, invoice_date=inv_date,
                                     amounts=[amount], post=False)
            move.invoice_date_due = due
            move.action_post()
            return move
        invoice(100.0, '2026-06-20', '2026-07-20')   # not due
        invoice(200.0, '2026-05-01', '2026-06-10')   # 20 days overdue
        invoice(300.0, '2026-01-01', '2026-02-01')   # > 90 days
        paid = invoice(999.0, '2026-05-01', '2026-05-15')
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=paid.ids).create({})._create_payments()
        data = self.Dashboard.get_widget('receivables', {'preset': 'this_month'})
        self.assertEqual(data['status'], 'ok')
        buckets = {b['key']: b for b in data['buckets']}
        self.assertAlmostEqual(buckets['not_due']['value'], 100.0)
        self.assertAlmostEqual(buckets['1_30']['value'], 200.0)
        self.assertAlmostEqual(buckets['90_plus']['value'], 300.0)
        self.assertAlmostEqual(data['total'], 600.0)
        self.assertAlmostEqual(data['overdue'], 500.0)
        moves = self.env['account.move'].search(buckets['1_30']['action']['domain'])
        self.assertAlmostEqual(sum(moves.mapped('amount_residual')), 200.0)

    def test_invoiced_revenue_net_of_credit_notes(self):
        self.init_invoice('out_invoice', partner=self.customer_a, invoice_date='2026-03-05', amounts=[1000.0], post=True)
        self.init_invoice('out_refund', partner=self.customer_a, invoice_date='2026-03-06', amounts=[250.0], post=True)
        self.init_invoice('out_invoice', partner=self.customer_a, invoice_date='2026-03-07', amounts=[400.0], post=False)
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'), ['invoiced_revenue'])
        self.assertAlmostEqual(cards['invoiced_revenue']['value'], 750.0)

    def test_filter_validation(self):
        bad = [
            self._custom('2026-03-31', '2026-03-01'),
            self._custom('not-a-date', '2026-03-01'),
            {'preset': 'bogus'},
            {'preset': 'this_month', 'comparison': 'bogus'},
            {'preset': 'this_month', 'user_ids': ['1; DROP TABLE']},
            {'preset': 'this_month', 'user_ids': [True]},
            self._custom('2000-01-01', '2026-01-01'),
        ]
        for raw in bad:
            result = self.Dashboard.get_widget('kpis', raw, {})
            self.assertEqual(result['status'], 'invalid', raw)
        with self.assertRaises(UserError):
            self.Dashboard._parse_filters({'preset': 'custom', 'date_from': '2026-01-01'})

    def test_salesman_record_rules(self):
        """A salesman restricted to his own documents only sees his own figures."""
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-02', user=self.salesman)
        self._order(self.customer_a, [(self.product_x, 7)], '2026-03-03')
        dashboard = self.Dashboard.with_user(self.salesman)
        cards = self._cards(self._custom('2026-03-01', '2026-03-31'),
                            ['confirmed_sales', 'invoiced_revenue', 'overdue_receivables'], dashboard)
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 100.0)
        # no accounting role: financial KPIs are restricted
        self.assertEqual(cards['invoiced_revenue']['status'], 'forbidden')
        self.assertEqual(cards['overdue_receivables']['status'], 'forbidden')
        self.assertEqual(dashboard.get_widget('receivables', {'preset': 'this_month'})['status'], 'forbidden')
        self.assertEqual(dashboard.get_widget('trend', {'preset': 'this_month'}, {'metric': 'revenue'})['status'],
                         'forbidden')
        self.assertFalse(dashboard.get_bootstrap()['permissions']['finance'])

    def test_users_without_group_are_denied(self):
        user = self.env['res.users'].create({
            'name': 'No BP', 'login': 'no_bp',
            'groups_id': [Command.set([self.env.ref('sales_team.group_sale_salesman').id])],
        })
        result = self.Dashboard.with_user(user).get_widget('kpis', {'preset': 'this_month'})
        self.assertEqual(result['status'], 'forbidden')

    def test_multi_company_isolation(self):
        other = self.env['res.company'].create({'name': 'BP Other Co'})
        self.env.user.company_ids |= other
        order = self.env['sale.order'].with_company(other).create({
            'partner_id': self.customer_a.id, 'company_id': other.id,
            'order_line': [Command.create({'product_id': self.product_x.id, 'product_uom_qty': 4, 'price_unit': 100})],
        })
        order.action_confirm()
        order.date_order = fields.Datetime.to_datetime('2026-03-10 10:00:00')
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-11')
        filters = self._custom('2026-03-01', '2026-03-31')
        only_main = self.Dashboard.with_context(allowed_company_ids=[self.env.company.id])
        cards = self._cards(filters, ['confirmed_sales'], only_main)
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 100.0)
        # a company outside the allowed set cannot be requested
        result = only_main.get_widget('kpis', dict(filters, company_ids=[other.id]), {})
        self.assertEqual(result['status'], 'forbidden')
        both = self.Dashboard.with_context(allowed_company_ids=[self.env.company.id, other.id])
        cards = self._cards(dict(filters, company_ids=[other.id]), ['confirmed_sales'], both)
        self.assertAlmostEqual(cards['confirmed_sales']['value'], 400.0)

    def test_preferences(self):
        Pref = self.env['business.pulse.preference'].with_user(self.salesman)
        saved = Pref.save_preferences({'kpi_keys': ['order_count', 'confirmed_sales'], 'date_preset': 'last_30_days'})
        self.assertEqual(saved['kpi_keys'], ['order_count', 'confirmed_sales'])
        self.assertEqual(saved['date_preset'], 'last_30_days')
        with self.assertRaises(UserError):
            Pref.save_preferences({'kpi_keys': ['not_a_kpi']})
        with self.assertRaises(UserError):
            Pref.save_preferences({'date_preset': 'custom'})
        # preferences are private
        self.assertFalse(self.env['business.pulse.preference'].get_preferences()['kpi_keys'])
        self.assertEqual(Pref.reset_preferences()['kpi_keys'], [])

    def test_export(self):
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-05')
        filters = self._custom('2026-03-01', '2026-03-31')
        for widget in ('kpis', 'trend', 'breakdown', 'top', 'receivables'):
            export = self.Dashboard.get_export(widget, filters, {})
            self.assertTrue(export['headers'])
            self.assertTrue(export['meta'])
        top = self.Dashboard.get_export('top', filters, {'kind': 'products'})
        self.assertEqual(top['rows'][0][1], self.product_x.display_name)
        with self.assertRaises(UserError):
            self.Dashboard.with_user(self.salesman).get_export('receivables', filters, {})

    def test_all_widgets_render_without_data(self):
        filters = self._custom('2030-01-01', '2030-01-31', comparison='previous_year')
        for widget in ('kpis', 'trend', 'breakdown', 'top', 'receivables', 'attention', 'activity'):
            self.assertEqual(self.Dashboard.get_widget(widget, filters)['status'], 'ok', widget)
