from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)

class VTPUpdateBillWizard(models.TransientModel):
    _name = 'vtp.update.bill.wizard'
    _description = 'Cập nhật đơn ViettelPost'
    _inherit = 'vtp.shipping.wizard.mixin'

    order_bill_id = fields.Many2one('vtp.order.bill.history', string='Vận đơn ViettelPost',  ondelete='cascade')
    order_status = fields.Integer(string='Trạng thái đơn hàng', related='order_bill_id.order_status', readonly=True);
    order_number = fields.Char(string = 'Mã vận đơn ViettelPost', required=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', required=True)
        

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Cập nhật thông tin từ phiếu xuất kho"""
        if self.picking_id:
            # Gán sẵn tài khoản và store từ phiếu (nếu đã tạo vận đơn trước đó)
            if self.picking_id.vtp_store_id:
                self.store_id = self.picking_id.vtp_store_id
                if self.picking_id.vtp_store_id.account_id:
                    self.account_id = self.picking_id.vtp_store_id.account_id

            # Cập nhật thông tin khách hàng
            self.partner_id = self.picking_id.partner_id

            # Cập nhật thông tin người nhận từ partner
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

                # Reset để chọn lại quận/huyện
                self.receiver_district_id = False
                self.receiver_ward_id = False

            # Build list item từ picking
            list_item, total_price, total_weight, total_quantity = self._prepare_list_items()

            # Gán vào wizard
            self.list_item = list_item
            self.product_price = total_price
            self.product_weight = total_weight
            self.product_quantity = total_quantity
            self.cod_amount = total_price

    @api.model
    def default_get(self, fields_list):
        """Lấy thông tin mặc định từ phiếu giao hàng"""
        res = super().default_get(fields_list)
        if self._context.get('active_model') == 'stock.picking' and self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))

            
            # Lấy mã vận đơn từ vtp.order.bill
            order_bill = self.env['vtp.order.bill'].search([('order_id', '=', picking.id)], limit=1)
            if order_bill and order_bill.order_number:
                # Gán picking và mã vận đơn
                res.update({
                    'picking_id': picking.id,
                    'order_number': order_bill.order_number,
                })

                # Gán sẵn Store/Account từ picking nếu có
                if picking.vtp_store_id:
                    res.update({
                        'store_id': picking.vtp_store_id.id,
                        'account_id': picking.vtp_store_id.account_id.id if picking.vtp_store_id.account_id else False,
                    })

                # Lấy lịch sử mới nhất của vận đơn để điền các trường liên quan
                latest_history = self.env['vtp.order.bill.history'].search([
                    ('order_number', '=', order_bill.order_number)
                ], order='create_date desc', limit=1)
                if latest_history:
                    # Map service_code -> vtp.service.bill
                    service_id = False
                    if latest_history.order_service:
                        service = self.env['vtp.service.bill'].search([('service_code', '=', latest_history.order_service)], limit=1)
                        service_id = service.id if service else False

                    # order_payment trong history là int, selection của wizard là str
                    order_payment_val = str(latest_history.order_payment) if latest_history.order_payment else False

                    res.update({
                        'order_bill_id': latest_history.id,
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
        """Cập nhật vận đơn ViettelPost (chỉ khi ORDER_STATUS < 200)"""
        self.ensure_one()

        # Kiểm tra trạng thái đơn hàng
        if self.order_status is not False and int(self.order_status) >= 200:
            raise UserError(_('Chỉ được phép cập nhật đơn hàng khi trạng thái < 200.'))

        if not self.store_id:
            raise UserError(_('Vui lòng chọn Store ViettelPost!'))

        # Chuẩn bị LIST_ITEM an toàn
        list_item_payload = self.list_item
        if isinstance(list_item_payload, str):
            try:
                list_item_payload = json.loads(list_item_payload) or []
            except Exception:
                list_item_payload = []
        if not list_item_payload:
            try:
                computed_items, _, _, _ = self._prepare_list_items()
                list_item_payload = computed_items or []
            except Exception:
                list_item_payload = []


        # Chuẩn bị dữ liệu giống tạo vận đơn
        data = {
            'ORDER_NUMBER': self.order_number,
            'GROUPADDRESS_ID': '',
            'CUS_ID': '',
            'SENDER_FULLNAME': self.store_id.name,
            'SENDER_ADDRESS': self.store_id.address,
            'SENDER_PHONE': self.store_id.phone,
            'RECEIVER_FULLNAME': self.receiver_name,
            'RECEIVER_ADDRESS': self.receiver_address,
            'PRODUCT_WEIGHT': self.product_weight,
            'RECEIVER_PHONE': self.receiver_phone,
            'ORDER_PAYMENT': int(self.order_payment),
            'ORDER_SERVICE': self.service_type.service_code,
            'PRODUCT_TYPE': 'HH'
        }

        # Thêm kích thước nếu có
        if self.product_length and self.product_width and self.product_height:
            data.update({
                'PRODUCT_LENGTH': self.product_length,
                'PRODUCT_WIDTH': self.product_width,
                'PRODUCT_HEIGHT': self.product_height,
            })

        _logger.info("Dữ liệu gửi lên API cập nhật vận đơn: %s", data)

        VTPService = self.env['vtp.service']
        result = VTPService.update_bill(data)

        if result and result.get('ORDER_NUMBER'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': 'Đã cập nhật vận đơn ViettelPost thành công: %s' % result.get('ORDER_NUMBER'),
                    'sticky': False,
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            raise UserError("Lỗi khi cập nhật vận đơn: " + result.get('error', 'Unknown error'))