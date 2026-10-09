# -*- coding: utf-8 -*-
import io
import zipfile
from datetime import date

from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.business_pulse.controllers.main import BusinessPulseController

from .common import BusinessPulseCase


@tagged('post_install', '-at_install')
class TestSalesAnalytics(BusinessPulseCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Target = cls.env['business.pulse.target']
        cls.View = cls.env['business.pulse.view']

    def _target(self, **vals):
        return self.Target.create(dict({
            'name': 'T', 'metric': 'confirmed_sales', 'scope': 'company', 'period': 'custom',
            'date_from': '2026-03-01', 'date_to': '2026-03-31', 'amount': 1000.0,
        }, **vals))

    # Funnel -------------------------------------------------------------
    def test_funnel_cohort(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-02')                 # confirmed 100
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-03', confirm=False)   # open 200
        cancelled = self._order(self.customer_b, [(self.product_y, 1)], '2026-03-04', confirm=False)
        cancelled._action_cancel()
        self._order(self.customer_b, [(self.product_x, 5)], '2026-04-04')                 # other cohort
        data = self.Dashboard.get_widget('funnel', self._custom('2026-03-01', '2026-03-31'))
        self.assertEqual(data['status'], 'ok', data)
        stages = {s['key']: s for s in data['stages']}
        self.assertEqual(stages['created']['count'], 3)
        self.assertEqual(stages['confirmed']['count'], 1)
        self.assertEqual(stages['open']['count'], 1)
        self.assertEqual(stages['cancelled']['count'], 1)
        self.assertAlmostEqual(stages['created']['value'], 350.0)
        self.assertAlmostEqual(data['rate'], 1 / 3)
        orders = self.env['sale.order'].search(stages['open']['action']['domain'])
        self.assertEqual(len(orders), 1)

    # Quotation aging ----------------------------------------------------
    @freeze_time('2026-03-31 12:00:00')
    def test_quotation_aging(self):
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-30', confirm=False)   # 1 day
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-10', confirm=False)   # 21 days
        old = self._order(self.customer_b, [(self.product_x, 3)], '2025-11-01', confirm=False)  # > 90 days
        old.validity_date = '2025-12-01'
        self._order(self.customer_b, [(self.product_x, 9)], '2026-03-30')                  # confirmed, ignored
        data = self.Dashboard.get_widget('quotations', {'preset': 'this_month'})
        self.assertEqual(data['status'], 'ok', data)
        buckets = {b['key']: b for b in data['buckets']}
        self.assertEqual(buckets['0_7']['count'], 1)
        self.assertEqual(buckets['8_30']['count'], 1)
        self.assertEqual(buckets['31_90']['count'], 0)
        self.assertEqual(buckets['90_plus']['count'], 1)
        self.assertAlmostEqual(data['total'], 600.0)
        self.assertEqual(data['expired']['count'], 1)
        self.assertEqual(data['top'][0]['id'], old.id)
        self.assertTrue(data['top'][0]['expired'])

    # Salespeople & targets ------------------------------------------------
    def test_salespeople_with_target(self):
        self._order(self.customer_a, [(self.product_x, 4)], '2026-03-02', user=self.salesman)       # 400
        self._order(self.customer_a, [(self.product_x, 1)], '2026-03-03', user=self.salesman, confirm=False)
        self._order(self.customer_b, [(self.product_x, 7)], '2026-03-04')                           # 700 admin
        self._target(scope='user', user_id=self.salesman.id, amount=800.0)
        data = self.Dashboard.get_widget('salespeople', self._custom('2026-03-01', '2026-03-31'))
        self.assertEqual(data['status'], 'ok', data)
        rows = {r['id']: r for r in data['items']}
        row = rows[self.salesman.id]
        self.assertAlmostEqual(row['value'], 400.0)
        self.assertEqual(row['orders'], 1)
        self.assertAlmostEqual(row['conversion'], 0.5)
        self.assertAlmostEqual(row['pipeline'], 100.0)
        self.assertAlmostEqual(row['target']['completion'], 0.5)
        self.assertEqual(data['items'][0]['id'], self.env.user.id)  # sorted by sales

    def test_target_progress_statuses(self):
        self._order(self.customer_a, [(self.product_x, 3)], '2026-03-05')   # 300
        target = self._target(amount=1000.0)
        self.env.flush_all()  # _target_progress is internal; the public widget API flushes itself
        with freeze_time('2026-03-10'):   # 10/31 elapsed -> expect ~322.6, actual 300 -> behind
            progress = self.Dashboard._target_progress(target, date(2026, 3, 10))
        self.assertEqual(progress['status'], 'behind')
        self.assertAlmostEqual(progress['completion'], 0.3)
        progress = self.Dashboard._target_progress(target, date(2026, 3, 5))   # 5/31 -> on track
        self.assertEqual(progress['status'], 'on_track')
        progress = self.Dashboard._target_progress(target, date(2026, 4, 15))  # ended below target
        self.assertEqual(progress['status'], 'missed')
        self.assertAlmostEqual(progress['remaining'], 700.0)
        progress = self.Dashboard._target_progress(target, date(2026, 2, 15))
        self.assertEqual(progress['status'], 'upcoming')
        self.assertEqual(progress['actual'], 0.0)
        target.amount = 250.0
        progress = self.Dashboard._target_progress(target, date(2026, 3, 10))
        self.assertEqual(progress['status'], 'achieved')
        orders_target = self._target(metric='order_count', amount=2)
        self.env.flush_all()
        self.assertEqual(self.Dashboard._target_progress(orders_target, date(2026, 3, 31))['actual'], 1)

    def test_targets_widget_and_visibility(self):
        self._target(name='Company')
        self._target(name='Mine', scope='user', user_id=self.salesman.id)
        self._target(name='Other', scope='user', user_id=self.env.user.id)
        self._target(name='Revenue', metric='invoiced_revenue')
        self._target(name='Next year', date_from='2027-01-01', date_to='2027-12-31')
        data = self.Dashboard.get_widget('targets', self._custom('2026-03-01', '2026-03-31'))
        self.assertEqual({t['name'] for t in data['items']}, {'Company', 'Mine', 'Other', 'Revenue'})
        self.assertTrue(data['can_manage'])
        as_salesman = self.Dashboard.with_user(self.salesman).get_widget(
            'targets', self._custom('2026-03-01', '2026-03-31'))
        # own-documents salesman: no other people's targets, no finance targets, read-only
        self.assertEqual({t['name'] for t in as_salesman['items']}, {'Company', 'Mine'})
        self.assertFalse(as_salesman['can_manage'])
        with self.assertRaises(AccessError):
            self.Target.with_user(self.salesman).create({
                'name': 'x', 'date_from': '2026-03-01', 'date_to': '2026-03-31', 'amount': 1})

    def test_target_constraints(self):
        with self.assertRaises(ValidationError):
            self._target(date_from='2026-04-01', date_to='2026-03-01')
        with self.assertRaises(ValidationError):
            self._target(amount=0)
        with self.assertRaises(ValidationError):
            self._target(scope='user')
        with self.assertRaises(ValidationError):
            self._target(scope='team')

    # Saved views -------------------------------------------------------
    def test_saved_views(self):
        views = self.View.with_user(self.salesman).save_view(
            'Mine', {'preset': 'last_30_days', 'user_ids': [self.salesman.id], 'evil': 1}, {'page': 'sales', 'x': 1})
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]['filters'], {'preset': 'last_30_days', 'user_ids': [self.salesman.id]})
        self.assertEqual(views[0]['options'], {'page': 'sales'})
        # same name replaces
        views = self.View.with_user(self.salesman).save_view('Mine', {'preset': 'this_year'})
        self.assertEqual([v['filters']['preset'] for v in views], ['this_year'])
        for bad in ({'preset': 'nope'}, {'preset': 'custom', 'date_from': '2026-02-01', 'date_to': '2026-01-01'},
                    {'preset': 'this_month', 'user_ids': ['x']}):
            with self.assertRaises(UserError):
                self.View.with_user(self.salesman).save_view('Bad', bad)
        with self.assertRaises(UserError):
            self.View.save_view('   ', {'preset': 'this_month'})
        # private to the owner
        self.assertEqual(self.View.list_views(), [])
        self.View.delete_view(views[0]['id'])  # someone else's id: no effect
        self.assertEqual(len(self.View.with_user(self.salesman).list_views()), 1)

    # Exports -------------------------------------------------------------
    def test_typed_exports_and_xlsx(self):
        self._order(self.customer_a, [(self.product_x, 2)], '2026-03-05', user=self.salesman)
        self._target(scope='user', user_id=self.salesman.id)
        filters = self._custom('2026-03-01', '2026-03-31')
        for widget in ('salespeople', 'quotations', 'targets', 'kpis', 'top'):
            export = self.Dashboard.get_export(widget, filters, {})
            self.assertEqual(len(export['headers']), len(export['kinds']))
            for row in export['rows']:
                self.assertEqual(len(row), len(export['headers']))
            content = BusinessPulseController._xlsx(export)
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                self.assertIn('xl/worksheets/sheet1.xml', archive.namelist())
            self.assertTrue(BusinessPulseController._csv(export).startswith('﻿'.encode()))
        people = self.Dashboard.get_export('salespeople', filters, {})
        self.assertEqual(people['rows'][0][0], self.salesman.name)
        self.assertEqual(people['rows'][0][1], 200.0)
        with self.assertRaises(UserError):
            self.Dashboard.get_export('activity', filters, {})
