# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

PRESET_SELECTION = [
    ('today', 'Today'), ('yesterday', 'Yesterday'),
    ('this_week', 'This week'), ('last_week', 'Last week'),
    ('this_month', 'This month'), ('last_month', 'Last month'),
    ('this_quarter', 'This quarter'), ('last_quarter', 'Last quarter'),
    ('this_year', 'This year'), ('last_year', 'Last year'),
    ('last_7_days', 'Last 7 days'), ('last_30_days', 'Last 30 days'), ('last_90_days', 'Last 90 days'),
]
COMPARISON_SELECTION = [
    ('previous_period', 'Previous period'),
    ('previous_year', 'Same period last year'),
    ('none', 'No comparison'),
]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    business_pulse_default_preset = fields.Selection(
        PRESET_SELECTION, string="Default period", default='this_month',
        config_parameter='business_pulse.default_preset')
    business_pulse_default_comparison = fields.Selection(
        COMPARISON_SELECTION, string="Default comparison", default='previous_period',
        config_parameter='business_pulse.default_comparison')
    business_pulse_expiring_days = fields.Integer(
        string="Expiring quotation window (days)", default=7,
        config_parameter='business_pulse.expiring_days')
    business_pulse_stale_days = fields.Integer(
        string="Stalled quotation age (days)", default=30,
        config_parameter='business_pulse.stale_days')
    business_pulse_sales_drop_threshold = fields.Float(
        string="Sales decline alert (%)", default=20.0,
        config_parameter='business_pulse.sales_drop_threshold')
    business_pulse_export_limit = fields.Integer(
        string="Maximum exported rows", default=10000,
        config_parameter='business_pulse.export_limit')

    @api.constrains('business_pulse_expiring_days', 'business_pulse_stale_days',
                    'business_pulse_sales_drop_threshold', 'business_pulse_export_limit')
    def _check_business_pulse_values(self):
        for settings in self:
            if not 1 <= settings.business_pulse_expiring_days <= 365:
                raise ValidationError(self.env._("The expiring quotation window must be between 1 and 365 days."))
            if not 1 <= settings.business_pulse_stale_days <= 3650:
                raise ValidationError(self.env._("The stalled quotation age must be between 1 and 3650 days."))
            if not 0 <= settings.business_pulse_sales_drop_threshold <= 100:
                raise ValidationError(self.env._("The sales decline threshold must be between 0 and 100%."))
            if not 100 <= settings.business_pulse_export_limit <= 1000000:
                raise ValidationError(self.env._("The export limit must be between 100 and 1,000,000 rows."))
