# -*- coding: utf-8 -*-
"""
VTP Order Bill Models - Enhanced with:
- Account relationship for multi-account support
- Token usage tracking for audit
- API audit log integration
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class VtpOrderBill(models.Model):
    _name = 'vtp.order.bill'
    _description = 'ViettelPost Order Bill'

    name = fields.Char(string='Mã đơn hàng', required=True)
    store_id = fields.Many2one('vtp.store', string='Store ViettelPost', index=True)
    
    # Account relationship - computed from store for multi-account support
    account_id = fields.Many2one(
        'vtp.account', 
        string='Tài khoản VTP',
        compute='_compute_account_id',
        store=True,
        index=True,
        readonly=True
    )
    
    order_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', index=True)
    sale_id = fields.Many2one('sale.order', related='order_id.sale_id', store=True, string='Đơn hàng')
    expected_delivery_date = fields.Date(string='Ngày giao hàng')
    order_number = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True, index=True)
    status_name = fields.Char(string='Trạng thái vận đơn', copy=False, readonly=True)
    vtp_bill_updated_date = fields.Datetime(string='Cập nhật lần cuối', readonly=True)
    vtp_order_status = fields.Integer(string='Mã trạng thái', copy=False, readonly=True)
    vtp_money_collection = fields.Float(string='Tiền thu hộ (COD)', copy=False, readonly=True)
    vtp_money_totalfee = fields.Float(string='Phí tổng', copy=False, readonly=True)
    vtp_money_total = fields.Float(string='Tổng tiền', copy=False, readonly=True)
    vtp_receiver_fullname = fields.Char(string='Người nhận', copy=False, readonly=True)
    vtp_product_weight = fields.Float(string='Trọng lượng', copy=False, readonly=True)
    vtp_pricing_ids = fields.One2many('vtp.pricing', 'order_id', string='Dịch vụ')
    bill_history_ids = fields.One2many('vtp.order.bill.history', 'bill_id', string='Lịch sử vận đơn')
    
    # Token usage tracking - for audit "đơn này dùng token nào"
    created_with_token = fields.Char(
        string='Token used (last 10 chars)', 
        size=10, 
        readonly=True,
        help='Last 10 characters of token used to create this bill'
    )
    
    # API Audit logs
    api_audit_ids = fields.One2many('vtp.api.audit', 'order_bill_id', string='API Audit Logs')
    
    @api.depends('store_id', 'store_id.account_id')
    def _compute_account_id(self):
        """Đặt tài khoản từ store"""
        for record in self:
            record.account_id = record.store_id.account_id if record.store_id else False
    
    def _track_token_usage(self, token):
        """Theo dõi token được sử dụng để tạo/cập nhật vận đơn"""
        self.ensure_one()
        if token:
            self.created_with_token = token[-10:]  # Only store last 10 chars for security
    
    def action_create_vtp_bill(self):
        """Mở wizard để tạo vận đơn ViettelPost"""
        self.ensure_one()
        if self.order_number:
            raise UserError(_('Phiếu xuất kho này đã có mã vận đơn ViettelPost!'))
        
        # Kiểm tra địa chỉ giao hàng
        if not self.order_id.partner_id or not self.order_id.partner_id.street:
            raise UserError(_('Vui lòng cập nhật đầy đủ địa chỉ giao hàng!'))
        
        # Lấy store mặc định từ tài khoản
        default_store = False
        default_account = False
        
        if self.store_id:
            default_store = self.store_id
            default_account = self.store_id.account_id
        else:
            # Tìm store mặc định
            default_store = self.env['vtp.store'].search([
                ('is_default', '=', True),
                ('active', '=', True)
            ], limit=1)
            if default_store:
                default_account = default_store.account_id
        
        return {
            'name': _('Tạo vận đơn ViettelPost'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'vtp.create.bill.wizard',
            'target': 'new',
            'context': {
                'default_picking_id': self.order_id.id,
                'default_partner_id': self.sale_id.partner_id.id if self.sale_id else False,
                'default_order_bill_id': self.id,
                'default_store_id': default_store.id if default_store else False,
                'default_account_id': default_account.id if default_account else False,
            }
        }
    
    def action_view_audit_logs(self):
        """Xem API audit logs cho vận đơn này"""
        self.ensure_one()
        return {
            'name': _('API Audit Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'vtp.api.audit',
            'view_mode': 'tree,form',
            'domain': [('order_bill_id', '=', self.id)],
            'context': {'default_order_bill_id': self.id},
        }
    
    @api.model
    def create_update_bill_from_webhook(self, data):
        """Tạo hoặc cập nhật vận đơn từ dữ liệu webhook"""
        order_number = data.get('ORDER_NUMBER')
        order_reference = data.get('ORDER_REFERENCE')

        if not order_number:
            _logger.warning("ORDER_NUMBER not found in webhook data.")
            return False

        bill = self.search([('order_number', '=', order_number)], limit=1)

        # Get picking to find store
        picking = self.env['stock.picking'].search([('name', '=', order_reference)], limit=1)
        store_id = picking.vtp_store_id.id if picking and picking.vtp_store_id else False
        
        # If no store in picking, try current bill
        if not store_id and bill and bill.store_id:
            store_id = bill.store_id.id
        
        # Parse dates safely
        def parse_vtp_date(date_str):
            if not date_str:
                return False
            try:
                return datetime.strptime(date_str, '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                except:
                    return False
        
        bill_data = {
            'name': order_reference,
            'order_number': order_number,
            'store_id': store_id,
            'order_id': picking.id if picking else False,
            'status_name': data.get('STATUS_NAME'),
            'vtp_order_status': data.get('ORDER_STATUS'),
            'vtp_bill_updated_date': parse_vtp_date(data.get('ORDER_STATUSDATE')),
            'vtp_money_collection': data.get('MONEY_COLLECTION', 0.0),
            'vtp_money_totalfee': data.get('MONEY_TOTALFEE', 0.0),
            'vtp_money_total': data.get('MONEY_TOTAL', 0.0),
            'vtp_receiver_fullname': data.get('RECEIVER_FULLNAME'),
            'vtp_product_weight': data.get('PRODUCT_WEIGHT', 0.0),
            'expected_delivery_date': parse_vtp_date(data.get('EXPECTED_DELIVERY_DATE')),
        }

        if bill:
            _logger.info(f"Cập nhật bill hiện có: {bill.name}")
            bill.write(bill_data)
        else:
            _logger.info(f"Tạo mới bill cho mã vận đơn: {order_number}")
            if picking:
                bill_data['order_id'] = picking.id
            bill = self.create(bill_data)

        # Cập nhật trạng thái của picking theo trạng thái của ViettelPost
        if picking:
            vtp_status = data.get('ORDER_STATUS')
            status_mapping = {
                101: 'canceled',        # ViettelPost yêu cầu hủy đơn hàng
                102: 'waiting_webhook', # Đơn hàng chờ xử lý
                103: 'created',         # Giao cho bưu cục
                104: 'created',         # Giao cho Bưu tá đi nhận
                105: 'created',         # Bưu tá đã nhận hàng
                106: 'created',         # Đối tác yêu cầu lấy lại hàng
                107: 'draft',           # Đối tác yêu cầu hủy qua API
                200: 'created',         # Nhận từ bưu tá - Bưu cục gốc
                201: 'canceled',        # Hủy nhập phiếu gửi
                202: 'created',         # Sửa phiếu gửi
                300: 'created',         # Khai thác đi
                400: 'created',         # Khai thác đến
                500: 'created',         # Giao bưu tá đi phát
                501: 'done',            # Phát thành công
                502: 'created',         # Chuyển hoàn bưu cục gốc
                503: 'canceled',        # Hủy - Theo yêu cầu khách hàng
                504: 'done',            # Thành công - Chuyển trả cho người gửi
                505: 'created',         # Tồn - Thông báo chuyển hoàn bưu cục gốc
                506: 'created',         # Tồn - Khách hàng nghỉ, không có nhà
                507: 'created',         # Tồn - Khách hàng đến bưu cục nhận
                508: 'created',         # Phát tiếp
                509: 'created',         # Chuyển tiếp bưu cục khác
                515: 'created',         # Duyệt hoàn
                550: 'created',         # Phát tiếp
            }

            vals = {
                'vtp_order_number': order_number,
                'vtp_status_name': data.get('STATUS_NAME')
            }

            if vtp_status:
                vtp_status = int(vtp_status)
                if vtp_status in status_mapping:
                    vals['vtp_state'] = status_mapping[vtp_status]

            picking.write(vals)

        # Create bill history
        self.env['vtp.order.bill.history'].create_bill_history_from_webhook(bill.id, data)
        return bill


class VtpOrderBillHistory(models.Model):
    _name = 'vtp.order.bill.history'
    _description = 'ViettelPost Order Bill History'
    _order = 'order_status_date desc'
    
    bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn', ondelete='cascade', index=True)
    name = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True)
    order_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', index=True)
    
    order_number = fields.Char("Mã đơn hàng VTP", index=True)
    order_reference = fields.Char("Mã đơn hàng")
    order_status_date = fields.Datetime(string='Ngày thay đổi', index=True)
    order_status = fields.Integer("Mã trạng thái")
    status_name = fields.Char("Tên trạng thái")
    location_currently = fields.Char("Địa điểm hiện tại")
    money_collection = fields.Float("Tiền thu hộ (COD)")
    note = fields.Text("Ghi chú")
    money_feecod = fields.Float("Phí COD")
    money_totalfee = fields.Float("Phí tổng")
    money_total = fields.Float("Tổng tiền")
    money_totalvat = fields.Float("Thuế VAT")
    expected_delivery_date = fields.Datetime("Thời gian dự kiến")
    product_weight = fields.Float("Trọng lượng")
    receiver_fullname = fields.Char("Người nhận")
    order_payment = fields.Integer("Phương thức thanh toán")
    order_service = fields.Char("Dịch vụ")
    is_returning = fields.Boolean("Trả hàng")

    @api.model
    def create_bill_history_from_webhook(self, bill_id, data):
        """Tạo lịch sử vận đơn từ dữ liệu webhook"""
        order_number = data.get('ORDER_NUMBER')
        order_reference = data.get('ORDER_REFERENCE')

        bill = self.env['vtp.order.bill'].browse(bill_id)
        
        # Parse dates safely
        def parse_vtp_date(date_str):
            if not date_str:
                return False
            try:
                return datetime.strptime(date_str, '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                try:
                    return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
                except:
                    return False

        history_data = {
            'bill_id': bill.id,
            'name': order_number,
            'order_id': bill.order_id.id if bill.order_id else False,
            'order_number': order_number,
            'order_reference': order_reference,
            'order_status_date': parse_vtp_date(data.get('ORDER_STATUSDATE')),
            'order_status': data.get('ORDER_STATUS'),
            'status_name': data.get('STATUS_NAME'),
            'location_currently': data.get('LOCATION_CURRENTLY'),
            'note': data.get('NOTE'),
            'money_collection': data.get('MONEY_COLLECTION', 0.0),
            'money_feecod': data.get('MONEY_FEECOD', 0.0),
            'money_totalfee': data.get('MONEY_TOTALFEE', 0.0),
            'money_totalvat': data.get('MONEY_TOTALVAT', 0.0),
            'money_total': data.get('MONEY_TOTAL', 0.0),
            'product_weight': data.get('PRODUCT_WEIGHT', 0.0),
            'order_service': data.get('ORDER_SERVICE'),
            'order_payment': data.get('ORDER_PAYMENT', 0),
            'expected_delivery_date': parse_vtp_date(data.get('EXPECTED_DELIVERY_DATE')),
            'is_returning': data.get('IS_RETURNING', False),
            'receiver_fullname': data.get('RECEIVER_FULLNAME'),
        }
        self.create(history_data)

        return bill


class VtpStockPicking(models.Model):
    _inherit = 'stock.picking'
    
    vtp_id = fields.Many2one('vtp.order.bill', string='Vận đơn VTP')
    vtp_order_bill_history_ids = fields.One2many('vtp.order.bill.history', 'order_id', string='Lịch sử vận đơn VTP')
    vtp_store_id = fields.Many2one('vtp.store', string='Store ViettelPost')
    
    # Computed account from store
    vtp_account_id = fields.Many2one(
        'vtp.account',
        string='Tài khoản VTP',
        related='vtp_store_id.account_id',
        store=True,
        readonly=True
    )
    
    vtp_state = fields.Selection([
        ('draft', 'Nháp'),
        ('waiting_webhook', 'Đang chờ xử lý'),
        ('created', 'Đã tạo'),
        ('done', 'Đã hoàn thành'),
        ('canceled', 'Đã hủy'),
    ], string='Trạng thái VTP', default='draft')
    vtp_order_number = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True, index=True)
    vtp_status_name = fields.Char(string='Trạng thái vận đơn', copy=False, readonly=True)


class VtpSaleOrder(models.Model):
    _inherit = 'sale.order'
    
    vtp_id = fields.Many2one('vtp.order.bill', string='Vận đơn VTP')
    vtp_store_id = fields.Many2one('vtp.store', string='Store ViettelPost')
    
    # Computed account from store
    vtp_account_id = fields.Many2one(
        'vtp.account',
        string='Tài khoản VTP',
        related='vtp_store_id.account_id',
        store=True,
        readonly=True
    )
