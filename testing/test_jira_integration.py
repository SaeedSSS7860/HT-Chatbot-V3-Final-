# test_jira_integration.py
import os
from dotenv import load_dotenv
from ticketing_utils import create_jira_ticket, add_jira_comment, transition_jira_ticket
import uuid # To make summaries unique for testing

# Load environment variables from .env file
load_dotenv()

# --- Configuration for the test ---
# Ensure these are set in your .env file or environment
TEST_REPORTER_EMAIL = os.getenv("TEST_JIRA_REPORTER_EMAIL", "test_reporter@example.com") # Email for the ticket reporter
UNIQUE_ID = str(uuid.uuid4())[:8] # To make test ticket summary unique

def run_jira_test():
    print("--- Starting Jira Integration Test ---")

    # --- Check if essential config is present ---
    if not all([os.getenv("JIRA_DOMAIN"), os.getenv("JIRA_API_USER_EMAIL"), os.getenv("JIRA_API_TOKEN"),
                os.getenv("JIRA_PROJECT_KEY"), os.getenv("JIRA_REQUEST_TYPE_ID"), os.getenv("JIRA_TRANSITION_ID_CLOSE")]):
        print("Error: One or more required Jira environment variables are missing.")
        print("Please set: JIRA_DOMAIN, JIRA_API_USER_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY, JIRA_REQUEST_TYPE_ID, JIRA_TRANSITION_ID_CLOSE")
        return

    # --- 1. Test Ticket Creation ---
    print(f"\n1. Attempting to create a Jira ticket with unique ID: {UNIQUE_ID}...")
    summary = f"Test Ticket from Chatbot Script - {UNIQUE_ID}"
    description = f"This is a test ticket created automatically by the chatbot integration script.\nQuery: User had an issue with test query {UNIQUE_ID}."
    
    creation_result = create_jira_ticket(
        summary=summary,
        description_text=description,
        reporter_email=TEST_REPORTER_EMAIL
    )

    if creation_result.get("success"):
        ticket_key = creation_result.get("ticket_key")
        print(f"   SUCCESS! Ticket created: {ticket_key}")

        # --- 2. Test Adding a Comment ---
        print(f"\n2. Attempting to add a public comment to ticket {ticket_key}...")
        comment_result_public = add_jira_comment(
            issue_key=ticket_key,
            comment_body="This is a public test comment from the chatbot script.",
            is_public=True
        )
        if comment_result_public.get("success"):
            print(f"   SUCCESS! Public comment added to {ticket_key}.")
        else:
            print(f"   FAILURE adding public comment to {ticket_key}: {comment_result_public.get('error')}")
            print(f"      Details: {comment_result_public.get('details')}")


        print(f"\n3. Attempting to add an internal comment to ticket {ticket_key}...")
        comment_result_internal = add_jira_comment(
            issue_key=ticket_key,
            comment_body="This is an INTERNAL test comment. User indicated issue was resolved by bot.",
            is_public=False # For JSM, this means an internal note
        )
        if comment_result_internal.get("success"):
            print(f"   SUCCESS! Internal comment added to {ticket_key}.")
        else:
            print(f"   FAILURE adding internal comment to {ticket_key}: {comment_result_internal.get('error')}")
            print(f"      Details: {comment_result_internal.get('details')}")


        # --- 3. Test Closing the Ticket ---
        # IMPORTANT: Ensure JIRA_TRANSITION_ID_CLOSE is correctly set in your .env for your workflow!
        close_transition_id = os.getenv("JIRA_TRANSITION_ID_CLOSE")
        print(f"\n4. Attempting to close ticket {ticket_key} using transition ID '{close_transition_id}'...")
        
        if not close_transition_id:
            print("   SKIPPED: JIRA_TRANSITION_ID_CLOSE is not set in environment variables.")
        else:
            transition_result = transition_jira_ticket(
                issue_key=ticket_key,
                transition_id=close_transition_id
            )
            if transition_result.get("success"):
                print(f"   SUCCESS! Ticket {ticket_key} transitioned (closed/resolved).")
            else:
                print(f"   FAILURE closing ticket {ticket_key}: {transition_result.get('error')}")
                print(f"      Details: {transition_result.get('details')}")
                print(f"      Ensure transition ID '{close_transition_id}' is valid for the current status of {ticket_key} and your project's workflow.")

    else:
        print(f"   FAILURE creating ticket: {creation_result.get('error')}")
        print(f"      Details: {creation_result.get('details')}")

    print("\n--- Jira Integration Test Finished ---")

if __name__ == "__main__":
    run_jira_test()