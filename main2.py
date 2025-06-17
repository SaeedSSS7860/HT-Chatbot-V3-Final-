from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from chatbot_utils import (
    get_gemini_llm, get_embedding_model, get_it_retriever, get_hr_retriever,
    perform_duckduckgo_search, INITIAL_ANALYSIS_PROMPT_TEMPLATE,
    RESPONSE_GENERATION_PROMPT_TEMPLATE, RELEVANCE_CHECK_PROMPT_TEMPLATE,
    clean_json_response, extract_and_prepare_links, logger,
    TICKET_ASSIGNMENT_PROMPT_TEMPLATE,
    HR_KEKA_LINKS, HR_FALLBACK_MESSAGE, HR_ERROR_FALLBACK_MESSAGE
)
from ticketing_utils import (
    create_jira_ticket, add_jira_comment, transition_jira_ticket,
    find_transition_id_by_name,
    assign_jira_issue, set_jira_issue_priority,
    JIRA_TRANSITION_ID_IN_PROGRESS, JIRA_TRANSITION_ID_CLOSE,
    JIRA_L1_ASSIGNEE_ACCOUNT_ID, JIRA_L2_ASSIGNEE_ACCOUNT_ID
)
import os
import random
import uuid
import json

ROOT_PATH_PREFIX = os.getenv("ROOT_PATH_PREFIX", "")
logger.info(f"--- FastAPI starting with ROOT_PATH_PREFIX: '{ROOT_PATH_PREFIX}' ---")

FORCE_RECREATE_INDEXES = os.getenv("FORCE_RECREATE_INDEXES", "False").lower() == "true"
logger.info(f"FORCE_RECREATE_INDEXES set to: {FORCE_RECREATE_INDEXES}")

app = FastAPI(title="AI Support Assistant", version="2.1.4", root_path=ROOT_PATH_PREFIX) # Incremented version

EMPLOYEE_DATA_PATH = "data/employee_data.json"
EMPLOYEES: Dict[int, str] = {}

# --- (load_employee_data, startup_event, validation_exception_handler, mount, templates as before) ---
def load_employee_data():
    global EMPLOYEES
    try:
        if os.path.exists(EMPLOYEE_DATA_PATH):
            with open(EMPLOYEE_DATA_PATH, 'r', encoding='utf-8') as f:
                employee_list = json.load(f)
            for emp in employee_list:
                try:
                    emp_id_val = emp.get("Employee ID", emp.get("id"))
                    emp_name_val = emp.get("Employee Name", emp.get("firstName"))
                    if emp_id_val is not None and emp_name_val is not None:
                        emp_id = int(emp_id_val)
                        EMPLOYEES[emp_id] = str(emp_name_val)
                    else: logger.warning(f"Skipping employee record with missing ID or Name: {emp}")
                except (ValueError, TypeError) as e: logger.warning(f"Skipping invalid employee record: {emp}. Error: {e}")
            logger.info(f"Loaded {len(EMPLOYEES)} employee records from {EMPLOYEE_DATA_PATH}.")
        else:
            logger.error(f"{EMPLOYEE_DATA_PATH} not found. Employee ID verification will fail. Using embedded fallback.")
            employee_list_embedded = [
              {"Employee ID": 101185, "Employee Name": "Anurag Kule"}, {"Employee ID": 101528, "Employee Name": "Saeed Shaik"},
              {"Employee ID": 101414, "Employee Name": "Ramani Giri"}, {"Employee ID": 100155, "Employee Name": "Sumit Patil"},
              {"Employee ID": 101194, "Employee Name": "Manasi Kabade"}, {"Employee ID": 101211, "Employee Name": "Ishika Mude"},
              {"Employee ID": 101207, "Employee Name": "Pallavi Wankhede"}, {"Employee ID": 101368, "Employee Name": "William Dsouza"},
              {"Employee ID": 100011, "Employee Name": "Amit Raj"}, {"Employee ID": 100108, "Employee Name": "Salikram Maske"},
              {"Employee ID": 100087, "Employee Name": "Shilpa Hegde"}, {"Employee ID": 100139, "Employee Name": "Nishant Shukla"}
            ]
            for emp in employee_list_embedded: EMPLOYEES[int(emp["Employee ID"])] = emp["Employee Name"]
            logger.info(f"Loaded {len(EMPLOYEES)} embedded employee records.")
    except Exception as e: logger.error(f"Critical error loading employee data: {e}", exc_info=True)

