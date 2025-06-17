# ticketing_utils.py
import requests
from requests.auth import HTTPBasicAuth
import os
import json
from dotenv import load_dotenv

load_dotenv() 

try:
    from chatbot_utils import logger 
except ImportError: 
    import logging
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
        logger.setLevel(logging.INFO)
        logger.warning("ticketing_utils.py: Using fallback logger.")

# --- JIRA API CONFIG (Load from environment variables) ---
JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
JIRA_API_USER_EMAIL = os.getenv("JIRA_API_USER_EMAIL") 
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_SERVICE_DESK_ID = os.getenv("JIRA_SERVICE_DESK_ID")
JIRA_REQUEST_TYPE_ID_STR = os.getenv("JIRA_REQUEST_TYPE_ID")
JIRA_TRANSITION_ID_IN_PROGRESS = os.getenv("JIRA_TRANSITION_ID_IN_PROGRESS")
JIRA_TRANSITION_ID_CLOSE = os.getenv("JIRA_TRANSITION_ID_CLOSE")

# Assignee Account IDs
JIRA_L1_ASSIGNEE_ACCOUNT_ID = os.getenv("JIRA_L1_ASSIGNEE_ACCOUNT_ID")
JIRA_L2_ASSIGNEE_ACCOUNT_ID = os.getenv("JIRA_L2_ASSIGNEE_ACCOUNT_ID")


JIRA_REQUEST_TYPE_ID = None
if JIRA_REQUEST_TYPE_ID_STR:
    try:
        JIRA_REQUEST_TYPE_ID = str(JIRA_REQUEST_TYPE_ID_STR)
    except ValueError:
        logger.error(f"Error with JIRA_REQUEST_TYPE_ID: '{JIRA_REQUEST_TYPE_ID_STR}'.")

def _get_jira_auth_and_headers():
    # ... (same as before) ...
    if not all([JIRA_DOMAIN, JIRA_API_USER_EMAIL, JIRA_API_TOKEN]):
        logger.error("Jira API configuration (domain, user email, or token) is missing.")
        return None, None
    auth = HTTPBasicAuth(JIRA_API_USER_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    return auth, headers

def _convert_description_to_adf(description_text: str):
    # ... (same as before) ...
    adf_content = []
    if description_text:
        for line in description_text.split('\n'):
            stripped_line = line.strip()
            adf_content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": stripped_line if stripped_line else " "}] 
            })
    if not adf_content: 
         adf_content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": "(No detailed description provided)"}]
        })
    return {"version": 1, "type": "doc", "content": adf_content}


