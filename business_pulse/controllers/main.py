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
from odoo.tools.misc import xlsxwriter

_logger = logging.getLogger(__name__)

FORMATS = ('csv', 'xlsx')


class BusinessPulseController(http.Controller):

    @http.route('/business_pulse/export/<string:fmt>', type='http', auth='user', methods=['POST'])
    def export(self, fmt, widget, filters='{}', options='{}', **kwargs):
        """Server-side export. Uses the same service, filters and access
        rights as the dashboard, so an export can never reveal more data than
        the user can already see."""
        if fmt not in FORMATS:
            raise BadRequest()
        if not request.env.user.has_group('business_pulse.group_business_pulse_user'):
            raise Forbidden()
        try:
            raw_filters = json.loads(filters or '{}')
            raw_options = json.loads(options or '{}')
        except ValueError:
            raise BadRequest()
        if not isinstance(raw_filters, dict) or not isinstance(raw_options, dict):
            raise BadRequest()
        context = raw_filters.pop('context', None)
        env = request.env
        if isinstance(context, dict) and isinstance(context.get('allowed_company_ids'), list):
            allowed = [cid for cid in context['allowed_company_ids'] if cid in env.user.company_ids.ids]
            if allowed:
                env = env(context=dict(env.context, allowed_company_ids=allowed))
        dashboard = env['business.pulse.dashboard']
        if widget not in dashboard._export_names():
            raise BadRequest()
        try:
            data = dashboard.get_export(widget, raw_filters, raw_options)
        except (AccessError, UserError) as error:
            raise Forbidden(description=str(error.args[0] if error.args else error))

        slug = re.sub(r'[^a-z0-9]+', '-', (data['title'] or widget).lower()).strip('-') or widget
        if fmt == 'xlsx':
            content = self._xlsx(data)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            content = self._csv(data)
            mimetype = 'text/csv; charset=utf-8'
        return request.make_response(content, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(f"business-pulse-{slug}.{fmt}")),
        ])

    @staticmethod
    def _csv(data):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for label, value in data['meta']:
            writer.writerow([label, value])
        writer.writerow([])
        writer.writerow(data['headers'])
        for row in data['rows']:
            writer.writerow(row)
        return ('﻿' + buffer.getvalue()).encode('utf-8')  # BOM so spreadsheet apps detect UTF-8

    @staticmethod
    def _xlsx(data):
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet = workbook.add_worksheet((data['title'] or 'Report')[:31])
        currency = data['currency']
        decimals = '0' if not currency['decimals'] else '0.' + '0' * currency['decimals']
        symbol = currency['symbol'].replace('"', '')
        money_fmt = (f'#,##{decimals} "{symbol}"' if currency['position'] == 'after'
                     else f'"{symbol}" #,##{decimals}')
        formats = {
            'title': workbook.add_format({'bold': True, 'font_size': 14}),
            'meta_label': workbook.add_format({'bold': True, 'font_color': '#52514e'}),
            'header': workbook.add_format({'bold': True, 'bottom': 1, 'bg_color': '#eef4fc', 'text_wrap': True,
                                           'valign': 'vcenter'}),
            'money': workbook.add_format({'num_format': money_fmt}),
            'count': workbook.add_format({'num_format': '#,##0'}),
            'number': workbook.add_format({'num_format': '#,##0.####'}),
            'percent': workbook.add_format({'num_format': '0.0%'}),
            'date': workbook.add_format({}),
            'text': workbook.add_format({'text_wrap': False}),
        }
        sheet.write(0, 0, data['title'], formats['title'])
        row = 2
        for label, value in data['meta'][1:]:
            sheet.write(row, 0, label, formats['meta_label'])
            sheet.write(row, 1, value)
            row += 1
        row += 1
        header_row = row
        for col, header in enumerate(data['headers']):
            sheet.write(row, col, header, formats['header'])
        widths = [max(len(str(h)), 10) for h in data['headers']]
        for values in data['rows']:
            row += 1
            for col, value in enumerate(values):
                kind = data['kinds'][col]
                if value == '' or value is None:
                    continue
                if isinstance(value, (int, float)) and kind in ('money', 'count', 'number', 'percent'):
                    sheet.write_number(row, col, value, formats[kind])
                else:
                    sheet.write_string(row, col, str(value), formats.get(kind, formats['text']))
                widths[col] = min(max(widths[col], len(str(value)) + 2), 60)
        for col, width in enumerate(widths):
            sheet.set_column(col, col, width)
        sheet.set_column(0, 0, max(widths[0] if widths else 10, 18))
        if data['rows']:
            sheet.autofilter(header_row, 0, row, len(data['headers']) - 1)
        sheet.freeze_panes(header_row + 1, 0)
        workbook.close()
        return buffer.getvalue()
