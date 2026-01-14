# -*- coding: utf-8 -*-
"""
VTP Update Bill Wizard - Refactored with:
- Multi-account support (account from picking's store)
- Proper validation
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class VTPUpdateBillWizard(models.TransientModel):
    _name = 'vtp.update.bill.wizard'
    _description = 'Cập nhật đơn ViettelPost'
    _inherit = 'vtp.shipping.wizard.mixin'

    vtp_bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn ViettelPost')
    order_status = fields.Integer(
        string='Trạng thái đơn hàng', 
        related='vtp_bill_id.vtp_order_status', 
        readonly=True
    )
    order_number = fields.Char(string='Mã vận đơn ViettelPost', required=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', required=True)

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Update information from picking"""
        if self.picking_id:
            # Set account and store from picking
            if self.picking_id.vtp_store_id:
                self.store_id = self.picking_id.vtp_store_id
                if self.picking_id.vtp_store_id.account_id:
                    self.account_id = self.picking_id.vtp_store_id.account_id

            # Update customer info
            self.partner_id = self.picking_id.partner_id

            # Update receiver info from partner
            if self.picking_id.partner_id:
                partner = self.picking_id.partner_id
                self.receiver_name = partner.name
                self.receiver_phone = partner.phone or partner.mobile
                self.receiver_address = partner.street
                if partner.state_id:
                    province = self.env['vtp.province'].search([
                        ('province_code', '=', partner.state_id.code)
                    ], limit=1)
                    if province:
                        self.receiver_province_id = province.id

                self.receiver_district_id = False
                self.receiver_ward_id = False

            # Build list item from picking
            list_item, unused_p, unused_w, unused_q = self._prepare_list_items()

            self.list_item = list_item
            self.product_price = unused_p
            self.product_weight = unused_w
            self.product_quantity = unused_q
            self.cod_amount = unused_p

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
            
            if vtp_bill and vtp_bill.order_number:
                res.update({
                    'picking_id': picking.id,
                    'order_number': vtp_bill.order_number,
                    'vtp_bill_id': vtp_bill.id,
                })

                # Set Store/Account from picking
                if picking.vtp_store_id:
                    res.update({
                        'store_id': picking.vtp_store_id.id,
                        'account_id': picking.vtp_store_id.account_id.id if picking.vtp_store_id.account_id else False,
                    })

                # Get latest history for defaults
                latest_history = self.env['vtp.order.bill.history'].search([
                    ('order_number', '=', vtp_bill.order_number)
                ], order='create_date desc', limit=1)
                
                if latest_history:
                    service_id = False
                    if latest_history.order_service:
                        service = self.env['vtp.service.bill'].search([
                            ('service_code', '=', latest_history.order_service)
                        ], limit=1)
                        service_id = service.id if service else False

                    order_payment_val = str(latest_history.order_payment) if latest_history.order_payment else False

                    res.update({
                        'service_type': service_id,
                        'order_payment': order_payment_val,
                        'product_weight': latest_history.product_weight or 0.0,
                        'cod_amount': latest_history.money_collection or 0.0,
                        'receiver_name': latest_history.receiver_fullname or picking.partner_id.name,
                    })
            else:
                raise UserError(_('Không tìm thấy mã vận đơn ViettelPost!'))
        return res

    def action_update_bill(self):
        """Update ViettelPost bill (only when ORDER_STATUS < 200)"""
        self.ensure_one()

        # Validate status
        if self.order_status is not False and int(self.order_status) >= 200:
            raise UserError(_('Chỉ được phép cập nhật đơn hàng khi trạng thái < 200.'))

        # Validate account and store
        if not self.account_id:
            raise UserError(_('Vui lòng chọn tài khoản ViettelPost!'))
            
        if not self.store_id:
            raise UserError(_('Vui lòng chọn Store ViettelPost!'))

        # Prepare LIST_ITEM safely
        list_item_payload = self.list_item
        if isinstance(list_item_payload, str):
            try:
                list_item_payload = json.loads(list_item_payload) or []
            except Exception:
                list_item_payload = []
        if not list_item_payload:
            try:
                computed_items, unused_p2, unused_w2, unused_q2 = self._prepare_list_items()
                list_item_payload = computed_items or []
            except Exception:
                list_item_payload = []

        # Prepare update data
        data = {
            'ORDER_NUMBER': self.picking_id.vtp_order_number,
            'GROUPADDRESS_ID': '',
            'CUS_ID': '',
            'SENDER_FULLNAME': self.store_id.name,
            'SENDER_ADDRESS': self.store_id.address,
            'SENDER_PHONE': self.store_id.phone,
            'RECEIVER_FULLNAME': self.receiver_name,
            'RECEIVER_ADDRESS': self.receiver_address,
            'PRODUCT_WEIGHT': int(self.product_weight) if self.product_weight else 0,
            'RECEIVER_PHONE': self.receiver_phone,
            'ORDER_PAYMENT': int(self.order_payment) if self.order_payment else 3,
            'ORDER_SERVICE': self.service_type.service_code if self.service_type else 'VSL6',
            'PRODUCT_TYPE': 'HH',
        }

        # Add dimensions if available
        if self.product_length and self.product_width and self.product_height:
            data.update({
                'PRODUCT_LENGTH': self.product_length,
                'PRODUCT_WIDTH': self.product_width,
                'PRODUCT_HEIGHT': self.product_height,
            })

        _logger.info("VTP Update Bill - Account: %s, Data: %s", self.account_id.name, data)

        # Call service with account (NEW: account parameter required)
        VTPService = self.env['vtp.service']
        result = VTPService.update_bill(
            account=self.account_id,
            data=data,
            order_bill=self.vtp_bill_id
        )

        if result and not isinstance(result, dict):
            # Success
            return self._success_notification(str(result))
        elif isinstance(result, dict) and result.get('ORDER_NUMBER'):
            return self._success_notification(result.get('ORDER_NUMBER'))
        else:
            error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else str(result)
            raise UserError(_('Lỗi khi cập nhật vận đơn: %s') % error_msg)
    
    def _success_notification(self, order_number):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã cập nhật vận đơn ViettelPost thành công: %s') % order_number,
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }