import os
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

def assign_issue(issue_key, account_id):
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/api/3/issue/{issue_key}/assignee"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = { "accountId": account_id }

    response = requests.put(
        url,
        json=payload,
        headers=headers,
        auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    )

    if response.status_code == 204:
        return {"success": True, "message": f"Issue {issue_key} assigned to accountId {account_id}"}
    else:
        return {"success": False, "error": response.text}

def set_issue_priority(issue_key, priority_id=2):  # Example: High
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/api/3/issue/{issue_key}"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": {
            "priority": {"id": str(priority_id)}
        }
    }

    response = requests.put(
        url,
        json=payload,
        headers=headers,
        auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    )

    if response.status_code == 204:
        return {"success": True, "message": f"Issue {issue_key} priority set to ID {priority_id}"}
    else:
        return {"success": False, "error": response.text}

# Example usage
if __name__ == "__main__":
    issue_key = "ITSSS-8"  # Replace with your ticket key
    print(set_issue_priority(issue_key, priority_id=2))  # Set to High



# Example usage:
if __name__ == "__main__":
    issue_key = "ITSSS-8"  # Replace with the ticket you created
    account_id = "712020:2da9f289-1d0f-4a45-9ff1-f3aaf57bbad2"  # Replace with actual Jira user's accountId

    result = assign_issue(issue_key, account_id)
    print(set_issue_priority(issue_key, priority_id=3)) 
    print(result)