def create_jira_ticket(summary: str, description_text: str, reporter_email: str = None) -> dict:
    # ... (same as before, ensure it uses JIRA_SERVICE_DESK_ID and JIRA_REQUEST_TYPE_ID) ...
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return {"success": False, "error": "Jira API configuration missing."}
    if not JIRA_SERVICE_DESK_ID or not JIRA_REQUEST_TYPE_ID:
        logger.error("Jira Service Desk ID or Request Type ID is not configured or invalid.")
        return {"success": False, "error": "Jira Service Desk/Request Type configuration missing or invalid."}

    url = f"https://{JIRA_DOMAIN}/rest/servicedeskapi/request"
    # Use plain text for description with this JSM endpoint
    # adf_description = _convert_description_to_adf(description_text) 

    payload = {
        "serviceDeskId": str(JIRA_SERVICE_DESK_ID), 
        "requestTypeId": str(JIRA_REQUEST_TYPE_ID),
        "requestFieldValues": {
            "summary": summary,
            "description": description_text, # Plain text for JSM /request endpoint's description
        }
    }
    if reporter_email:
        payload["raiseOnBehalfOf"] = reporter_email
    
    logger.info(f"Creating Jira ticket. URL: {url}\nPayload: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(url, auth=auth, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        ticket_data = response.json()
        ticket_key = ticket_data.get("issueKey")
        logger.info(f"Jira ticket created successfully: Key {ticket_key}")
        return {"success": True, "ticket_key": ticket_key, "issue_id": ticket_data.get("issueId"), "data": ticket_data}
    except requests.exceptions.HTTPError as http_err:
        error_text = response.text
        logger.error(f"HTTP error creating Jira ticket: {http_err} (Status: {response.status_code})\nResponse: {error_text}")
        try: error_details = response.json()
        except json.JSONDecodeError: error_details = {"raw_response": error_text}
        return {"success": False, "error": f"JIRA API HTTP Error: {response.status_code}", "details": error_details}
    except Exception as e:
        logger.error(f"Unexpected error creating Jira ticket: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


def get_available_transitions(issue_key_or_id: str) -> list:
    # ... (same as before) ...
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return []
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key_or_id}/transitions"
    logger.debug(f"Getting transitions for Jira ticket {issue_key_or_id}. URL: {url}")
    try:
        response = requests.get(url, headers=headers, auth=auth, timeout=10)
        response.raise_for_status()
        return response.json().get("transitions", [])
    except Exception as e:
        logger.error(f"Error getting transitions for {issue_key_or_id}: {e}", exc_info=True)
        return []

def find_transition_id_by_name(issue_key_or_id: str, target_transition_names: list[str]) -> str | None:
    # ... (same as before) ...
    transitions = get_available_transitions(issue_key_or_id)
    target_names_lower = [name.lower() for name in target_transition_names]
    for t in transitions:
        if t.get("name", "").lower() in target_names_lower:
            logger.info(f"Found transition for {issue_key_or_id}: ID '{t.get('id')}' Name '{t.get('name')}' (matched one of {target_transition_names})")
            return t.get("id")
    logger.warning(f"No transition matching '{target_transition_names}' found for issue {issue_key_or_id}. Available: {[tr.get('name') for tr in transitions]}")
    return None


def transition_jira_ticket(issue_key_or_id: str, transition_id: str) -> dict:
    # ... (same as before, ensure transition_id is string) ...
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return {"success": False, "error": "Jira API configuration missing."}
    if not transition_id:
        logger.error(f"Jira transition ID not provided for ticket {issue_key_or_id}.")
        return {"success": False, "error": "Jira transition ID missing."}

    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key_or_id}/transitions"
    payload = {"transition": {"id": str(transition_id)}}

    logger.info(f"Transitioning Jira ticket {issue_key_or_id} with transition ID {transition_id}.\nPayload: {json.dumps(payload)}")
    try:
        response = requests.post(url, auth=auth, headers=headers, json=payload, timeout=10)
        if response.status_code == 204: 
            logger.info(f"Jira ticket {issue_key_or_id} transitioned successfully using ID {transition_id}.")
            return {"success": True}
        else:
            response.raise_for_status() 
            logger.warning(f"Jira ticket {issue_key_or_id} transition returned status {response.status_code}, but no HTTPError. Response: {response.text}")
            return {"success": True, "message": f"Transition status: {response.status_code}"}
    except requests.exceptions.HTTPError as http_err:
        error_text = response.text
        logger.error(f"HTTP error transitioning Jira ticket: {http_err} (Status: {response.status_code})\nResponse: {error_text}")
        try: error_details = response.json()
        except json.JSONDecodeError: error_details = {"raw_response": error_text}
        return {"success": False, "error": f"JIRA API HTTP Error: {response.status_code}", "details": error_details}
    except Exception as e:
        logger.error(f"Unexpected error transitioning Jira ticket: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected error: {str(e)}"}

def add_jira_comment(issue_key_or_id: str, comment_body: str, is_public: bool = True) -> dict:
    # ... (same as before) ...
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return {"success": False, "error": "Jira API configuration missing."}

    url = f"https://{JIRA_DOMAIN}/rest/servicedeskapi/request/{issue_key_or_id}/comment"
    payload = {"body": comment_body, "public": is_public} 

    logger.info(f"Adding Jira comment to {issue_key_or_id}. URL: {url}\nPublic: {is_public}\nPayload: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(url, auth=auth, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Comment added to Jira ticket {issue_key_or_id}.")
        return {"success": True, "data": response.json()}
    except requests.exceptions.HTTPError as http_err:
        error_text = response.text
        logger.error(f"HTTP error adding Jira comment: {http_err} (Status: {response.status_code})\nResponse: {error_text}")
        try: error_details = response.json()
        except json.JSONDecodeError: error_details = {"raw_response": error_text}
        return {"success": False, "error": f"JIRA API HTTP Error: {response.status_code}", "details": error_details}
    except Exception as e:
        logger.error(f"Unexpected error adding Jira comment: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected error: {str(e)}"}

