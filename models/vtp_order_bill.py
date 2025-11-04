from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime

class VtpOrderBill(models.Model):
    _name = 'vtp.order.bill'
    _description = 'ViettelPost Order Bill'

    name = fields.Char(string='Mã đơn hàng', required=True)
    store_id = fields.Many2one('vtp.store', string='Store ViettelPost')
    order_id = fields.Many2one('stock.picking', string='Phiếu giao hàng')
    sale_id = fields.Many2one('sale.order', related='order_id.sale_id', store=True, string='Đơn hàng')
    expected_delivery_date = fields.Date(string='Ngày giao hàng')
    order_number = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True)
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
    
    
    def action_create_vtp_bill(self):
        """Mở wizard để tạo vận đơn ViettelPost"""
        self.ensure_one()
        if self.order_number:
            raise UserError(_('Phiếu xuất kho này đã có mã vận đơn ViettelPost!'))
        
        # Kiểm tra địa chỉ giao hàng
        if not self.order_id.partner_id or not self.order_id.partner_id.street or not self.order_id.partner_id.city:
            raise UserError(_('Vui lòng cập nhật đầy đủ địa chỉ giao hàng!'))
        
        # Lấy store mặc định nếu chưa có
        if not self.store_id:
            default_store_id = int(self.env['ir.config_parameter'].sudo().get_param('viettelpost.default_store_id', default=0))
            if default_store_id:
                self.store_id = default_store_id
        
        return {
            'name': _('Tạo vận đơn ViettelPost'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'vtp.create.bill.wizard',
            'target': 'new',
            'context': {
                'default_picking_id': self.order_id.id,
                'default_partner_id': self.sale_id.partner_id.id,
                'default_order_bill_id': self.id,
                'default_store_id': self.store_id.id if self.store_id else False,
                'default_account_id': self.store_id.account_id.id if self.store_id and self.store_id.account_id else False,
                'default_cod_amount': self.vtp_cod_amount,
                'default_insurance_value': self.vtp_insurance_value,
                'default_note': self.vtp_note,
            }
        }
    @api.model
    def create_update_bill_from_webhook(self, data):
        
        order_number = data.get('ORDER_NUMBER')
        order_reference = data.get('ORDER_REFERENCE')

        if not order_number:
            print("ORDER_NUMBER not found in webhook data.")
            return False

        bill = self.search([('order_number', '=', order_number)], limit=1)

        # Lấy thông tin picking để lấy store
        picking = self.env['stock.picking'].search([('name', '=', order_reference)], limit=1)
        store_id = picking.vtp_store_id.id if picking and picking.vtp_store_id else False
        
        # Nếu không có store trong picking, thử tìm trong bill hiện tại
        if not store_id and bill and bill.store_id:
            store_id = bill.store_id.id
        
        bill_data = {
            'name': order_reference,
            'order_number': order_number,
            'store_id': store_id,
            'order_id': picking.id if picking else False,
            'status_name': data.get('STATUS_NAME'),
            'vtp_order_status': data.get('ORDER_STATUS'),
            'vtp_bill_updated_date': datetime.strptime(data.get('ORDER_STATUSDATE'), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') if data.get('ORDER_STATUSDATE') else False,
            'vtp_money_collection': data.get('MONEY_COLLECTION', 0.0),
            'vtp_money_totalfee': data.get('MONEY_TOTALFEE', 0.0),
            'vtp_money_total': data.get('MONEY_TOTAL', 0.0),
            'vtp_receiver_fullname': data.get('RECEIVER_FULLNAME'),
            'vtp_product_weight': data.get('PRODUCT_WEIGHT', 0.0),
            'expected_delivery_date': datetime.strptime(data.get('EXPECTED_DELIVERY_DATE'), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') if data.get('EXPECTED_DELIVERY_DATE') else False,
        }

        if bill:
            print(f"Updating existing bill: {bill.name}")
            bill.write(bill_data)
        else:
            print(f"Creating new bill for order number: {order_number}")
            if picking:
                bill_data['order_id'] = picking.id
                bill_data['sale_id'] = picking.sale_id.id if picking.sale_id else False
            bill = self.create(bill_data)


        # Cập nhật trạng thái picking dựa trên trạng thái từ ViettelPost
        if picking or picking.vtp_state == 'waiting_webhook':
            vtp_status = data.get('ORDER_STATUS')
            # Cập nhật order_number và status_name cho picking
            picking.write({
                'vtp_order_number': order_number,
                'vtp_status_name': data.get('STATUS_NAME')
            })
            
            if vtp_status:
                vtp_status = int(vtp_status)
                
                #Đưa thành JSON={key: result} => JSON[vtp_status]=picking
                
                # Mã 101: ViettelPost yêu cầu hủy đơn hàng
                if vtp_status == 101:
                    picking.vtp_state = 'canceled'
                # Mã 102: Đơn hàng chờ xử lý
                elif vtp_status == 102:
                    picking.vtp_state = 'waiting_webhook'
                # Mã 103: Giao cho bưu cục
                elif vtp_status == 103:
                    picking.vtp_state = 'created'
                # Mã 104: Giao cho Bưu tá đi nhận
                elif vtp_status == 104:
                    picking.vtp_state = 'created'
                # Mã 105: Bưu tá đã nhận hàng
                elif vtp_status == 105:
                    picking.vtp_state = 'created'
                # Mã 106: Đối tác yêu cầu lấy lại hàng
                elif vtp_status == 106:
                    picking.vtp_state = 'created'
                # Mã 107: Đối tác yêu cầu hủy qua API
                elif vtp_status == 107:
                    picking.vtp_state = 'draft'
                # Mã 200: Nhận từ bưu tá - Bưu cục gốc
                elif vtp_status == 200:
                    picking.vtp_state = 'created'
                # Mã 201: Hủy nhập phiếu gửi
                elif vtp_status == 201:
                    picking.vtp_state = 'canceled'
                # Mã 202: Sửa phiếu gửi
                elif vtp_status == 202:
                    picking.vtp_state = 'created'
                # Mã 300: Khai thác đi
                elif vtp_status == 300:
                    picking.vtp_state = 'created'
                # Mã 400: Khai thác đến
                elif vtp_status == 400:
                    picking.vtp_state = 'created'
                # Mã 500: Giao bưu tá đi phát
                elif vtp_status == 500:
                    picking.vtp_state = 'created'
                # Mã 501: Phát thành công
                elif vtp_status == 501:
                    picking.vtp_state = 'done'
                # Mã 502: Chuyển hoàn bưu cục gốc
                elif vtp_status == 502:
                    picking.vtp_state = 'created'
                # Mã 503: Hủy - Theo yêu cầu khách hàng
                elif vtp_status == 503:
                    picking.vtp_state = 'canceled'
                # Mã 504: Thành công - Chuyển trả cho người gửi
                elif vtp_status == 504:
                    picking.vtp_state = 'done'
                # Mã 505: Tồn - Thông báo chuyển hoàn bưu cục gốc
                elif vtp_status == 505:
                    picking.vtp_state = 'created'
                # Mã 506: Tồn - Khách hàng nghỉ, không có nhà
                elif vtp_status == 506:
                    picking.vtp_state = 'created'
                # Mã 507: Tồn - Khách hàng đến bưu cục nhận
                elif vtp_status == 507:
                    picking.vtp_state = 'created'
                # Mã 508: Phát tiếp
                elif vtp_status == 508:
                    picking.vtp_state = 'created'
                # Mã 509: Chuyển tiếp bưu cục khác
                elif vtp_status == 509:
                    picking.vtp_state = 'created'
                # Mã 515: Duyệt hoàn
                elif vtp_status == 515:
                    picking.vtp_state = 'created'
                # Mã 550: Phát tiếp
                elif vtp_status == 550:
                    picking.vtp_state = 'created'

        # Tạo lịch sử bill
        self.env['vtp.order.bill.history'].create_bill_history_from_webhook(bill.id, data)
        return bill
    
class VtpOrderBillHistory(models.Model):
    _name = 'vtp.order.bill.history'
    _description = 'ViettelPost Order Bill History'
    bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn')
    name = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True)
    order_id = fields.Many2one('stock.picking', string='Phiếu giao hàng')
    
    order_number = fields.Char("Mã đơn hàng VTP")
    order_reference = fields.Char("Mã đơn hàng")
    order_status_date = fields.Datetime(string='Ngày thay đổi')
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
    is_returning = fields.Boolean("Trả hàng")

    @api.model
    def create_bill_history_from_webhook(self, bill_id, data):

        order_number = data.get('ORDER_NUMBER')
        order_reference = data.get('ORDER_REFERENCE')

        bill = self.env['vtp.order.bill'].browse(bill_id)

        history_data = {
            'bill_id': bill.id,
            'name': order_number,
            'order_id': bill.order_id.id if bill.order_id else False,
            'order_number': order_number,
            'order_reference': order_reference,
            'order_status_date': datetime.strptime(data.get('ORDER_STATUSDATE'), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') if data.get('ORDER_STATUSDATE') else False,
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
            'expected_delivery_date': datetime.strptime(data.get('EXPECTED_DELIVERY_DATE'), '%d/%m/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S') if data.get('EXPECTED_DELIVERY_DATE') else False,
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
    vtp_state = fields.Selection([
        ('draft', 'Nháp'),
        ('waiting_webhook', 'Đang chờ xử lý'),
        ('created', 'Đã tạo'),
        ('done', 'Đã hoàn thành'),
        ('canceled', 'Đã hủy'),
    ], string='Trạng thái', default='draft')
    vtp_order_number = fields.Char(string='Mã vận đơn ViettelPost', copy=False, readonly=True)
    vtp_status_name = fields.Char(string='Trạng thái vận đơn', copy=False, readonly=True)

class VtpSaleOrder(models.Model):
    _inherit = 'sale.order'
    
    vtp_id = fields.Many2one('vtp.order.bill', string='Vận đơn VTP')
    vtp_store_id = fields.Many2one('vtp.store', string='Store ViettelPost')
