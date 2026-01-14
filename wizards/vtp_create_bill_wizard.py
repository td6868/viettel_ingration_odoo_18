# -*- coding: utf-8 -*-
"""
VTP Create Bill and Check Fee Wizards - Refactored with:
- Multi-account support (all API calls require account)
- Proper account validation
- Order bill tracking for audit
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)


class VTPCreateBillWizard(models.TransientModel):
    _name = 'vtp.create.bill.wizard'
    _description = 'Tạo vận đơn ViettelPost'    
    _inherit = 'vtp.shipping.wizard.mixin'
    
    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True)
    vtp_bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn ViettelPost')

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Update information from picking"""
        if self.picking_id:
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

            # Build list item
            list_item, unused_price, unused_weight, unused_qty = self._prepare_list_items()

            self.list_item = list_item
            self.product_price = unused_price
            self.product_weight = unused_weight
            self.product_quantity = unused_qty
            self.cod_amount = unused_price
            
            # Auto-select account and store from picking if available
            if self.picking_id.vtp_store_id:
                self.store_id = self.picking_id.vtp_store_id
                self.account_id = self.picking_id.vtp_store_id.account_id
    
    def action_create_bill(self):
        """Create ViettelPost shipping bill"""
        self.ensure_one()

        # Validate account and store
        if not self.account_id:
            raise UserError(_('Vui lòng chọn tài khoản ViettelPost!'))
        
        if not self.store_id:
            raise UserError(_('Vui lòng chọn Store ViettelPost!'))
        
        # Validate store belongs to account
        if self.store_id.account_id != self.account_id:
            raise UserError(_('Store không thuộc tài khoản đã chọn!'))
        
        # Prepare LIST_ITEM safely
        list_item_payload = self.list_item
        if isinstance(list_item_payload, str):
            try:
                list_item_payload = json.loads(list_item_payload) or []
            except Exception:
                list_item_payload = []
        if not list_item_payload:
            try:
                computed_items, unused_p, unused_w, unused_q = self._prepare_list_items()
                list_item_payload = computed_items or []
            except Exception:
                list_item_payload = []

        # Prepare bill data
        data = {
            'ORDER_NUMBER': self.picking_id.name,
            'GROUPADDRESS_ID': int(self.store_id.groupaddressId) if self.store_id.groupaddressId else 0,
            'CUS_ID': int(self.store_id.cusId) if self.store_id.cusId else 0,
            'DELIVERY_DATE': (self.picking_id.scheduled_date and self.picking_id.scheduled_date.strftime("%d/%m/%Y %H:%M:%S")),
            'SENDER_FULLNAME': self.store_id.name,
            'SENDER_ADDRESS': self.store_id.address,
            'SENDER_PHONE': self.store_id.phone,
            'SENDER_WARD': self.store_id.wardId.wardId if self.store_id.wardId else '',
            'SENDER_DISTRICT': self.store_id.districtId.districtId if self.store_id.districtId else '',
            'SENDER_PROVINCE': self.store_id.provinceId.provinceId if self.store_id.provinceId else '',
            'RECEIVER_FULLNAME': self.receiver_name,
            'RECEIVER_ADDRESS': self.receiver_address,
            'RECEIVER_PHONE': self.receiver_phone,
            'RECEIVER_WARD': self.receiver_ward_id.wardId if self.receiver_ward_id else '',
            'RECEIVER_DISTRICT': self.receiver_district_id.districtId if self.receiver_district_id else '',
            'RECEIVER_PROVINCE': self.receiver_province_id.provinceId if self.receiver_province_id else '',
            'PRODUCT_NAME': self.product_name or 'Hàng hóa',
            'PRODUCT_DESCRIPTION': self.note or '',
            'PRODUCT_QUANTITY': int(self.product_quantity) if self.product_quantity else 1,
            'PRODUCT_PRICE': int(self.product_price) if self.product_price else 0,
            'PRODUCT_WEIGHT': int(self.product_weight) if self.product_weight else 0,
            'PRODUCT_TYPE': 'HH',
            'ORDER_PAYMENT': int(self.order_payment) if self.order_payment else 3,
            'ORDER_SERVICE': self.service_type.service_code if self.service_type else 'VSL6',
            'ORDER_SERVICE_ADD': '',
            'ORDER_VOUCHER': '',
            'MONEY_COLLECTION': int(self.cod_amount) if self.cod_amount else 0,
            'MONEY_TOTALFEE': int(self.pricing_id.money_total_fee) if self.pricing_id else 0,        
            'LIST_ITEM': list_item_payload,    
            'NOTE': self.note or self.picking_id.name,
        }
        
        # Thêm kích thước nếu có
        if self.product_length and self.product_width and self.product_height:
            data.update({
                'PRODUCT_LENGTH': self.product_length,
                'PRODUCT_WIDTH': self.product_width,
                'PRODUCT_HEIGHT': self.product_height,
            })
        
        _logger.info("VTP Create Bill - Account: %s, Store: %s, Data: %s", 
                     self.account_id.name, self.store_id.name, data)
        
        # Call service with account (NEW: account parameter required)
        VTPService = self.env['vtp.service']
        result = VTPService.create_bill(
            account=self.account_id,
            data=data,
            order_bill=self.vtp_bill_id
        )

        if result and not isinstance(result, dict):
            # Success - result is the order data
            order_number = result if isinstance(result, str) else result.get('ORDER_NUMBER')
            self._update_picking_after_create(order_number)
            return self._success_notification(order_number)
            
        elif isinstance(result, dict) and result.get('ORDER_NUMBER'):
            # Success - dict with ORDER_NUMBER
            order_number = result.get('ORDER_NUMBER')
            self._update_picking_after_create(order_number)
            return self._success_notification(order_number)
            
        else:
            # Error
            error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else str(result)
            if 'Price does not apply to this itinerary' in error_msg:
                raise UserError(_('Giá không áp dụng cho tuyến này!'))
            raise UserError(_('Không thể tạo vận đơn. Chi tiết: %s') % error_msg)
    
    def _update_picking_after_create(self, order_number):
        """Update picking after successful bill creation"""
        self.picking_id.write({
            'vtp_store_id': self.store_id.id,
            'vtp_state': 'waiting_webhook',
            'vtp_order_number': order_number,
        })
        
        # Update order_bill if exists
        if self.vtp_bill_id:
            self.vtp_bill_id.write({
                'order_number': order_number,
                'store_id': self.store_id.id,
            })
            # Track token usage
            if hasattr(self.vtp_bill_id, '_track_token_usage'):
                self.vtp_bill_id._track_token_usage(self.account_id.token)
    
    def _success_notification(self, order_number):
        """Return success notification"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã tạo vận đơn ViettelPost thành công: %s') % order_number,
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }


class VTPCheckFeeWizard(models.TransientModel):
    _name = 'vtp.check.fee.wizard'
    _description = 'Tra cước ViettelPost'
    _inherit = 'vtp.shipping.wizard.mixin'

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', required=True)
    partner_id = fields.Many2one(
        'res.partner', 
        string='Khách hàng', 
        required=True, 
        related='sale_order_id.partner_id', 
        store=False
    )

    # Fee calculation results
    pricing_id = fields.Many2one('vtp.pricing', string='Tra cước')
    money_total_old = fields.Integer(related='pricing_id.money_total_old', readonly=True)
    money_total = fields.Integer(related='pricing_id.money_total', readonly=True)
    money_total_fee = fields.Integer(related='pricing_id.money_total_fee', readonly=True)
    money_fee = fields.Integer(related='pricing_id.money_fee', readonly=True)
    money_collection_fee = fields.Integer(related='pricing_id.money_collection_fee', readonly=True)
    money_other_fee = fields.Integer(related='pricing_id.money_other_fee', readonly=True)
    money_vas = fields.Integer(related='pricing_id.money_vas', readonly=True)
    money_vat = fields.Integer(related='pricing_id.money_vat', readonly=True)
    kpi_ht = fields.Integer(related='pricing_id.kpi_ht', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        
        if self._context.get('active_model') == 'sale.order' and self._context.get('active_id'):
            so = self.env['sale.order'].browse(self._context.get('active_id'))
            if so:
                res.update({'sale_order_id': so.id, 'partner_id': so.partner_id.id})
                
                # Get last pricing
                last_pricing = self.env['vtp.pricing'].search([
                    ('sale_order_id', '=', so.id)
                ], order='create_date desc', limit=1)

                # Prefer store: SO.vtp_store_id -> last_pricing.store_id
                pref_store = so.vtp_store_id or (last_pricing.store_id if last_pricing else False)
                if pref_store:
                    res.update({
                        'store_id': pref_store.id,
                        'account_id': pref_store.account_id.id if pref_store.account_id else False,
                    })

                if last_pricing:
                    res.update({
                        'pricing_id': last_pricing.id,
                        'service_type': last_pricing.service_code,
                    })
        return res

    @api.onchange('account_id')
    def _onchange_account_id_fee(self):
        if self.account_id and self.store_id and self.store_id.account_id != self.account_id:
            self.store_id = False

    @api.onchange('store_id')
    def _onchange_store_id_fee(self):
        if self.store_id:
            if not self.account_id or self.account_id != self.store_id.account_id:
                self.account_id = self.store_id.account_id

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id:
            so = self.sale_order_id
            self.partner_id = so.partner_id
            if so.partner_id:
                partner = so.partner_id
                self.receiver_name = partner.name
                self.receiver_phone = partner.phone or partner.mobile
                self.receiver_address = partner.street or ''
                if partner.state_id:
                    province = self.env['vtp.province'].search([
                        ('province_code', '=', partner.state_id.code)
                    ], limit=1)
                    if province:
                        self.receiver_province_id = province.id
                self.receiver_district_id = False
                self.receiver_ward_id = False

            # Calculate totals from SO lines
            total_price = 0
            total_weight = 0
            for line in so.order_line:
                qty = line.product_uom_qty
                price_unit = line.price_unit
                total_price += price_unit * qty
                total_weight += (line.product_id.weight or 0.0) * qty * 1000
            self.product_price = total_price
            self.product_weight = total_weight
            self.cod_amount = total_price

            # Load last pricing if available
            last_pricing = self.env['vtp.pricing'].search([
                ('sale_order_id', '=', so.id)
            ], order='create_date desc', limit=1)
            if last_pricing:
                self.pricing_id = last_pricing.id

    def action_calculate_fee(self):
        """Calculate shipping fee"""
        self.ensure_one()
        
        # Validate account and store
        if not self.account_id:
            raise UserError(_('Vui lòng chọn tài khoản ViettelPost!'))
        
        if not self.store_id:
            raise UserError(_('Vui lòng chọn Store ViettelPost!'))
        
        if not self.receiver_province_id or not self.receiver_district_id:
            raise UserError(_('Vui lòng cung cấp đầy đủ thông tin địa chỉ!'))

        data = {
            "PRODUCT_WEIGHT": int(self.product_weight) if self.product_weight else 0,
            "PRODUCT_PRICE": int(self.product_price) if self.product_price else 0,
            "MONEY_COLLECTION": int(self.cod_amount) if self.cod_amount else 0,
            "ORDER_SERVICE_ADD": "",
            "ORDER_SERVICE": self.service_type.service_code if self.service_type else 'VSL6',
            "SENDER_PROVINCE": self.store_id.provinceId.provinceId if self.store_id.provinceId else '',
            "SENDER_DISTRICT": self.store_id.districtId.districtId if self.store_id.districtId else '',
            "RECEIVER_PROVINCE": self.receiver_province_id.provinceId if self.receiver_province_id else '',
            "RECEIVER_DISTRICT": self.receiver_district_id.districtId if self.receiver_district_id else '',
            "PRODUCT_TYPE": "HH",
            "NATIONAL_TYPE": 1,
        }
        
        if self.product_length and self.product_width and self.product_height:
            data.update({
                'PRODUCT_LENGTH': self.product_length,
                'PRODUCT_WIDTH': self.product_width,
                'PRODUCT_HEIGHT': self.product_height,
            })

        _logger.info("VTP Calculate Fee - Account: %s, Data: %s", self.account_id.name, data)
        
        # Call service with account (NEW: account parameter required)
        VTPService = self.env['vtp.service']
        result = VTPService.calculate_fee(
            account=self.account_id,
            data=data
        )
        
        # Handle error
        if not result or (isinstance(result, dict) and result.get('error')):
            error_msg = result.get('error') if isinstance(result, dict) else _('Unknown error')
            if 'Price does not apply to this itinerary' in str(error_msg):
                raise UserError(_('Giá không áp dụng cho tuyến này!'))
            raise UserError(_('Không thể tra phí vận đơn. Chi tiết: %s') % error_msg)

        # Save pricing result
        pricing_vals = {
            'name': self.sale_order_id.name or _('Tra cước'),
            'store_id': self.store_id.id,
            'service_code': self.service_type.id if self.service_type else False,
            'sale_order_id': self.sale_order_id.id,
            'money_total_old': result.get('MONEY_TOTAL', 0.0),
            'money_total': result.get('MONEY_TOTAL', 0.0),
            'money_total_fee': result.get('MONEY_TOTAL_FEE', 0.0),
            'money_fee': result.get('MONEY_FEE', 0.0),
            'money_collection_fee': result.get('MONEY_COLLECTION_FEE', 0.0),
            'money_other_fee': result.get('MONEY_OTHER_FEE', 0.0),
            'money_vas': result.get('MONEY_VAS', 0.0),
            'money_vat': result.get('MONEY_VAT', 0.0),
            'kpi_ht': result.get('KPI_HT', 0),
            'vtp_response': str(result),
        }

        _logger.info("Fee calculation result: %s", pricing_vals)

        try:
            if self.pricing_id:
                self.pricing_id.write(pricing_vals)
            else:
                self.pricing_id = self.env['vtp.pricing'].create(pricing_vals)
        except Exception as e:
            _logger.error("Error saving pricing result: %s", e)
            raise UserError(_('Không thể lưu kết quả tra cước. Chi tiết: %s') % str(e))

        # Save store to Sale Order for next time
        if self.sale_order_id and self.store_id:
            try:
                self.sale_order_id.write({'vtp_store_id': self.store_id.id})
            except Exception as e:
                _logger.warning("Could not save vtp_store_id to Sale Order: %s", e)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã tra phí vận đơn thành công'),
                'sticky': False,
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'vtp.check.fee.wizard',
                    'res_id': self.id,
                    'views': [[False, 'form']],
                    'target': 'new',
                }
            }
        }