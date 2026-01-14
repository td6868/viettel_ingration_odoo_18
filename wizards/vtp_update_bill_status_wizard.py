# -*- coding: utf-8 -*-
"""
VTP Update Bill Status Wizard - Refactored with:
- Multi-account support (account from picking's store)
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class VTPUpdateBillStatusWizard(models.TransientModel):
    _name = 'vtp.update.bill.status.wizard'
    _description = 'Chỉnh sửa trạng thái vận đơn ViettelPost'

    picking_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', required=True)
    order_number = fields.Char(string='Mã vận đơn ViettelPost', required=True)
    
    # Account for API calls
    account_id = fields.Many2one('vtp.account', string='Tài khoản VTP')
    vtp_bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn')
    
    vtp_state = fields.Selection([
        ('draft', 'Nháp'),
        ('waiting_webhook', 'Đang chờ xử lý'),
        ('created', 'Đã tạo'),
        ('done', 'Đã hoàn thành'),
        ('canceled', 'Đã hủy'),
    ], string='Trạng thái hiện tại', readonly=True)
    
    type = fields.Selection([
        ('1', 'Xác nhận đơn hàng'),
        ('2', 'Xác nhận trả hàng'),
        ('3', 'Giao hàng lại'),
        ('4', 'Hủy đơn hàng'),
        ('5', 'Nhận lại đơn hàng (đặt hàng lại)'),
        ('11', 'Xóa đơn hàng đã hủy')
    ], string='Loại cập nhật', required=True)
    
    note = fields.Text(string='Ghi chú')

    @api.model
    def default_get(self, fields_list):
        """Get default values from picking"""
        res = super().default_get(fields_list)
        
        if self._context.get('active_model') == 'stock.picking' and self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))

            # Get vtp_bill
            vtp_bill = self.env['vtp.order.bill'].search([
                ('order_id', '=', picking.id)
            ], limit=1)
            
            if vtp_bill and picking.vtp_order_number:
                res.update({
                    'picking_id': picking.id,
                    'order_number': picking.vtp_order_number,
                    'vtp_state': picking.vtp_state,
                    'vtp_bill_id': vtp_bill.id,
                })
                
                # Get account from store
                if picking.vtp_store_id and picking.vtp_store_id.account_id:
                    res['account_id'] = picking.vtp_store_id.account_id.id
                elif vtp_bill.store_id and vtp_bill.store_id.account_id:
                    res['account_id'] = vtp_bill.store_id.account_id.id
            else:
                raise UserError(_('Không tìm thấy mã vận đơn ViettelPost!'))
        return res

    def action_update_bill_status(self):
        """Update bill status via ViettelPost API"""
        self.ensure_one()
        
        if not self.order_number:
            raise UserError(_('Vui lòng nhập mã vận đơn!'))
        
        # Validate account
        if not self.account_id:
            # Try to get from vtp_bill or picking
            account = None
            if self.vtp_bill_id and self.vtp_bill_id.store_id:
                account = self.vtp_bill_id.store_id.account_id
            elif self.picking_id and self.picking_id.vtp_store_id:
                account = self.picking_id.vtp_store_id.account_id
            
            if not account:
                raise UserError(_('Không tìm thấy tài khoản VTP. Vui lòng đảm bảo vận đơn được gán store.'))
            self.account_id = account

        # Prepare data
        data = {
            "TYPE": int(self.type),
            "ORDER_NUMBER": self.order_number,
            "NOTE": self.note or "Cập nhật trạng thái"
        }
        
        _logger.info("VTP Update Status - Account: %s, Data: %s", self.account_id.name, data)
        
        # Call service with account (NEW: account parameter required)
        VTPService = self.env['vtp.service']
        result = VTPService.update_bill_status(
            account=self.account_id,
            data=data,
            order_bill=self.vtp_bill_id
        )
        
        _logger.info("VTP UpdateOrder result: %s", result)
        
        # Update picking state to waiting (actual state will be updated by webhook)
        self.picking_id.write({
            'vtp_state': 'waiting_webhook',
        })
        
        # Check for error
        if isinstance(result, dict) and result.get('error'):
            raise UserError(_('Lỗi khi cập nhật trạng thái: %s') % result.get('error'))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã gửi yêu cầu'),
                'message': _('Đã gửi yêu cầu cập nhật trạng thái vận đơn! Trạng thái sẽ cập nhật khi webhook trả về.'),
                'sticky': False,
                'type': 'info',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }