from enum import Enum


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    AUDITOR = "auditor"
    CFO = "cfo"
    VIEWER = "viewer"


ROLE_PERMISSIONS = {
    UserRole.OWNER: ["*"],
    UserRole.ADMIN: ["manage_users", "manage_settings", "view_financials", "approve_actions"],
    UserRole.ACCOUNTANT: ["create_entries", "upload_documents", "view_financials"],
    UserRole.AUDITOR: ["view_audit_logs", "review_documents", "view_financials"],
    UserRole.CFO: ["view_financials", "approve_actions", "view_reports"],
    UserRole.VIEWER: ["view_dashboard"],
}


def role_has_permission(role: str, permission: str) -> bool:
    try:
        role_enum = UserRole(role)
    except ValueError:
        return False

    permissions = ROLE_PERMISSIONS.get(role_enum, [])
    return "*" in permissions or permission in permissions
