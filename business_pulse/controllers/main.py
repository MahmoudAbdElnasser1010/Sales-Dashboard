# -*- coding: utf-8 -*-
import csv
import io
import json
import logging
import re

from werkzeug.exceptions import BadRequest, Forbidden

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

EXPORTABLE = ('kpis', 'trend', 'breakdown', 'top', 'receivables')


class BusinessPulseController(http.Controller):

    @http.route('/business_pulse/export/csv', type='http', auth='user', methods=['POST'])
    def export_csv(self, widget, filters='{}', options='{}', **kwargs):
        """Server-side CSV export. Uses the same service, filters and access
        rights as the dashboard, so an export can never reveal more data than
        the user can already see."""
        if widget not in EXPORTABLE:
            raise BadRequest()
        if not request.env.user.has_group('business_pulse.group_business_pulse_user'):
            raise Forbidden()
        try:
            raw_filters = json.loads(filters or '{}')
            raw_options = json.loads(options or '{}')
        except ValueError:
            raise BadRequest()
        context = raw_filters.pop('context', None) if isinstance(raw_filters, dict) else None
        env = request.env
        if isinstance(context, dict) and isinstance(context.get('allowed_company_ids'), list):
            allowed = [cid for cid in context['allowed_company_ids'] if cid in env.user.company_ids.ids]
            if allowed:
                env = env(context=dict(env.context, allowed_company_ids=allowed))
        try:
            data = env['business.pulse.dashboard'].get_export(widget, raw_filters, raw_options)
        except (AccessError, UserError) as error:
            raise Forbidden(description=str(error.args[0] if error.args else error))

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for label, value in data['meta']:
            writer.writerow([label, value])
        writer.writerow([])
        writer.writerow(data['headers'])
        for row in data['rows']:
            writer.writerow(['' if value is None or value is False else value for value in row])
        content = '﻿' + buffer.getvalue()  # BOM so spreadsheet apps detect UTF-8
        slug = re.sub(r'[^a-z0-9]+', '-', (data['title'] or widget).lower()).strip('-') or widget
        filename = f"business-pulse-{slug}.csv"
        return request.make_response(content.encode('utf-8'), headers=[
            ('Content-Type', 'text/csv; charset=utf-8'),
            ('Content-Disposition', content_disposition(filename)),
        ])
