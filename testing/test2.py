import requests
from requests.auth import HTTPBasicAuth
import os

def get_transitions(issue_key):
    jira_domain = os.getenv("JIRA_DOMAIN")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_TOKEN")

    url = f"https://{jira_domain}/rest/api/3/issue/{issue_key}/transitions"

    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=HTTPBasicAuth(jira_email, jira_token))

    if response.status_code == 200:
        return response.json().get("transitions", [])
    else:
        print(f"Error fetching transitions: {response.status_code} {response.text}")
        return []

def close_ticket(issue_key):
    jira_domain = os.getenv("JIRA_DOMAIN")
    jira_email = os.getenv("JIRA_EMAIL")
    jira_token = os.getenv("JIRA_TOKEN")

    # Get available transitions for the issue
    transitions = get_transitions(issue_key)

    # Find the transition ID for "Done" or "Close" (names may vary)
    close_transition = None
    for t in transitions:
        if t["name"].lower() in ["done", "close", "closed", "resolve"]:
            close_transition = t
            break

    if not close_transition:
        return {"success": False, "error": "No suitable close transition found"}

    url = f"https://{jira_domain}/rest/api/3/issue/{issue_key}/transitions"

    payload = {
        "transition": {
            "id": close_transition["id"]
        }
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, auth=HTTPBasicAuth(jira_email, jira_token))

    if response.status_code == 204:
        return {"success": True, "message": f"Issue {issue_key} transitioned to {close_transition['name']}"}
    else:
        return {"success": False, "status_code": response.status_code, "error": response.text}

# Example usage:
if __name__ == "__main__":
    issue_key = "ITSSS-4"  # Replace with your issue key
    result = close_ticket(issue_key)
    print(result)

### We need to get the issue key realtime from the code.
