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
    order_bill_id = fields.Many2one('vtp.order.bill.history', string='Vận đơn ViettelPost',  ondelete='cascade')

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Cập nhật thông tin từ phiếu xuất kho"""
        if self.picking_id:
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
                
                # Tạm thời xóa domain để có thể chọn quận/huyện
                self.receiver_district_id = False
                self.receiver_ward_id = False

            # Build list item
            list_item, total_price, total_weight, total_quantity = self._prepare_list_items()

            # Gán vào wizard (giữ dạng list để phù hợp fields.Json)
            self.list_item = list_item
            self.product_price = total_price
            self.product_weight = total_weight
            self.product_quantity = total_quantity
            self.cod_amount = total_price
    
        
    def action_create_bill(self):
        """Tạo vận đơn ViettelPost"""
        self.ensure_one()


        if not self.store_id:
            raise UserError(_('Vui lòng chọn Store ViettelPost!'))
        
        # Chuẩn bị LIST_ITEM an toàn (không để False)
        list_item_payload = self.list_item
        if isinstance(list_item_payload, str):
            try:
                list_item_payload = json.loads(list_item_payload) or []
            except Exception:
                list_item_payload = []
        if not list_item_payload:
            # Tính lại từ picking nếu có
            try:
                computed_items, _, _, _ = self._prepare_list_items()
                list_item_payload = computed_items or []
            except Exception:
                list_item_payload = []

        # Chuẩn bị dữ liệu để tạo vận đơn
        data = {
            'ORDER_NUMBER': self.picking_id.name,
            'GROUPADDRESS_ID': int(self.store_id.groupaddressId),
            'CUS_ID': int(self.store_id.cusId),
            'DELIVERY_DATE': (self.picking_id.scheduled_date and self.picking_id.scheduled_date.strftime("%d/%m/%Y %H:%M:%S")),
            'SENDER_FULLNAME': self.store_id.name,
            'SENDER_ADDRESS': self.store_id.address,
            'SENDER_PHONE': self.store_id.phone,
            'SENDER_WARD': self.store_id.wardId.wardId,
            'SENDER_DISTRICT': self.store_id.districtId.districtId,
            'SENDER_PROVINCE': self.store_id.provinceId.provinceId,
            'RECEIVER_FULLNAME': self.receiver_name,
            'RECEIVER_ADDRESS': self.receiver_address,
            'RECEIVER_PHONE': self.receiver_phone,
            'RECEIVER_WARD': self.receiver_ward_id.wardId,
            'RECEIVER_DISTRICT': self.receiver_district_id.districtId,
            'RECEIVER_PROVINCE': self.receiver_province_id.provinceId,
            'PRODUCT_NAME': self.product_name,
            'PRODUCT_DESCRIPTION': self.note or '',
            'PRODUCT_QUANTITY': int(self.product_quantity),
            'PRODUCT_PRICE': int(self.product_price),
            'PRODUCT_WEIGHT': int(self.product_weight),
            'PRODUCT_TYPE': 'HH',
            'ORDER_PAYMENT': int(self.order_payment),
            'ORDER_SERVICE': self.service_type.service_code,
            'ORDER_SERVICE_ADD': '',
            'ORDER_VOUCHER': '',
            'MONEY_COLLECTION': int(self.cod_amount),
            'MONEY_TOTALFEE': int(self.pricing_id.money_total_fee),        
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
        
        _logger.info("Dữ liệu gửi lên API tạo vận đơn: %s", data)
        
        VTPService = self.env['vtp.service']
        result = VTPService.create_bill(data)

        if result and result.get('ORDER_NUMBER'):
            # Cập nhật trường vtp_store_id và đánh dấu đang chờ webhook
            self.picking_id.write({
                'vtp_store_id': self.store_id.id,
                'vtp_state': 'waiting_webhook'
            })

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': 'Đã tạo vận đơn ViettelPost thành công: %s' % result.get('ORDER_NUMBER'),
                    'sticky': False,
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            raise UserError(f"Không thể tạo vận đơn. Chi tiết: {result.get('error', 'Unknown error')}")

class VTPCheckFeeWizard(models.TransientModel):
    _name = 'vtp.check.fee.wizard'
    _description = 'Tra cước ViettelPost'
    _inherit = 'vtp.shipping.wizard.mixin'

    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', required=True)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', required=True, related='sale_order_id.partner_id', store=False)


    # Kết quả tra cước
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

            # Tổng hợp giá trị và trọng lượng từ SO line
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

    def action_calculate_fee(self):
        self.ensure_one()
        if not self.store_id or not self.receiver_province_id or not self.receiver_district_id:
            raise UserError(_('Vui lòng cung cấp đầy đủ thông tin địa chỉ!'))

        data = {
            "PRODUCT_WEIGHT": int(self.product_weight),
            "PRODUCT_PRICE": int(self.product_price),
            "MONEY_COLLECTION": int(self.cod_amount),
            "ORDER_SERVICE_ADD": "",
            "ORDER_SERVICE": self.service_type.service_code,
            "SENDER_PROVINCE": self.store_id.provinceId.provinceId,
            "SENDER_DISTRICT": self.store_id.districtId.districtId,
            "RECEIVER_PROVINCE": self.receiver_province_id.provinceId,
            "RECEIVER_DISTRICT": self.receiver_district_id.districtId,
            "PRODUCT_TYPE": "HH",
            "NATIONAL_TYPE": 1,
        }
        if self.product_length and self.product_width and self.product_height:
            data.update({
                'PRODUCT_LENGTH': self.product_length,
                'PRODUCT_WIDTH': self.product_width,
                'PRODUCT_HEIGHT': self.product_height,
            })

        _logger.info("Dữ liệu gửi lên API tính phí (SO): %s", data)
        VTPService = self.env['vtp.service']
        result = VTPService.calculate_fee(data)
        if result:
            pricing_vals = {
                'name': self.sale_order_id.name or _('Tra cước'),
                'store_id': self.store_id.id,
                'service_code': self.service_type.id if self.service_type else False,
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
            if self.pricing_id:
                self.pricing_id.write(pricing_vals)
            else:
                self.pricing_id = self.env['vtp.pricing'].create(pricing_vals)
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }
        else:
            raise UserError(_('Lỗi khi tính phí'))