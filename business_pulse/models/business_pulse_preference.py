# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .business_pulse_dashboard import COMPARISONS, PRESETS


class BusinessPulsePreference(models.Model):
    """Per-user dashboard personalization.

    Preferences only change *what* is displayed, never *which records* a user
    can read: every widget is still computed with the user's own access rights.
    """
    _name = 'business.pulse.preference'
    _description = 'Business Pulse User Preference'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True,
                              default=lambda self: self.env.user)
    kpi_keys = fields.Char(help="JSON list of KPI card keys, in display order.")
    date_preset = fields.Selection([(p, p) for p in PRESETS if p != 'custom'])
    comparison = fields.Selection([(c, c) for c in COMPARISONS if c != 'custom'])

    _sql_constraints = [
        ('user_unique', 'unique(user_id)', 'Each user can only have one Business Pulse preference.'),
    ]

    @api.model
    def _own(self):
        return self.search([('user_id', '=', self.env.uid)], limit=1)

    @api.model
    def get_preferences(self):
        pref = self._own()
        keys = []
        if pref.kpi_keys:
            try:
                keys = [k for k in json.loads(pref.kpi_keys) if isinstance(k, str)]
            except ValueError:
                keys = []
        return {
            'kpi_keys': keys,
            'date_preset': pref.date_preset or False,
            'comparison': pref.comparison or False,
        }

    @api.model
    def save_preferences(self, values):
        if not isinstance(values, dict):
            raise UserError(_("Invalid preferences."))
        catalog = self.env['business.pulse.dashboard']._kpi_catalog()
        vals = {}
        if 'kpi_keys' in values:
            keys = values['kpi_keys'] or []
            if not isinstance(keys, list) or any(k not in catalog for k in keys) or len(keys) > 12:
                raise UserError(_("Invalid KPI selection."))
            vals['kpi_keys'] = json.dumps(list(dict.fromkeys(keys))) if keys else False
        if 'date_preset' in values:
            preset = values['date_preset'] or False
            if preset and (preset not in PRESETS or preset == 'custom'):
                raise UserError(_("Invalid date preset."))
            vals['date_preset'] = preset
        if 'comparison' in values:
            comparison = values['comparison'] or False
            if comparison and (comparison not in COMPARISONS or comparison == 'custom'):
                raise UserError(_("Invalid comparison."))
            vals['comparison'] = comparison
        pref = self._own()
        if pref:
            pref.write(vals)
        else:
            self.create(dict(vals, user_id=self.env.uid))
        return self.get_preferences()

    @api.model
    def reset_preferences(self):
        self._own().unlink()
        return self.get_preferences()
