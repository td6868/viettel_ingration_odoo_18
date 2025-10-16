from odoo import models, fields, api

class VtpPricing(models.Model):
    _name = 'vtp.pricing'
    _description = 'ViettelPost Pricing'
    
    store_id = fields.Many2one('vtp.store', string='ID cửa hàng', required=True)
    service_code = fields.Many2one('vtp.service.bill', string='Mã dịch vụ')
    sale_id = fields.Many2one('sale.order', related='order_id.sale_id', store=True)
    order_id = fields.Many2one('vtp.order.bill', string='Phiếu giao hàng')
    
    name = fields.Char(string='Tên', required=True)
    money_total_old = fields.Integer(string='Tổng tiền trước khi áp dụng phí')
    money_total = fields.Integer(string='Tổng tiền sau khi áp dụng phí')
    money_total_fee = fields.Integer(string='Tổng phí vận chuyển')
    money_fee = fields.Integer(string='Phí vận chuyển')
    money_collection_fee = fields.Integer(string='Phí thu hộ')
    money_other_fee = fields.Integer(string='Phí khác')
    money_vas = fields.Integer(string='Phí VAS')
    money_vat = fields.Integer(string='Phí VAT')
    kpi_ht = fields.Integer(string='KPI HT')    
    vtp_response = fields.Text(string='JSON phản hồi VTP')
    
    
