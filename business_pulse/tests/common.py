# -*- coding: utf-8 -*-
from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class BusinessPulseCase(AccountTestInvoicingCommon):
    """Shared fixtures and helpers for Business Pulse tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, tz='UTC'))
        cls.Dashboard = cls.env['business.pulse.dashboard']
        cls.group_bp = cls.env.ref('business_pulse.group_business_pulse_user')
        cls.env.user.groups_id |= cls.group_bp | cls.env.ref('sales_team.group_sale_manager')
        cls.customer_a = cls.env['res.partner'].create({'name': 'BP Customer A'})
        cls.customer_b = cls.env['res.partner'].create({'name': 'BP Customer B'})
        cls.categ_x = cls.env['product.category'].create({'name': 'BP Category X'})
        cls.categ_y = cls.env['product.category'].create({'name': 'BP Category Y'})
        cls.product_x = cls.env['product.product'].create({
            'name': 'BP Product X', 'list_price': 100.0, 'categ_id': cls.categ_x.id,
            'invoice_policy': 'order', 'taxes_id': [Command.clear()],
        })
        cls.product_y = cls.env['product.product'].create({
            'name': 'BP Product Y', 'list_price': 50.0, 'categ_id': cls.categ_y.id,
            'invoice_policy': 'order', 'taxes_id': [Command.clear()],
        })
        cls.salesman = cls.env['res.users'].create({
            'name': 'BP Salesman', 'login': 'bp_salesman',
            'groups_id': [Command.set([cls.env.ref('sales_team.group_sale_salesman').id, cls.group_bp.id])],
            'company_id': cls.env.company.id, 'company_ids': [Command.set(cls.env.company.ids)],
        })

    # ------------------------------------------------------------------
    def _order(self, partner, lines, day, user=None, confirm=True):
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'user_id': (user or self.env.user).id,
            'order_line': [Command.create({'product_id': p.id, 'product_uom_qty': q, 'price_unit': p.list_price})
                           for p, q in lines],
        })
        if confirm:
            order.action_confirm()
        order.date_order = fields.Datetime.to_datetime(f'{day} 10:00:00')
        self.env.cr.execute("UPDATE sale_order SET create_date=%s WHERE id=%s", (order.date_order, order.id))
        order.invalidate_recordset(['create_date'])
        return order

    def _custom(self, start, end, **extra):
        return dict({'preset': 'custom', 'date_from': start, 'date_to': end, 'comparison': 'none'}, **extra)

    def _cards(self, filters, keys, dashboard=None):
        result = (self.Dashboard if dashboard is None else dashboard).get_widget('kpis', filters, {'keys': keys})
        self.assertEqual(result['status'], 'ok', result)
        return {card['key']: card for card in result['cards']}
