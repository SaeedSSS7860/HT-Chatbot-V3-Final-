import requests
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file (if you have one)
load_dotenv()  # Load .env vars BEFORE importing ticketing_utils

JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")
JIRA_API_USER_EMAIL = os.getenv("JIRA_API_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
# --- YOU NEED TO PROVIDE AN ACTUAL ISSUE KEY FROM YOUR JIRA PROJECT ---
# --- This issue should be in a state where it CAN be closed/resolved ---
EXISTING_ISSUE_KEY = "ITSSS-2" # <--- REPLACE THIS WITH A REAL ISSUE KEY (e.g., from your JSM project)

if not all([JIRA_DOMAIN, JIRA_API_USER_EMAIL, JIRA_API_TOKEN]):
    print("Error: JIRA_DOMAIN, JIRA_API_USER_EMAIL, or JIRA_API_TOKEN environment variables are not set.")
    print("Please set them in your environment or a .env file.")
    exit()

if EXISTING_ISSUE_KEY == "ITSM-123": # Reminder to change it
    print(f"Error: Please replace 'EXISTING_ISSUE_KEY = \"ITSSS-2\"' with an actual issue key from your project.")
    exit()


url = f"https://{JIRA_DOMAIN}/rest/api/2/issue/{EXISTING_ISSUE_KEY}/transitions"
auth = (JIRA_API_USER_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json"}

print(f"Fetching transitions for issue: {EXISTING_ISSUE_KEY} from {url}")

try:
    response = requests.get(url, headers=headers, auth=auth, timeout=10)
    response.raise_for_status()  # Raise an exception for HTTP errors

    transitions_data = response.json()
    print("\nAvailable Transitions:")
    print("-----------------------")
    if "transitions" in transitions_data and transitions_data["transitions"]:
        for transition in transitions_data["transitions"]:
            print(f"  ID: {transition['id']}, Name: \"{transition['name']}\" --> Leads to Status: \"{transition['to']['name']}\" (Status ID: {transition['to']['id']})")
        print("\nLook for the transition that moves the issue to your 'Closed', 'Resolved', or 'Done' status.")
        print("The 'ID' of that transition is what you need for JIRA_TRANSITION_ID_CLOSE.")
    else:
        print("No transitions found or an unexpected response structure.")
        print("Response:", json.dumps(transitions_data, indent=2))

except requests.exceptions.HTTPError as http_err:
    print(f"\nHTTP error occurred: {http_err}")
    print(f"Status Code: {response.status_code}")
    print(f"Response Text: {response.text}")
except requests.exceptions.RequestException as req_err:
    print(f"\nRequest error occurred: {req_err}")
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")