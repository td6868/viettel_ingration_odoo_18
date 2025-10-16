from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)

class VTPPrintBillWizard(models.TransientModel):
    _name = 'vtp.print.bill.wizard'
    _description = 'In vận đơn ViettelPost'

    
    type = fields.Selection([
        ('1', 'A5'),
        ('2', 'A6'),
        ('3', 'A7'),
    ], string='Khổ giấy', default='1')

    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True)
    order_bill_id = fields.Many2one('vtp.order.bill', string='Vận đơn ViettelPost', required=True)
    order_number = fields.Char(string='Số vận đơn', related='order_bill_id.order_number', readonly=True)
    token_expiry = fields.Char(string='Hết hạn token', related='order_bill_id.store_id.account_id.token_expiry', readonly=True)

    @api.onchange('picking_id')
    def _onchange_picking_id(self):
        """Khi chọn phiếu xuất kho, tự động lấy vận đơn liên quan để hiển thị số vận đơn."""
        if self.picking_id:
            bill = self.env['vtp.order.bill'].search([('order_id', '=', self.picking_id.id)], limit=1)
            self.order_bill_id = bill.id if bill else False           

    def _get_default_from_context(self):
        """Xác định bản ghi mặc định dựa theo context khi mở wizard.
        Hỗ trợ mở từ stock.picking hoặc từ vtp.order.bill.
        """
        ctx = self.env.context or {}
        active_model = ctx.get('active_model')
        active_id = ctx.get('active_id')

        picking = False
        bill = False

        if active_model == 'stock.picking' and active_id:
            picking = self.env['stock.picking'].browse(active_id)
            if picking:
                bill = self.env['vtp.order.bill'].search([('order_id', '=', picking.id)], limit=1)
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
            res['order_bill_id'] = bill.id
        # Nếu không xác định được bill, hiển thị thông báo rõ ràng để người dùng biết lý do
        if 'order_bill_id' not in res or not res.get('order_bill_id'):
            _logger.warning('Không tìm thấy vtp.order.bill tương ứng khi mở wizard in phiếu')
        return res

    def action_print_bill(self):
        self.ensure_one()
        # Kiểm tra dữ liệu bắt buộc
        if not self.order_bill_id:
            raise UserError(_('Không tìm thấy vận đơn ViettelPost cho phiếu này.'))
        if not self.order_bill_id.order_number:
            raise UserError(_('Vận đơn chưa có mã ORDER_NUMBER. Vui lòng tạo vận đơn trước khi in.'))

        data = {
            'EXPIRY_TIME': self.token_expiry,
            'ORDER_ARRAY': [self.order_bill_id.order_number],
        }

        _logger.info("Token expiry: %s", self.token_expiry) 
        _logger.info("Data: %s", data)

        VTPservice = self.env['vtp.service']
        code = VTPservice.link_print_bill(data)
        _logger.info("Code: %s", code)
        if not code:
            raise UserError(_('Không tìm thấy link in vận đơn!'))

        if self.type == '1':
            # môi trường dev:
            link = "https://dev-print.viettelpost.vn/DigitalizePrint/report.do?type=1&bill=" + code + "&showPostage=1"
            # môi trường production:
            # link = "https://digitalize.viettelpost.vn/DigitalizePrint/report.do?type=1&bill=" + code + "&showPostage=1"

        elif self.type == '2':
            # môi trường dev:
            link = "https://dev-print.viettelpost.vn/DigitalizePrint/report.do?type=2&bill=" + code + "&showPostage=1"
            # môi trường production:
            # link = "https://digitalize.viettelpost.vn/DigitalizePrint/report.do?type=2&bill=" + code + "&showPostage=1"
        elif self.type == '3':
            # môi trường dev:
            link = "https://dev-print.viettelpost.vn/DigitalizePrint/report.do?type=100&bill=" + code + "&showPostage=1"
            # môi trường production:
            # link = "https://digitalize.viettelpost.vn/DigitalizePrint/report.do?type=100&bill=" + code + "&showPostage=1"
        else:
            # fallback
            link = "https://dev-print.viettelpost.vn/DigitalizePrint/report.do?type=1&bill=" + code + "&showPostage=1"

        # Trả về action URL để Odoo mở tab in
        return {
            'type': 'ir.actions.act_url',
            'url': link,
            'target': 'new',
        }