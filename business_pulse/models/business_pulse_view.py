# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .business_pulse_dashboard import DIMENSION_FILTERS

MAX_VIEWS_PER_USER = 30
FILTER_KEYS = {'preset', 'date_from', 'date_to', 'comparison', 'compare_from', 'compare_to', 'company_ids',
               *DIMENSION_FILTERS}
OPTION_KEYS = {'trend', 'breakdown', 'top', 'page'}


class BusinessPulseView(models.Model):
    """A named set of filters saved by a user ("saved view").

    Only filter values are stored. Loading a view re-runs every widget with
    the user's own permissions, so a view can never widen access.
    """
    _name = 'business.pulse.view'
    _description = 'Business Pulse Saved View'
    _order = 'name, id'

    name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True,
                              default=lambda self: self.env.user)
    filters = fields.Text(required=True, default='{}')
    options = fields.Text(default='{}')

    @api.model
    def _clean(self, filters, options):
        if not isinstance(filters, dict) or not isinstance(options, dict):
            raise UserError(_("Invalid view."))
        filters = {k: v for k, v in filters.items() if k in FILTER_KEYS}
        options = {k: v for k, v in options.items() if k in OPTION_KEYS}
        # Validate with the same parser as the dashboard (raises on bad input).
        self.env['business.pulse.dashboard']._parse_filters(filters)
        return filters, options

    @api.model
    def list_views(self):
        views = self.search([('user_id', '=', self.env.uid)])
        result = []
        for view in views:
            try:
                result.append({'id': view.id, 'name': view.name,
                               'filters': json.loads(view.filters or '{}'),
                               'options': json.loads(view.options or '{}')})
            except ValueError:
                continue
        return result

    @api.model
    def save_view(self, name, filters, options=None):
        name = (name or '').strip()
        if not name or len(name) > 80:
            raise UserError(_("Give the view a name (up to 80 characters)."))
        filters, options = self._clean(filters, options or {})
        existing = self.search([('user_id', '=', self.env.uid), ('name', '=', name)], limit=1)
        vals = {'filters': json.dumps(filters), 'options': json.dumps(options)}
        if existing:
            existing.write(vals)
        else:
            if self.search_count([('user_id', '=', self.env.uid)]) >= MAX_VIEWS_PER_USER:
                raise UserError(_("You can save up to %s views. Delete one first.", MAX_VIEWS_PER_USER))
            self.create(dict(vals, name=name, user_id=self.env.uid))
        return self.list_views()

    @api.model
    def delete_view(self, view_id):
        view = self.search([('id', '=', int(view_id)), ('user_id', '=', self.env.uid)])
        view.unlink()
        return self.list_views()
