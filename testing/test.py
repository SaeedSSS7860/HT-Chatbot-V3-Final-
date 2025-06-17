import requests
from requests.auth import HTTPBasicAuth
import os
# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

def get_service_desks():
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/servicedeskapi/servicedesk"
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))

    if response.status_code == 200:
        return response.json()["values"]
    else:
        raise Exception(f"Failed to fetch service desks: {response.text}")


def get_request_types(service_desk_id):
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/servicedeskapi/servicedesk/{service_desk_id}/requesttype"
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))
    
    if response.status_code == 200:
        return response.json()["values"]
    else:
        raise Exception(f"Failed to fetch request types: {response.text}")
    

def create_ticket(service_desk_id, request_type_id, summary, description):
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/servicedeskapi/request"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "serviceDeskId": str(service_desk_id),
        "requestTypeId": str(request_type_id),
        "requestFieldValues": {
            "summary": summary,
            "description": description
        }
}

    response = requests.post(url, json=payload, headers=headers,
                             auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))

    if response.status_code == 201:
        issue_key = response.json()["issueKey"]
        return {"success": True, "issue_key": issue_key}
    else:
        return {"success": False, "error": response.text}

def get_transitions(issue_key):
    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/api/3/issue/{issue_key}/transitions"
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))

    if response.status_code == 200:
        return response.json()["transitions"]
    else:
        return []


def transition_to_in_progress(issue_key):
    transitions = get_transitions(issue_key)
    
    # Find transition id for "In Progress" (case-insensitive)
    in_progress_transition = next((t for t in transitions if t["name"].lower() == "start work"), None)
    
    if not in_progress_transition:
        return {"success": False, "error": "No 'In Progress' transition found", "available_transitions": [t["name"] for t in transitions]}

    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/api/3/issue/{issue_key}/transitions"
    payload = {"transition": {"id": in_progress_transition["id"]}}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))

    if response.status_code == 204:
        return {"success": True, "message": f"Issue {issue_key} transitioned to 'In Progress'."}
    else:
        return {"success": False, "error": response.text}



def close_ticket(issue_key):
    transitions = get_transitions(issue_key)
    
    close_transition = next((t for t in transitions if t["name"].lower() in ["done", "closed", "resolve"]), None)
    
    if not close_transition:
        return {"success": False, "error": "No close transition found"}

    url = f"https://{os.getenv('JIRA_DOMAIN')}/rest/api/3/issue/{issue_key}/transitions"
    payload = {"transition": {"id": close_transition["id"]}}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers, auth=HTTPBasicAuth(os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN")))

    if response.status_code == 204:
        return {"success": True, "message": f"Issue {issue_key} closed."}
    else:
        return {"success": False, "error": response.text}

if __name__ == "__main__":
    summary = "VPN Not Working"
    description = "User reports that the VPN connection fails after login."
    
    service_desk_id = 2  # For IT-SSS
    request_type_id = 10046  # IT-Support (from earlier curl)

    # Step 1: Create ticket
    result = create_ticket(service_desk_id, request_type_id, summary, description)
    print("Ticket Created:", result)

    if result["success"]:
        issue_key = result["issue_key"]
     #   issue_key = "ITSSS-13"
        # Step 2: Transition to In Progress
        transition_result = transition_to_in_progress(issue_key)
        print("Transition to In Progress Result:", transition_result)

        # Step 3: Close the ticket
        close_result = close_ticket(issue_key)
        print("Close Result:", close_result)
#issue_key= "ITSSS-13"  # Replace with your issue key
#close_result = close_ticket(issue_key)
#print("Close Result:", close_result)
#####################################################################
""" 
def create_jira_ticket(summary, description):
    jira_domain = os.getenv("JIRA_DOMAIN")  # e.g. saidshaikhnagar.atlassian.net
    jira_email = os.getenv("JIRA_EMAIL")    # your email
    jira_token = os.getenv("JIRA_TOKEN")    # your API token

    url = f"https://{jira_domain}/rest/servicedeskapi/request"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "serviceDeskId": "2",  # IT-SSS project service desk id
        "requestTypeId": "10046",  # IT-Support request type id
        "requestFieldValues": {
            "summary": summary,
            "description": description
        }
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        auth=HTTPBasicAuth(jira_email, jira_token)
    )

    if response.status_code == 201:
        return {"success": True, "data": response.json()}
    else:
        return {
            "success": False,
            "status_code": response.status_code,
            "error": response.text
        }

# Example usage:
if __name__ == "__main__":
    result = create_jira_ticket(
        "Ticket Creation Test by python code",
        "I tried pressing the power button several times but nothing happens."
    )
    print(result)

    """