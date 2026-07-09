from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    CFO = "cfo"
    FINANCE_MANAGER = "finance_manager"
    VIEWER = "viewer"


ROLE_PERMISSIONS = {
    UserRole.OWNER: ["*"],
    UserRole.ADMIN: [
        "manage_users",
        "manage_settings",
        "view_financials",
        "upload_documents",
        "create_entries",
        "review_entries",
        "approve_actions",
        "post_odoo_entries",
        "view_reports",
        "view_audit_logs",
    ],
    UserRole.ACCOUNTANT: [
        "create_entries",
        "upload_documents",
        "view_financials",
    ],
    UserRole.REVIEWER: [
        "view_financials",
        "review_entries",
        "view_reports",
    ],
    UserRole.AUDITOR: [
        "view_audit_logs",
        "review_documents",
        "view_financials",
        "view_reports",
    ],
    UserRole.CFO: [
        "view_financials",
        "approve_actions",
        "post_odoo_entries",
        "view_reports",
        "view_audit_logs",
    ],
    UserRole.FINANCE_MANAGER: [
        "view_financials",
        "approve_actions",
        "post_odoo_entries",
        "view_reports",
    ],
    UserRole.VIEWER: [
        "view_dashboard",
        "view_financials",
    ],
}


def role_has_permission(role: str, permission: str) -> bool:
    try:
        role_enum = UserRole(role)
    except ValueError:
        return False

    permissions = ROLE_PERMISSIONS.get(role_enum, [])
    return "*" in permissions or permission in permissions
