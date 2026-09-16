"""
NASQuay's own classification of QNAP's MCP tools.

QNAP's annotations cannot be used: on MCP Assistant 1.0.0.2356 every tool, reads
included, reports `readOnlyHint=false, destructiveHint=true`. So each tool is classified
here, by reading what it does.

A tool that is not in this table is discovered as `destructive` and `reviewed = 0`, which
means it is offered to nobody — not even an admin — until someone classifies it. A
firmware update must not quietly hand out a new power.
"""
from __future__ import annotations

from app.actions.registry import DESTRUCTIVE, READ, WRITE

ACTION_PREFIX = "qnap."

# Seen on QTS 5.2.x with MCP Assistant 1.0.0.2356: 42 tools.
KNOWN: dict[str, tuple[str, str, str]] = {
    # tool name: (category, classification, description)
    "list_storages":                        ("storage", READ, "List storage pools, volumes and disks"),
    "list_disks":                           ("storage", READ, "List the disks fitted to the NAS"),
    "get_pool_usage_history":               ("storage", READ, "Capacity history for a storage pool"),
    "get_qts_volume_usage_history":         ("storage", READ, "Capacity history for a volume"),

    "list_shared_folder":                   ("shares", READ, "List shared folders"),
    "get_shared_folder":                    ("shares", READ, "One shared folder's settings"),
    "get_shared_folder_permission_acl":     ("shares", READ, "A shared folder's access list"),
    "get_shared_folder_permission_details": ("shares", READ, "A shared folder's permissions in detail"),
    "get_subfolder_permission_acl":         ("shares", READ, "A subfolder's access list"),
    "verify_shared_folder_permission":      ("shares", READ, "Check a shared folder's permissions"),
    "verify_subfolder_permission_acl":      ("shares", READ, "Check a subfolder's access list"),

    "list_files":                           ("files", READ,  "List files and folders in a directory"),
    "search_files":                         ("files", READ,  "Search for files by name, type, owner or size"),
    "list_file_tasks":                      ("files", READ,  "Progress of file operations running on the NAS"),
    "generate_share_link":                  ("files", WRITE, "Create a share link for a file"),

    "list_users":                           ("nas-users", READ, "List NAS user accounts"),
    "get_user":                             ("nas-users", READ, "One NAS user account"),
    "list_groups":                          ("nas-users", READ, "List NAS groups"),
    "get_group":                            ("nas-users", READ, "One NAS group"),
    "list_online_users":                    ("nas-users", READ, "Who is connected to the NAS now"),
    "list_delegated_users":                 ("nas-users", READ, "Users with delegated administration"),
    "list_all_delegated_principals":        ("nas-users", READ, "Everyone holding delegated roles"),
    "verify_delegated_user_roles":          ("nas-users", READ, "Check a user's delegated roles"),

    "list_event_logs":                      ("logs", READ, "The NAS event log"),
    "list_access_logs":                     ("logs", READ, "The NAS connection log"),
    "get_log_config":                       ("logs", READ, "How the NAS is keeping its logs"),
    "get_qvr_logs":                         ("logs", READ, "Surveillance station logs"),

    "get_securitycenter_report":            ("security", READ,  "The security centre's report"),
    "get_security_policy_detail":           ("security", READ,  "The NAS security policy"),
    "securitycheckup_scan_report":          ("security", READ,  "The last security check-up result"),
    "antivirus_scan_report":                ("security", READ,  "The last antivirus scan result"),
    "malware_scan_report":                  ("security", READ,  "The last malware scan result"),
    "securitycheckup_scan":                 ("security", WRITE, "Run a security check-up on the NAS"),
    "malware_scan":                         ("security", WRITE, "Run a malware scan on the NAS"),
    "set_security_policy":                  ("security", WRITE, "Change the NAS security policy"),

    "get_system_info":                      ("system", READ,  "The NAS's model, firmware and state"),
    "get_system_server_name":               ("system", READ,  "The NAS's server name"),
    "query_load_avg":                       ("system", READ,  "The NAS's load average"),
    "query_top_processes":                  ("system", READ,  "The busiest processes on the NAS"),
    "list_power_schedule":                  ("system", READ,  "The NAS's power schedule"),
    "check_firmware_update":                ("system", READ,  "Whether a firmware update is offered"),
    "appcenter_list_apps":                  ("apps",   READ,  "Apps installed on the NAS"),
}


def action_id(tool_name: str) -> str:
    return f"{ACTION_PREFIX}{tool_name}"


def classify(tool_name: str, description: str = "") -> tuple[str, str, str, bool]:
    """(category, classification, description, reviewed) for a discovered tool.

    An unknown tool is the cautious case: destructive, and unreviewed so that nobody is
    offered it until a person has looked at it.
    """
    known = KNOWN.get(tool_name)
    if known:
        category, classification, text = known
        return category, classification, text, True
    return "unreviewed", DESTRUCTIVE, (description or "").strip()[:500], False
