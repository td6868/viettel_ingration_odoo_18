from odoo import api, fields, models, _
from odoo.exceptions import UserError
import json
import logging

_logger = logging.getLogger(__name__)

class VTPUpdateBillWizard(models.TransientModel):
    _name = 'vtp.update.bill.status.wizard'
    _description = 'Chỉnh sửa vận đơn ViettelPost'

    picking_id = fields.Many2one('stock.picking', string='Phiếu giao hàng', required=True)
    order_number = fields.Char(string='Mã vận đơn ViettelPost', required=True)
    vtp_state = fields.Selection([
        ('draft', 'Nháp'),
        ('waiting_webhook', 'Đang chờ xử lý'),
        ('created', 'Đã tạo'),
        ('done', 'Đã hoàn thành'),
        ('canceled', 'Đã hủy'),
    ], string='Trạng thái', readonly=True)
    type = fields.Selection([
        ('1', 'Xác nhận đơn hàng'),
        ('2', 'Xác nhận trả hàng'),
        ('3', 'Giao hàng lại'),
        ('4', 'Hủy đơn hàng'),
        ('5', 'Nhận lại đơn hàng (đặt hàng lại)'),
        ('11', 'Xóa đơn hàng đã hủy')
    ], string='Loại', required=True)
    note = fields.Text(string='Ghi chú')

    @api.model
    def default_get(self, fields_list):
        """Lấy thông tin mặc định từ phiếu giao hàng"""
        res = super().default_get(fields_list)
        if self._context.get('active_model') == 'stock.picking' and self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))

            
            # Lấy mã vận đơn từ vtp.order.bill
            order_bill = self.env['vtp.order.bill'].search([('order_id', '=', picking.id)], limit=1)
            if order_bill and order_bill.order_number:
                res.update({
                    'picking_id': picking.id,
                    'order_number': order_bill.order_number,
                    'vtp_state': picking.vtp_state,
                })
            else:
                raise UserError(_('Không tìm thấy mã vận đơn ViettelPost!'))
        return res

    def action_update_bill_status(self):
        """Cập nhật trạng thái vận đơn"""
        self.ensure_one()
        
        if not self.order_number:
            raise UserError(_('Vui lòng nhập mã vận đơn!'))

        VTPService = self.env['vtp.service']
        data = {
            "TYPE": int(self.type),
            "ORDER_NUMBER": self.order_number,
            "NOTE": self.note or "Cập nhật trạng thái"
        }
        _logger.info("Dữ liệu gửi lên API cập nhật trạng thái: %s", data)
        result = VTPService.update_bill_status(data)
        _logger.info("Kết quả gọi UpdateOrder: %s", result)
        self.picking_id.update({
            'vtp_state': 'waiting_webhook',
        })
        # Không cập nhật vtp_state tại đây. Trạng thái sẽ do webhook cập nhật.
        message = 'Đã gửi yêu cầu cập nhật trạng thái vận đơn! Trạng thái sẽ cập nhật khi webhook trả về.'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã gửi yêu cầu'),
                'message': _(message),
                'sticky': False,
                'type': 'info',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }