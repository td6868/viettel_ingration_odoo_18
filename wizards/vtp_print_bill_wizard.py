# -*- coding: utf-8 -*-
"""
VTP Print Bill Wizard - Refactored with:
- Multi-account support (account from order_bill)
- Print URL based on environment
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

# Print URLs by environment
PRINT_URLS = {
    'test': 'https://dev-print.viettelpost.vn/DigitalizePrint/report.do',
    'production': 'https://digitalize.viettelpost.vn/DigitalizePrint/report.do'
}

# Paper type mapping
PAPER_TYPES = {
    '1': 1,    # A5
    '2': 2,    # A6
    '3': 100,  # A7
}


class VTPPrintBillWizard(models.TransientModel):
    _name = 'vtp.print.bill.wizard'
    _description = 'In vận đơn ViettelPost'

    type = fields.Selection([
        ('1', 'A5'),
        ('2', 'A6'),
        ('3', 'A7'),
    ], string='Khổ giấy', default='1')

    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True)
    vtp_bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn ViettelPost', required=True)
    order_number = fields.Char(string='Số vận đơn', related='picking_id.vtp_order_number', readonly=True)
    
    # Account from vtp_bill for API calls
    account_id = fields.Many2one(
        'vtp.account',
        string='Tài khoản VTP',
        compute='_compute_account_id',
        store=False
    )
    
    token_expiry_display = fields.Datetime(
        string='Hết hạn token', 
        related='account_id.token_expiry_display', 
        readonly=True
    )

    @api.depends('vtp_bill_id', 'vtp_bill_id.store_id', 'vtp_bill_id.store_id.account_id')
    def _compute_account_id(self):
        for record in self:
            if record.vtp_bill_id and record.vtp_bill_id.store_id:
                record.account_id = record.vtp_bill_id.store_id.account_id
            elif record.picking_id and record.picking_id.vtp_store_id:
                record.account_id = record.picking_id.vtp_store_id.account_id
            else:
                record.account_id = False

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Auto-select vtp_bill when picking is selected"""
        if self.picking_id:
            bill = self.env['vtp.order.bill'].search([
                ('order_id', '=', self.picking_id.id)
            ], limit=1)
            self.vtp_bill_id = bill.id if bill else False

    def _get_default_from_context(self):
        """Determine default records from context"""
        ctx = self.env.context or {}
        active_model = ctx.get('active_model')
        active_id = ctx.get('active_id')

        picking = False
        bill = False

        if active_model == 'stock.picking' and active_id:
            picking = self.env['stock.picking'].browse(active_id)
            if picking:
                bill = self.env['vtp.order.bill'].search([
                    ('order_id', '=', picking.id)
                ], limit=1)
        elif active_model == 'vtp.order.bill' and active_id:
            bill = self.env['vtp.order.bill'].browse(active_id)
            if bill:
                picking = bill.order_id

        return picking, bill

    @api.model
    def default_get(self, fields):
        res = super(VTPPrintBillWizard, self).default_get(fields)
        picking, bill = self._get_default_from_context()
        if picking:
            res['picking_id'] = picking.id
        if bill:
            res['vtp_bill_id'] = bill.id
        
        if 'vtp_bill_id' not in res or not res.get('vtp_bill_id'):
            _logger.warning('No vtp.order.bill found when opening print wizard')
        return res

    def _get_print_base_url(self):
        """Get print URL based on environment"""
        env = self.env['ir.config_parameter'].sudo().get_param(
            'viettel_ingration_odoo_18.environment', 'production'
        )
        return PRINT_URLS.get(env, PRINT_URLS['production'])

    def action_print_bill(self):
        """Print ViettelPost bill"""
        self.ensure_one()
        
        # Validate
        if not self.vtp_bill_id:
            raise UserError(_('Không tìm thấy vận đơn ViettelPost cho phiếu này.'))
        if not self.picking_id.vtp_order_number:
            raise UserError(_('Vận đơn chưa có mã ORDER_NUMBER. Vui lòng tạo vận đơn trước khi in.'))
        
        # Get account for API call
        account = self.account_id
        if not account:
            # Fallback: try to get from store
            if self.vtp_bill_id.store_id and self.vtp_bill_id.store_id.account_id:
                account = self.vtp_bill_id.store_id.account_id
            elif self.picking_id.vtp_store_id and self.picking_id.vtp_store_id.account_id:
                account = self.picking_id.vtp_store_id.account_id
            else:
                raise UserError(_('Không tìm thấy tài khoản VTP. Vui lòng đảm bảo vận đơn được gán store.'))

        # Prepare request data
        data = {
            'EXPIRY_TIME': str(account.token_expiry) if account.token_expiry else '',
            'ORDER_ARRAY': [self.picking_id.vtp_order_number],
        }

        _logger.info("VTP Print Bill - Account: %s, Order: %s", 
                     account.name, self.picking_id.vtp_order_number)

        # Call service with account (NEW: account parameter required)
        VTPservice = self.env['vtp.service']
        code = VTPservice.link_print_bill(
            account=account,
            data=data,
            order_bill=self.vtp_bill_id
        )
        
        if not code:
            raise UserError(_('Không tìm thấy link in vận đơn! Vui lòng thử lại.'))

        # Build print URL
        base_url = self._get_print_base_url()
        paper_type = PAPER_TYPES.get(self.type, 1)
        link = f"{base_url}?type={paper_type}&bill={code}&showPostage=1"

        _logger.info("VTP Print URL: %s", link)

        # Return URL action
        return {
            'type': 'ir.actions.act_url',
            'url': link,
            'target': 'new',
        }