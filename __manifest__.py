{
    'name': 'ViettelPost Integration',
    'version': '1.1',
    'category': 'Inventory/Delivery',
    'summary': 'Tích hợp API ViettelPost để tạo vận đơn',
    'description': """
        Module tích hợp API ViettelPost cho Odoo 18
        ==========================================
        
        Chức năng:
        - Cấu hình tài khoản ViettelPost (client_id, client_secret, username, password)
        - Lấy và lưu token truy cập từ API ViettelPost
        - Quản lý Store: cho phép tạo mới Store hoặc chọn Store có sẵn
        - Tra cước vận chuyển dựa trên thông tin đơn hàng
        - Tạo bill vận chuyển và lưu lại mã vận đơn vào phiếu xuất kho
        - Cập nhật trạng thái bill vận chuyển từ API về Odoo
        - Có cron job/webhook để đồng bộ trạng thái vận đơn tự động
    """,
    'author': 'NTAN',    
    'depends': [
        'base',
        'stock',
        'delivery',
    ],
    'data': [
        # 'data/ir_cron_data.xml',
        'views/vtp_store_views.xml',
        'views/vtp_account_views.xml',
        'views/vtp_place_views.xml',
        'views/vtp_order_bill_views.xml',
        'wizards/vtp_create_bill_views.xml',
        'wizards/vtp_update_bill_status_wizard.xml',
        'wizards/vtp_update_bill_wizard.xml',
        'views/vtp_service_bill_views.xml',
        'wizards/vtp_print_bill_wizard.xml',
        'views/stock_picking_views.xml',
        
        'views/sale_order_views.xml',
        'security/ir.model.access.csv',
        'security/groups.xml',

    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}