# --- NEW FUNCTIONS FOR ASSIGNMENT AND PRIORITY ---
def assign_jira_issue(issue_key_or_id: str, account_id: str) -> dict:
    """Assigns a Jira issue to a user using their accountId."""
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return {"success": False, "error": "Jira API configuration missing."}
    if not account_id:
        logger.warning(f"No account_id provided for assigning issue {issue_key_or_id}.")
        return {"success": False, "error": "No account_id provided."}

    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key_or_id}/assignee"
    payload = {"accountId": account_id}

    logger.info(f"Assigning Jira issue {issue_key_or_id} to accountId {account_id}. URL: {url}\nPayload: {json.dumps(payload)}")
    try:
        response = requests.put(url, auth=auth, headers=headers, json=payload, timeout=10)
        if response.status_code == 204:
            logger.info(f"Issue {issue_key_or_id} assigned to accountId {account_id} successfully.")
            return {"success": True}
        else:
            response.raise_for_status()
            logger.warning(f"Assigning issue {issue_key_or_id} returned {response.status_code} but no error. Response: {response.text}")
            return {"success": True, "message": f"Assignment status: {response.status_code}"}
    except requests.exceptions.HTTPError as http_err:
        error_text = response.text
        logger.error(f"HTTP error assigning Jira issue: {http_err} (Status: {response.status_code})\nResponse: {error_text}")
        try: error_details = response.json()
        except json.JSONDecodeError: error_details = {"raw_response": error_text}
        return {"success": False, "error": f"JIRA API HTTP Error: {response.status_code}", "details": error_details}
    except Exception as e:
        logger.error(f"Unexpected error assigning Jira issue: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


def set_jira_issue_priority(issue_key_or_id: str, priority_id: str) -> dict:
    """Sets the priority of a Jira issue using priority ID."""
    auth, headers = _get_jira_auth_and_headers()
    if not auth: return {"success": False, "error": "Jira API configuration missing."}
    if not priority_id:
        logger.warning(f"No priority_id provided for setting priority of issue {issue_key_or_id}.")
        return {"success": False, "error": "No priority_id provided."}
        
    url = f"https://{JIRA_DOMAIN}/rest/api/3/issue/{issue_key_or_id}"
    payload = {"fields": {"priority": {"id": str(priority_id)}}} # Priority ID should be a string

    logger.info(f"Setting priority for Jira issue {issue_key_or_id} to ID {priority_id}. URL: {url}\nPayload: {json.dumps(payload)}")
    try:
        response = requests.put(url, auth=auth, headers=headers, json=payload, timeout=10)
        if response.status_code == 204:
            logger.info(f"Issue {issue_key_or_id} priority set to ID {priority_id} successfully.")
            return {"success": True}
        else:
            response.raise_for_status()
            logger.warning(f"Setting priority for {issue_key_or_id} returned {response.status_code} but no error. Response: {response.text}")
            return {"success": True, "message": f"Set priority status: {response.status_code}"}
    except requests.exceptions.HTTPError as http_err:
        error_text = response.text
        logger.error(f"HTTP error setting Jira issue priority: {http_err} (Status: {response.status_code})\nResponse: {error_text}")
        try: error_details = response.json()
        except json.JSONDecodeError: error_details = {"raw_response": error_text}
        return {"success": False, "error": f"JIRA API HTTP Error: {response.status_code}", "details": error_details}
    except Exception as e:
        logger.error(f"Unexpected error setting Jira issue priority: {e}", exc_info=True)
        return {"success": False, "error": f"Unexpected error: {str(e)}"}