@app.on_event("startup")
async def startup_event():
    load_employee_data()
    logger.info("Initializing LLM and Embedding Model...")
    global llm, embedding_model, it_retriever, hr_retriever
    llm = get_gemini_llm()
    embedding_model = get_embedding_model()
    logger.info("Initializing IT Retriever...")
    it_retriever = get_it_retriever(embedding_model, force_recreate=FORCE_RECREATE_INDEXES)
    if not it_retriever: logger.critical("IT Retriever could not be initialized.")
    logger.info("Initializing HR Retriever...")
    hr_retriever = get_hr_retriever(embedding_model, force_recreate=FORCE_RECREATE_INDEXES)
    if not hr_retriever: logger.critical("HR Retriever could not be initialized.")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    raw_body_bytes = await request.body()
    raw_body_str = raw_body_bytes.decode('utf-8', errors='ignore')
    logger.error(f"Pydantic Validation Error for request path: {request.url.path}")
    logger.error(f"Validation Errors: {exc.errors()}")
    logger.error(f"Problematic Raw Request Body: {raw_body_str}")
    return JSONResponse(status_code=422, content={"detail": exc.errors(), "body_received": raw_body_str})

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

class QueryRequest(BaseModel):
    user_query: str
    session_id: Optional[str] = None
    intent: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/chat", response_model=Dict[str, Any])
