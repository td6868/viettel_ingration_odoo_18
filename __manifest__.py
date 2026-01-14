{
    'name': 'ViettelPost Integration',
    'version': '2.0',
    'category': 'Inventory/Delivery',
    'summary': 'Tích hợp API ViettelPost để tạo vận đơn - Multi-account support',
    'description': """
        Module tích hợp API ViettelPost cho Odoo 18
        ==========================================
        
        Phiên bản 2.0 - Major Refactor:
        - Hỗ trợ đa tài khoản (Multi-account)
        - Token riêng biệt cho từng tài khoản
        - Mã hóa password
        - Retry logic với exponential backoff
        - Audit trail cho mọi API call
        - PostgreSQL advisory locks cho token refresh
        - Pure stateless service layer
        
        Chức năng:
        - Cấu hình nhiều tài khoản ViettelPost
        - Lấy và lưu token truy cập riêng cho từng tài khoản
        - Quản lý Store: cho phép tạo mới Store hoặc chọn Store có sẵn
        - Tra cước vận chuyển dựa trên thông tin đơn hàng
        - Tạo bill vận chuyển và lưu lại mã vận đơn vào phiếu xuất kho
        - Cập nhật trạng thái bill vận chuyển từ API về Odoo
        - Có cron job/webhook để đồng bộ trạng thái vận đơn tự động
        - API Audit Log để theo dõi mọi API calls
    """,
    'author': 'NTAN',    
    'depends': [
        'base',
        'stock',
        'delivery',
        'mail',
    ],
    'data': [
        # 'data/ir_cron_data.xml',
        'security/groups.xml',
        'security/ir.model.access.csv',

        'wizards/vtp_create_bill_views.xml',
        'wizards/vtp_update_bill_status_wizard.xml',
        'wizards/vtp_update_bill_wizard.xml',
        'wizards/vtp_print_bill_wizard.xml',

        'views/vtp_store_views.xml',
        'views/vtp_account_views.xml',
        'views/vtp_api_audit_views.xml',
        'views/vtp_place_views.xml',
        'views/vtp_order_bill_views.xml',       
        'views/vtp_service_bill_views.xml',
        'views/sale_order_views.xml',
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}