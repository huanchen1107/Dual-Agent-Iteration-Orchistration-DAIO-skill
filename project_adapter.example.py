"""Example DAIO project adapter.

Copy into a project and enable via .daio/project_adapter.json:
{"enabled": true, "path": "daio_adapter.py"}
"""
def collect_sections(project_root):
    return {
        "summary": {
            "title": "Project-specific status",
            "items": ["Replace this example with domain-specific read-only dashboard data."]
        }
    }
