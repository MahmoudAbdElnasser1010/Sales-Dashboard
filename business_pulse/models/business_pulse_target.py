# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TARGET_METRICS = [
    ('confirmed_sales', 'Confirmed Sales'),
    ('order_count', 'Confirmed Orders'),
    ('invoiced_revenue', 'Invoiced Revenue'),
]


class BusinessPulseTarget(models.Model):
    """A performance target. Progress is always measured with exactly the
    same metric definition, company currency and dates as the dashboard KPI
    of the same name."""
    _name = 'business.pulse.target'
    _description = 'Business Pulse Target'
    _order = 'date_from desc, id desc'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    metric = fields.Selection(TARGET_METRICS, required=True, default='confirmed_sales')
    scope = fields.Selection([
        ('company', 'Whole company'),
        ('team', 'Sales team'),
        ('user', 'Salesperson'),
    ], required=True, default='company')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Salesperson', domain=[('share', '=', False)])
    period = fields.Selection([
        ('month', 'Month'), ('quarter', 'Quarter'), ('year', 'Year'), ('custom', 'Custom'),
    ], required=True, default='month')
    date_from = fields.Date(string='Start', required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='End', required=True,
                          default=lambda self: fields.Date.context_today(self).replace(day=1)
                          + relativedelta(months=1, days=-1))
    amount = fields.Float(string='Target', required=True,
                          help="Target value in the company currency, or a number of orders.")
    note = fields.Text()

    @api.onchange('period', 'date_from')
    def _onchange_period(self):
        for target in self:
            if not target.date_from or target.period == 'custom':
                continue
            start = target.date_from
            if target.period == 'month':
                start = start.replace(day=1)
                end = start + relativedelta(months=1, days=-1)
            elif target.period == 'quarter':
                start = date(start.year, 3 * ((start.month - 1) // 3) + 1, 1)
                end = start + relativedelta(months=3, days=-1)
            else:
                start = date(start.year, 1, 1)
                end = date(start.year, 12, 31)
            target.date_from, target.date_to = start, end

    @api.onchange('scope')
    def _onchange_scope(self):
        for target in self:
            if target.scope != 'team':
                target.team_id = False
            if target.scope != 'user':
                target.user_id = False

    @api.constrains('date_from', 'date_to', 'amount', 'scope', 'team_id', 'user_id')
    def _check_target(self):
        for target in self:
            if target.date_from > target.date_to:
                raise ValidationError(_("The target start date must be before its end date."))
            if (target.date_to - target.date_from).days > 3700:
                raise ValidationError(_("A target cannot span more than 10 years."))
            if target.amount <= 0:
                raise ValidationError(_("The target value must be positive."))
            if target.scope == 'team' and not target.team_id:
                raise ValidationError(_("Select the sales team for this target."))
            if target.scope == 'user' and not target.user_id:
                raise ValidationError(_("Select the salesperson for this target."))

    @api.depends('name', 'date_from', 'date_to')
    def _compute_display_name(self):
        for target in self:
            target.display_name = f"{target.name} ({target.date_from} → {target.date_to})" \
                if target.date_from else target.name

    def _scope_label(self):
        self.ensure_one()
        if self.scope == 'team':
            return self.team_id.display_name
        if self.scope == 'user':
            return self.user_id.display_name
        return self.company_id.display_name


def elapsed_fraction(date_from, date_to, today):
    """Share of the target period elapsed at ``today`` (inclusive), 0..1."""
    total = (date_to - date_from).days + 1
    done = (min(today, date_to) - date_from).days + 1
    return max(0.0, min(1.0, done / total)) if total > 0 else 0.0