async def chat(data: QueryRequest):
    user_query_from_client = data.user_query
    session_id = data.session_id
    intent = data.intent

    if intent == "user_said_no_thank_you":
        if session_id and session_id in ACTIVE_SESSIONS:
            session_data_ref = ACTIVE_SESSIONS[session_id]
            session_data_ref["session_paused_after_farewell"] = True
            session_data_ref["expecting_new_typed_query"] = False
            logger.info(f"SID: {session_id} | Intent 'user_said_no_thank_you'. Session paused for {session_data_ref.get('employee_name')}.")
            return {
                "response": "Alright! Have a great day. Feel free to reach out if you need anything else.",
                "links": [], "options": [], "session_id": session_id,
                "next_action": "paused_wait_for_greeting_or_query"
            }
        else:
            intent = "reset_session_for_new_employee"

    if intent == "reset_session_for_new_employee":
        employee_name_for_log = "Unknown User"
        if session_id and session_id in ACTIVE_SESSIONS:
            employee_name_for_log = ACTIVE_SESSIONS[session_id].get('employee_name', 'Unknown User')
            ACTIVE_SESSIONS.pop(session_id)
        logger.info(f"SID: {session_id if session_id else 'N/A'} | Intent 'reset_session_for_new_employee'. Session fully cleared for {employee_name_for_log}.")
        return {
            "response": "Session has been reset. Please provide your Employee ID to start a new conversation.",
            "links": [], "options": [], "session_id": None, "next_action": "expect_employee_id"
        }

    if not session_id or session_id not in ACTIVE_SESSIONS:
        new_session_id = str(uuid.uuid4())
        log_message = f"New session started: {new_session_id}, awaiting employee ID."
        if session_id and session_id not in ACTIVE_SESSIONS:
            log_message = f"Session {session_id} (from client) not found or reset, re-initialized as {new_session_id}. Awaiting employee ID."
        session_id = new_session_id
        ACTIVE_SESSIONS[session_id] = {
            "awaiting_employee_id": True, "employee_id": None, "employee_name": None,
            "mode": None, "assistant_name": "AI Assistant",
            "original_query_context": None, "last_bot_response_for_feedback": None,
            "mismatched_query_info": None, "first_interaction_after_id": True,
            "expecting_new_typed_query": False, "just_stayed_in_mode": False,
            "session_paused_after_farewell": False
        }
        logger.info(log_message)
        return {
            "session_id": session_id,
            "response": "Dear User, Welcome to Hoonartek AI Assistant. I am here to assist you with the HR and IT related queries.\n\nTo proceed with the question, please provide your employee id.",
            "links": [], "options": [], "next_action": "expect_employee_id"
        }

    session_data = ACTIVE_SESSIONS[session_id]
    response_payload: Dict[str, Any] = {"session_id": session_id, "links": [], "options": []}
    logger.info(f"SID: {session_id} | Paused: {session_data.get('session_paused_after_farewell')} | AwaitingID: {session_data.get('awaiting_employee_id')} | EmpID: {session_data.get('employee_id')} | EmpName: {session_data.get('employee_name')} | Mode: {session_data.get('mode')} | ClientQ: '{user_query_from_client}' | Intent: {intent}")

    if session_data.get("session_paused_after_farewell"):
        session_data["session_paused_after_farewell"] = False
        analysis_prompt_for_greeting = INITIAL_ANALYSIS_PROMPT_TEMPLATE.format(user_query=user_query_from_client, assistant_mode=session_data.get("mode", "General").upper())
        try:
            analysis_response = llm.generate_content(analysis_prompt_for_greeting)
            parsed_analysis = clean_json_response(analysis_response.text)
            if parsed_analysis and parsed_analysis.get("best_source") == "Greeting":
                logger.info(f"SID: {session_id} | User greeted after pause. Prompting for department or continue.")
                first_name = session_data.get("employee_name", "User").split()[0]
                current_assistant_name = session_data.get("assistant_name", "AI Assistant")
                current_assistant_mode_paused = session_data.get("mode")
                if current_assistant_mode_paused:
                     response_payload["response"] = f"Hi {first_name}! You are currently with {current_assistant_name}. How can I help you further, or would you like to switch departments?"
                     options = [f"Continue with {current_assistant_mode_paused}", f"Switch to {'HR' if current_assistant_mode_paused == 'IT' else 'IT'} Assistant"]
                else:
                    response_payload["response"] = f"Hi {first_name}! Please select a department to continue:"
                    options = ["IT Related", "HR Related"]
                response_payload["options"] = options
                response_payload["next_action"] = "expect_mode_selection"
                return response_payload
        except Exception as e:
            logger.error(f"SID: {session_id} | Error analyzing greeting after pause: {e}", exc_info=True)

    if session_data.get("awaiting_employee_id"):
        try:
            submitted_id_str = user_query_from_client.strip()
            if not submitted_id_str:
                 response_payload["response"] = "Employee ID cannot be empty. Kindly enter your Employee ID to proceed."
                 response_payload["next_action"] = "expect_employee_id"; return response_payload
            submitted_id = int(submitted_id_str)
            if submitted_id in EMPLOYEES:
                employee_name = EMPLOYEES[submitted_id]
                session_data.update({"employee_id": submitted_id, "employee_name": employee_name, "awaiting_employee_id": False, "first_interaction_after_id": True})
                first_name = employee_name.split()[0]
                response_payload["response"] = f"Hi {first_name}, how can I assist you with? Please select:"
                response_payload["options"] = ["IT Related", "HR Related"]
                response_payload["next_action"] = "expect_mode_selection"
            else:
                response_payload["response"] = "Invalid Employee ID. Please try again."; response_payload["next_action"] = "expect_employee_id"
        except ValueError:
            response_payload["response"] = "Employee ID should be a number. Please enter a valid Employee ID."; response_payload["next_action"] = "expect_employee_id"
        return response_payload

    current_mode = session_data.get("mode")
    assistant_name = session_data.get("assistant_name", f"{session_data.get('employee_name', 'User')}'s Assistant")

    if intent == "select_mode_it" or intent == "select_mode_hr" or intent == "continue_with_current_mode":
        new_mode = current_mode
        if intent == "continue_with_current_mode":
            if not new_mode:
                logger.error(f"SID: {session_id} | 'continue_with_current_mode' but no current_mode set.")
                response_payload["response"] = "It seems there was an issue. Please select a department."
                response_payload["options"] = ["IT Related", "HR Related"]
                response_payload["next_action"] = "expect_mode_selection"
                return response_payload
        else:
            new_mode = "IT" if intent == "select_mode_it" else "HR"

        session_data.update({"mode": new_mode, "assistant_name": f"{new_mode} Assistant", "first_interaction_after_id": False, "mismatched_query_info": None, "original_query_context": None, "expecting_new_typed_query": False, "just_stayed_in_mode": False})
        if new_mode == "IT" and intent != "continue_with_current_mode":
            session_data.update({"jira_ticket_key": None, "assigned_level": None, "pending_email_for_ticket_update": None, "original_query_context_for_ticket": None})
        logger.info(f"SID: {session_id} | Intent '{intent}': Mode set/switched/continued to {new_mode} for {session_data.get('employee_name')}.")
        other_mode_text = "HR" if new_mode == "IT" else "IT"
        response_payload["response"] = f"You’re now connected with the {session_data['assistant_name']}. How can I help you today?"
        response_payload["mode_selected"] = new_mode
        response_payload["options"] = [f"Switch to {other_mode_text} Assistant", "No, Thank you."]
        return response_payload

    if not current_mode:
        first_name = session_data.get("employee_name", "User").split()[0]
        logger.info(f"SID: {session_id} | Employee {first_name} verified, but no mode selected. Reprompting.")
        response_payload["response"] = f"Hi {first_name}, please select which assistant you need:"
        response_payload["options"] = ["IT Related", "HR Related"]; response_payload["next_action"] = "expect_mode_selection"
        return response_payload

    if intent == "ask_another_question_init" or intent == "rephrase_question_init":
        prompt_verb = "type" if intent == "ask_another_question_init" else "rephrase"
        logger.info(f"SID: {session_id} | Intent '{intent}' in {current_mode} mode by {session_data.get('employee_name')}.")
        session_data["original_query_context"] = None
        session_data["expecting_new_typed_query"] = True
        session_data["just_stayed_in_mode"] = False
        response_payload["response"] = f"Alright, please {prompt_verb} your {current_mode} question."
        response_payload["options"] = []
        session_data["last_bot_response_for_feedback"] = response_payload["response"]
        return response_payload

    if current_mode == "IT" and intent == "provide_email_for_ticket_update":
        # Check if we are genuinely expecting an email for a specific ticket
        ticket_key_for_email = session_data.get("pending_email_for_ticket_update")
        if ticket_key_for_email: # We were expecting an email for this ticket
            user_email = user_query_from_client.strip()
            if not (user_email and "@" in user_email and "." in user_email.split("@")[-1]):
                # Invalid email format, re-prompt for email for the same ticket
                return {"response": "That doesn't look like a valid email address. Please enter your email:", 
                        "links": [], "options": [], 
                        "next_action": "expect_email_for_ticket_update", # Keep expecting email
                        "session_id": session_id}
            
            session_data.pop("pending_email_for_ticket_update", None) # Clear the pending flag
            add_jira_comment(ticket_key_for_email, f"Chatbot (IT): User contact email: {user_email}", is_public=False)
            session_data["reporter_email"] = user_email # Store email for future use in this session
            retrieved_assigned_level = session_data.get("assigned_level", "support")
            
            # Clear ticket-specific context as this problem's escalation is done
            session_data.update({"jira_ticket_key": None, "assigned_level": None, 
                                 "original_query_context": None, "last_bot_response_for_feedback": None, 
                                 "expecting_new_typed_query": False, "original_query_context_for_ticket": None,
                                 "just_stayed_in_mode": False})
            
            options_after_email = [f"Ask another {current_mode} question", f"Switch to HR Assistant", "No, Thank you."]
            response_text = f"Thanks! IT Ticket **{ticket_key_for_email}** is now being handled by our {retrieved_assigned_level} staff. We’ll contact you at **{user_email}** if needed. How else can I help?"
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response":response_text, "links": [], "options": options_after_email, "session_id": session_id}
        else:
            # Intent is provide_email_for_ticket_update, but we weren't expecting one.
            # This is an anomaly. Respond gracefully.
            logger.warning(f"SID: {session_id} | Received 'provide_email_for_ticket_update' but 'pending_email_for_ticket_update' was not set.")
            response_text = "I wasn't expecting an email right now. How can I help you?"
            options = [f"Ask another {current_mode} question", f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant", "No, Thank you."]
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": options, "session_id": session_id}


    query_context_for_feedback = session_data.get("original_query_context", "the previous issue")
    last_bot_response_text = session_data.get("last_bot_response_for_feedback", "Chatbot provided an answer.")
    ticket_key = session_data.get("jira_ticket_key") if current_mode == "IT" else None

    if intent == "user_feedback_helpful":
        logger.info(f"SID: {session_id} | Intent 'user_feedback_helpful' for query context: '{query_context_for_feedback}' by {session_data.get('employee_name')}")
        response_text_line1 = "I'm glad I could help!"
        response_text_line2 = "Is there anything else I can assist you with?"
        options = ["Yes, I need assistance with something else", "No, Thank you."]

        if current_mode == "IT" and ticket_key:
            add_jira_comment(ticket_key, f"Chatbot (IT): User indicated helpful. Query context: \"{query_context_for_feedback}\". Closing.", is_public=False)
            close_transition_id = JIRA_TRANSITION_ID_CLOSE or find_transition_id_by_name(ticket_key, ["Done", "Resolve Issue", "Close Issue", "Resolve", "Closed", "RESOLVED"])
            if close_transition_id:
                transition_result = transition_jira_ticket(ticket_key, close_transition_id)
                response_text_line1 = f"Glad I could help with the IT issue! Ticket {ticket_key} is now " + ("closed." if transition_result.get("success") else "marked for closing.")
            else: response_text_line1 = f"Glad I could help with the IT issue! (Close transition not found for ticket {ticket_key})."
            session_data.pop("jira_ticket_key", None); session_data.pop("assigned_level", None); session_data.pop("pending_email_for_ticket_update", None)
            session_data.pop("original_query_context_for_ticket", None)
        elif current_mode == "HR": response_text_line1 = "I'm glad I could help with your HR question!"
        full_response_text = f"{response_text_line1}\n\n{response_text_line2}"
        session_data.update({"original_query_context": None, "last_bot_response_for_feedback": full_response_text, "expecting_new_typed_query": False, "just_stayed_in_mode": False})
        return {"response": full_response_text, "links": [], "options": options, "session_id": session_id }

    if intent == "user_feedback_not_helpful":
        logger.info(f"SID: {session_id} | Intent 'user_feedback_not_helpful' for query context: '{query_context_for_feedback}' by {session_data.get('employee_name')}")
        session_data["expecting_new_typed_query"] = False

        if current_mode == "HR":
            logger.info(f"SID: {session_id} | User feedback 'Not Helpful' in HR mode. Providing HR fallback.")
            response_text ="Sorry that wasn’t helpful. Please check the following links or try rephrasing your question."
            session_data["last_bot_response_for_feedback"] = response_text
            hr_fallback_options = [f"Rephrase my {current_mode} question","No, Thank you."]
            session_data["just_stayed_in_mode"] = False
            return {"response": response_text, "links": HR_KEKA_LINKS, "options": hr_fallback_options, "session_id": session_id}

        options_after_not_helpful = [f"Ask another {current_mode} question", "No, Thank you."]
        if not session_data.get("just_stayed_in_mode"):
            options_after_not_helpful.insert(1, f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant")
        session_data["just_stayed_in_mode"] = False

        if current_mode == "IT" and ticket_key:
            add_jira_comment(ticket_key, f"Chatbot (IT): User NOT helped. Query context: \"{query_context_for_feedback}\". Bot's last response: \"{last_bot_response_text[:200]}...\". Initiating LLM assignment.", is_public=True)
            assignment_prompt_text = TICKET_ASSIGNMENT_PROMPT_TEMPLATE.format(user_query=query_context_for_feedback, chatbot_response=last_bot_response_text, user_feedback="User found the chatbot's IT response not helpful.")
            assigned_to_level_str, llm_priority_name_for_response = "L1 (default on error)", "Medium"
            try: 
                assignment_llm_response = llm.generate_content(assignment_prompt_text)
                assignment_details = clean_json_response(assignment_llm_response.text)
                if assignment_details: 
                    llm_level, llm_priority_name = assignment_details.get("assignment_level", "L1").upper(), assignment_details.get("priority", "Medium").capitalize()
                    assigned_to_level_str, llm_priority_name_for_response = llm_level, llm_priority_name
                    add_jira_comment(ticket_key, f"LLM Routing Suggestion (IT):\nLevel: {llm_level}\nPriority: {llm_priority_name}\nCategory: {assignment_details.get('suggested_category', 'N/A')}\nReason: {assignment_details.get('reasoning', 'N/A')}", is_public=False)
                    assignee_id_to_set = None 
                    if llm_level == "L1" and JIRA_L1_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L1_ASSIGNEE_ACCOUNT_ID
                    elif llm_level == "L2" and JIRA_L2_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L2_ASSIGNEE_ACCOUNT_ID
                    elif JIRA_L1_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L1_ASSIGNEE_ACCOUNT_ID; assigned_to_level_str = "L1 (defaulted)"
                    if assignee_id_to_set: assign_jira_issue(ticket_key, assignee_id_to_set)
                    else: assigned_to_level_str = "Unassigned (by bot)"
                    priority_map = {"High": "1", "Highest": "1", "Medium": "2", "Low": "3", "Lowest": "4"}
                    set_jira_issue_priority(ticket_key, priority_map.get(llm_priority_name, "2"))
                else: 
                    if JIRA_L1_ASSIGNEE_ACCOUNT_ID: assign_jira_issue(ticket_key, JIRA_L1_ASSIGNEE_ACCOUNT_ID)
                    set_jira_issue_priority(ticket_key, "2") 
            except Exception as e: logger.error(f"SID: {session_id} | Error LLM ticket assignment for {ticket_key}: {e}", exc_info=True)

            session_data["assigned_level"] = assigned_to_level_str
            if not session_data.get("reporter_email"):
                session_data["pending_email_for_ticket_update"] = ticket_key # Set flag before asking for email
                temp_response_payload = {"response": f"Thanks for the IT feedback. Your ticket **{ticket_key}** has been escalated to our {assigned_to_level_str} support team with *{llm_priority_name_for_response}* urgency. Please share your email so we can follow up with you.",
                                   "links": [], "options": [], "next_action": "expect_email_for_ticket_update", "session_id": session_id}
            else:
                session_data.update({"jira_ticket_key": None, "assigned_level": None, "original_query_context": None, "last_bot_response_for_feedback": None, "original_query_context_for_ticket": None})
                temp_response_payload = {"response": f"I'm sorry the previous IT solution wasn't helpful. Your issue (Ticket: **{ticket_key}**) has been routed to our {assigned_to_level_str} team with *{llm_priority_name_for_response}* priority using your email {session_data.get('reporter_email')}. How else can I help?",
                                   "links": [], "options": options_after_not_helpful, "session_id": session_id}
            session_data["last_bot_response_for_feedback"] = temp_response_payload["response"]
            return temp_response_payload
        
        response_text = "I'll try to do better. How else can I help?"
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": options_after_not_helpful, "session_id": session_id}

    # --- Main Query Processing Logic ---
    # (This section remains largely the same, but the email intent is handled above now)
    # ...
    query_to_process = user_query_from_client
    simplified_query_to_process = user_query_from_client
    source_classification = "Internal_Docs"
    was_expecting_new_typed_query = session_data.pop("expecting_new_typed_query", False)

    if intent == "stay_in_current_mode":
        mismatched_info = session_data.get("mismatched_query_info")
        if mismatched_info:
            query_to_process = mismatched_info.get("original_query", query_to_process)
            simplified_query_to_process = mismatched_info.get("simplified_query", query_to_process)
            session_data.pop("mismatched_query_info", None)
        session_data["original_query_context"] = query_to_process
        session_data["just_stayed_in_mode"] = True
    elif not intent: 
        if session_data.get("just_stayed_in_mode"): 
            session_data["just_stayed_in_mode"] = False
        if was_expecting_new_typed_query:
            logger.info(f"SID: {session_id} | Processing as new typed query after prompt. Bypassing LLM analysis for: '{query_to_process}'")
            source_classification = "Internal_Docs"
            session_data["original_query_context"] = query_to_process
        else:
            session_data["original_query_context"] = query_to_process
            analysis_prompt = INITIAL_ANALYSIS_PROMPT_TEMPLATE.format(user_query=query_to_process, assistant_mode=current_mode.upper())
            try: 
                analysis_response = llm.generate_content(analysis_prompt)
                logger.debug(f"SID: {session_id} | RAW LLM Analysis Response Text: {analysis_response.text}")
                parsed_analysis = clean_json_response(analysis_response.text)
                if parsed_analysis:
                    logger.info(f"SID: {session_id} | Parsed LLM Analysis: {parsed_analysis}")
                    source_classification = parsed_analysis.get("best_source", "Internal_Docs")
                    simplified_query_to_process = parsed_analysis.get("simplified_query_for_search", query_to_process)
                else:
                    logger.warning(f"SID: {session_id} | Failed to parse JSON from analysis for '{query_to_process}'. Raw: {analysis_response.text}. Defaulting.")
            except Exception as e: 
                logger.error(f"SID: {session_id} | Analysis step failed for query '{query_to_process}': {e}", exc_info=True)
                error_response_text = HR_ERROR_FALLBACK_MESSAGE if current_mode == "HR" else f"Sorry, I had trouble understanding that {current_mode} query. Could you rephrase?"
                error_options = [f"Rephrase my {current_mode} question", f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant", "No, Thank you."]
                session_data["last_bot_response_for_feedback"] = error_response_text
                return {"response": error_response_text, "links": HR_KEKA_LINKS if current_mode == "HR" else [], "options": error_options, "session_id": session_id}

    elif intent and not was_expecting_new_typed_query : 
        session_data["just_stayed_in_mode"] = False 
        session_data["original_query_context"] = query_to_process
        analysis_prompt = INITIAL_ANALYSIS_PROMPT_TEMPLATE.format(user_query=query_to_process, assistant_mode=current_mode.upper())
        try:
            analysis_response = llm.generate_content(analysis_prompt)
            logger.debug(f"SID: {session_id} | RAW LLM Analysis (for button text) Response Text: {analysis_response.text}")
            parsed_analysis = clean_json_response(analysis_response.text)
            if parsed_analysis:
                logger.info(f"SID: {session_id} | Parsed LLM Analysis (for button text): {parsed_analysis}")
                source_classification = parsed_analysis.get("best_source", "Internal_Docs")
                simplified_query_to_process = parsed_analysis.get("simplified_query_for_search", query_to_process)
            else:
                logger.warning(f"SID: {session_id} | Failed to parse JSON (for button text) from analysis for '{query_to_process}'. Raw: {analysis_response.text}. Defaulting.")
        except Exception as e:
            logger.error(f"SID: {session_id} | Analysis step failed for button text query '{query_to_process}': {e}", exc_info=True)
            source_classification = "Internal_Docs"
            simplified_query_to_process = query_to_process


    logger.info(f"SID: {session_id} | Processing Final Query: '{query_to_process}' | Source: {source_classification}, Simplified: '{simplified_query_to_process}'")

    post_classification_options = ["No, Thank you."]
    if not session_data.get("just_stayed_in_mode"):
         post_classification_options.insert(0, f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant")

    if source_classification == "Greeting":
        response_text = random.choice([f"Hi! This is your {assistant_name}. How can I assist you today?", f"Hello! Need help with something in {current_mode}?"])
        if "how are you" in query_to_process.lower() or "how are u" in query_to_process.lower(): response_text = f"I’m all set to assist with any {current_mode}-related queries you have."
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": post_classification_options, "session_id": session_id}

    if source_classification == "OutOfScope":
        response_text = random.choice([f"My apologies, I can only assist with {current_mode}-related matters.", f"That seems outside my current scope as the {assistant_name}."]) + f" Do you have a {current_mode} question?"
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": post_classification_options, "session_id": session_id}

    if source_classification == "TopicMismatch":
        other_mode = "HR" if current_mode == "IT" else "IT"
        other_assistant_name = f"{other_mode} Assistant"
        response_text = f"It appears your query aligns more with {other_mode} topics. You're currently with {assistant_name}. Would you like to switch to the {other_assistant_name}?"
        options_mismatch = [f"Yes, switch to {other_assistant_name}", f"No, stay with {assistant_name}"]
        session_data["mismatched_query_info"] = {"original_query": query_to_process, "simplified_query": simplified_query_to_process}
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": options_mismatch, "session_id": session_id}

    if current_mode == "IT" and source_classification in ["Internal_Docs", "Web_Search_IT"]:
        if not ticket_key or session_data.get("original_query_context_for_ticket") != query_to_process:
            if ticket_key:
                logger.info(f"SID: {session_id} | New IT query '{query_to_process}', different from previous ticket {ticket_key}'s query ('{session_data.get('original_query_context_for_ticket')}'). Will create a new ticket.")
                session_data.pop("jira_ticket_key", None); ticket_key = None
                session_data.pop("original_query_context_for_ticket", None)
            if not ticket_key:
                logger.info(f"SID: {session_id} | New IT query for ticket: '{query_to_process}'. Creating Jira ticket.")
                ticket_summary = f"Chatbot IT ({session_data.get('employee_name', 'N/A')} - EmpID {session_data.get('employee_id', 'N/A')}): {query_to_process[:60]}..."
                ticket_description = f"Employee: {session_data.get('employee_name', 'N/A')} (ID: {session_data.get('employee_id', 'N/A')})\nQuery (IT Mode): {query_to_process}"
                ticket_result = create_jira_ticket(summary=ticket_summary, description_text=ticket_description, reporter_email=session_data.get("reporter_email"))
                if ticket_result.get("success"):
                    ticket_key = ticket_result["ticket_key"]; session_data["jira_ticket_key"] = ticket_key
                    session_data["original_query_context_for_ticket"] = query_to_process
                    session_data["assigned_level"] = "L1 (initial)"
                    add_jira_comment(ticket_key, f"Chatbot (IT): Ticket for query: \"{query_to_process}\". Bot attempting to resolve.", is_public=False)
                    in_progress_id = JIRA_TRANSITION_ID_IN_PROGRESS or find_transition_id_by_name(ticket_key, ["Start Work", "In Progress", "Work In Progress", "OPEN"])
                    if in_progress_id: transition_jira_ticket(ticket_key, in_progress_id)
                else: logger.error(f"SID: {session_id} | Failed to create IT Jira ticket for '{query_to_process}': {ticket_result.get('error')}")
        elif ticket_key:
             add_jira_comment(ticket_key, f"Chatbot (IT): User follow-up on same issue ({ticket_key}): \"{query_to_process}\"", is_public=False)

    context = ""; retrieved_docs_source_type = f"{current_mode} Internal Docs"
    active_retriever = it_retriever if current_mode == "IT" else hr_retriever
    if not active_retriever: 
        logger.error(f"SID: {session_id} | {current_mode} retriever is not available.")
        error_response_options = [f"Rephrase my {current_mode} question", f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant", "No, Thank you."]
        if current_mode == "HR":
            session_data["last_bot_response_for_feedback"] = HR_ERROR_FALLBACK_MESSAGE
            return {"response": HR_ERROR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": error_response_options, "session_id": session_id}
        else:
            response_text = f"I'm currently unable to search {current_mode} documents. Please try again later."
            if ticket_key: response_text += f" Your query for ticket {ticket_key} is logged."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": error_response_options, "session_id": session_id}

    if source_classification == "Internal_Docs": 
        try:
            docs = active_retriever.get_relevant_documents(simplified_query_to_process)
            if docs:
                context_from_docs = "\n\n---\n\n".join([f"Source: {d.metadata.get('source', 'Document')}\n{d.page_content}" for d in docs])
                relevance_prompt_text = RELEVANCE_CHECK_PROMPT_TEMPLATE.format(user_query=query_to_process, simplified_query=simplified_query_to_process, retrieved_context=context_from_docs[:3000])
                if not llm: raise Exception("LLM not initialized for relevance check.")
                rel_check_response = llm.generate_content(relevance_prompt_text)
                if "NO" in rel_check_response.text.strip().upper():
                    context = "";
                    if current_mode == "IT": source_classification = "Web_Search_IT"
                else: context = context_from_docs
            elif current_mode == "IT": source_classification = "Web_Search_IT"
        except Exception as e:
            logger.error(f"SID: {session_id} | Retriever/relevance error for {current_mode} query '{simplified_query_to_process}': {e}", exc_info=True)
            if current_mode == "IT": source_classification = "Web_Search_IT"

    if not context and current_mode == "IT" and source_classification == "Web_Search_IT": 
        logger.info(f"SID: {session_id} | Performing web search for IT query: {simplified_query_to_process}")
        context = perform_duckduckgo_search(simplified_query_to_process)
        retrieved_docs_source_type = "Web Search Results"
        if "did not yield specific results" in context or "failed" in context: context = ""
    
    no_context_options_after_rag_final = [f"Rephrase my {current_mode} question", "No, Thank you."]
    #if not session_data.get("just_stayed_in_mode"): 
    #     no_context_options_after_rag_final.insert(1, f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant")

    if not context:
        if current_mode == "HR":
            logger.info(f"SID: {session_id} | No context found for HR query '{query_to_process}'. Providing Keka links and rephrase option.")
            session_data["last_bot_response_for_feedback"] = HR_FALLBACK_MESSAGE
            hr_no_context_options = [f"Rephrase my {current_mode} question","No, Thank you."]
            return {"response": HR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": hr_no_context_options, "session_id": session_id}
        elif current_mode == "IT":
            response_text = "I couldn't find specific information for your IT query in my documents or via web search right now."
            if ticket_key: response_text += f" Your IT query has been logged (Ticket: {ticket_key}). An agent may review it if the issue persists."
            else: response_text += " You can try rephrasing or asking a different IT question."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": no_context_options_after_rag_final, "session_id": session_id}

    final_prompt_for_llm = RESPONSE_GENERATION_PROMPT_TEMPLATE.format(user_query=query_to_process, source_type_used=retrieved_docs_source_type, context=context)
    try:
        if not llm: raise Exception("LLM not initialized for response generation.")
        final_response_content = llm.generate_content(final_prompt_for_llm)
        raw_llm_response_text = final_response_content.text
        processed_text_for_display, extracted_links = extract_and_prepare_links(raw_llm_response_text)
        session_data["last_bot_response_for_feedback"] = processed_text_for_display[:500]
        feedback_options = ["👍 Helpful", "👎 Not Helpful"]
        if current_mode == "IT" and ticket_key: add_jira_comment(ticket_key, f"Chatbot IT response for \"{query_to_process}\":\n{processed_text_for_display[:500]}...", is_public=False)
        return {"response": processed_text_for_display, "links": extracted_links, "options": feedback_options, "session_id": session_id }
    except Exception as e: 
        logger.error(f"SID: {session_id} | LLM response generation error for {current_mode} query '{query_to_process}': {e}. Ticket: {ticket_key or 'N/A'}", exc_info=True)
        error_response_options_final = [f"Rephrase my {current_mode} question", f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant", "No, Thank you."]
        if current_mode == "HR":
            session_data["last_bot_response_for_feedback"] = HR_ERROR_FALLBACK_MESSAGE
            return {"response": HR_ERROR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": error_response_options_final, "session_id": session_id}
        else:
            response_text = f"Sorry, I encountered an issue generating an IT response."
            if ticket_key: response_text += f" Your IT query was logged (Ticket: {ticket_key}). Please try rephrasing."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": error_response_options_final, "session_id": session_id}

    logger.error(f"SID: {session_id} | Fallback: No specific response path taken for query: '{query_to_process}'")
    fallback_options = [f"Ask another {current_mode} question", f"Switch to {'HR' if current_mode == 'IT' else 'IT'} Assistant", "No, Thank you."]
    session_data["last_bot_response_for_feedback"] = "I'm having trouble processing that. Please try rephrasing or select an option."
    return {"response": "I'm having trouble processing that. Please try rephrasing or select an option.", "links": [], "options": fallback_options, "session_id": session_id}