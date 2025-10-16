from odoo import models, fields, _
from odoo import api, fields, models, _


class VTPShippingWizardMixin(models.AbstractModel):
    _name = 'vtp.shipping.wizard.mixin'
    _description = 'ViettelPost Shipping Wizard Mixin'
    
    # Thông tin tài khoản và cửa hàng
    account_id = fields.Many2one('vtp.account', string='Tài khoản ViettelPost', required=True)
    store_id = fields.Many2one('vtp.store', string='Store ViettelPost', required=True,
                             domain="[('account_id', '=', account_id)]")
    partner_id = fields.Many2one('res.partner', string='Khách hàng', required=True)
    
    # Thông tin người nhận
    receiver_name = fields.Char(string='Tên người nhận', required=True)
    receiver_phone = fields.Char(string='Số điện thoại', required=True)
    receiver_address = fields.Char(string='Địa chỉ', required=True)
    receiver_province_id = fields.Many2one('vtp.province', string='Tỉnh/Thành phố', required=True)
    receiver_district_id = fields.Many2one('vtp.district', string='Quận/Huyện', required=True, 
                                         domain="[('provinceId', '=', receiver_province_id)]")
    receiver_ward_id = fields.Many2one('vtp.ward', string='Phường/Xã', required=True, 
                                     domain="[('districtId', '=', receiver_district_id)]")
    
    # Thông tin hàng hóa
    product_name = fields.Char(string='Tên hàng hóa', default='Hàng hóa')
    product_price = fields.Float(string='Giá trị hàng hóa')
    product_weight = fields.Float(string='Trọng lượng (gram)', required=True)
    product_length = fields.Float(string='Chiều dài (cm)', required=True)
    product_width = fields.Float(string='Chiều rộng (cm)', required=True)
    product_height = fields.Float(string='Chiều cao (cm)', required=True)
    list_item = fields.Json(string='Danh sách hàng hóa')
    product_quantity = fields.Integer(string = 'Số lượng')
    
    # Thông tin dịch vụ
    service_type = fields.Many2one('vtp.service.bill', string='Dịch vụ', required=True, default= lambda self: self._default_service_type())
    cod_amount = fields.Float(string='Tiền thu hộ (COD)')
    pricing_id = fields.Many2one('vtp.pricing', string='Thông tin phí')
    
    order_payment = fields.Selection([
        ('1', 'Không thu tiền'),
        ('2', 'Thu phí vận chuyển và giá trị hàng hóa'),
        ('3', 'Thu giá trị hàng hóa'),
        ('4', 'Thu phí vận chuyển')
    ], string='Phương thức thanh toán', default='3')
    
    note = fields.Text(string='Ghi chú')
    
    company_type = fields.Selection(
        related='partner_id.company_type', string='Loại khách hàng', default='company')

    def _default_service_type(self):
        return self.env['vtp.service.bill'].search([('service_code', '=', 'VSL6')], limit=1)
    
    @api.onchange('account_id')
    def _onchange_account_id(self):
        """Khi đổi tài khoản VTP thì reset store để buộc chọn lại theo tài khoản"""
        if self.account_id and self.store_id and self.store_id.account_id != self.account_id:
            self.store_id = False
    
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Cập nhật thông tin người nhận khi thay đổi khách hàng"""
        if self.partner_id:
            self.receiver_name = self.partner_id.name
            self.receiver_phone = self.partner_id.phone or self.partner_id.mobile
            self.receiver_address = self.partner_id.street or ''
            
            # Tìm và gán tỉnh/thành phố nếu có
            if self.partner_id.state_id:
                province = self.env['vtp.province'].search([
                    ('province_code', '=', self.partner_id.state_id.code)
                ], limit=1)
                if province:
                    self.receiver_province_id = province
                    
            # Reset quận/huyện và phường/xã
            self.receiver_district_id = False
            self.receiver_ward_id = False
            
    @api.onchange('receiver_province_id')
    def _onchange_receiver_province_id(self):
        if self.receiver_province_id:
            self.receiver_district_id = False
            self.receiver_ward_id = False

    def _prepare_list_items(self):
        """Build LIST_ITEM từ picking để gửi API"""
        self.ensure_one()
        list_item = []
        total_price = 0
        total_weight = 0
        total_quantity = 0

        for move_line in self.picking_id.move_line_ids_without_package:
            if move_line.product_id:
                qty = move_line.qty_done

            # Giá ưu tiên từ sale_line, fallback sang list_price
            price_unit = move_line.product_id.list_price if move_line.product_id.list_price else move_line.product_id.lst_price
            product_price = price_unit * qty
            total_price += product_price

            # Trọng lượng (kg → gram)
            weight = (move_line.product_id.weight) * qty * 1000
            total_weight += weight
            total_quantity += qty

            list_item.append({
                "PRODUCT_NAME": move_line.product_id.display_name,
                "PRODUCT_PRICE": int(product_price),
                "PRODUCT_WEIGHT": int(weight),
                "PRODUCT_QUANTITY": int(qty),
            })
        return list_item, total_price, total_weight, total_quantity