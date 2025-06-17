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

app = FastAPI(title="AI Support Assistant", version="1.3.6", root_path=ROOT_PATH_PREFIX) # Incremented version

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

llm = get_gemini_llm()
embedding_model = get_embedding_model()

logger.info("Initializing IT Retriever...")
it_retriever = get_it_retriever(embedding_model, force_recreate=FORCE_RECREATE_INDEXES)
if not it_retriever: logger.critical("IT Retriever could not be initialized. IT document search will be unavailable.")

logger.info("Initializing HR Retriever...")
hr_retriever = get_hr_retriever(embedding_model, force_recreate=FORCE_RECREATE_INDEXES)
if not hr_retriever: logger.critical("HR Retriever could not be initialized. HR document search will be unavailable.")

ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}

class QueryRequest(BaseModel):
    user_query: str 
    session_id: Optional[str] = None
    intent: Optional[str] = None

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "name": "User"})

@app.post("/chat", response_model=Dict[str, Any])
async def chat(data: QueryRequest):
    user_query_from_client = data.user_query 
    session_id = data.session_id
    intent = data.intent

    if not session_id:
        session_id = str(uuid.uuid4())
        ACTIVE_SESSIONS[session_id] = {"mode": None, "assistant_name": "AI Assistant", "original_query_context": None, "last_bot_response_for_feedback": None, "mismatched_query_info": None}
        logger.info(f"New session started: {session_id}")
    elif session_id not in ACTIVE_SESSIONS:
        ACTIVE_SESSIONS[session_id] = {"mode": None, "assistant_name": "AI Assistant", "original_query_context": None, "last_bot_response_for_feedback": None, "mismatched_query_info": None}
        logger.warning(f"Session {session_id} not found, re-initialized.")

    session_data = ACTIVE_SESSIONS[session_id]
    current_mode = session_data.get("mode")
    assistant_name = session_data.get("assistant_name", "AI Assistant")
    response_payload: Dict[str, Any] = {"session_id": session_id, "links": [], "options": []}

    logger.info(f"SID: {session_id} | Mode: {current_mode} | Client Query: '{user_query_from_client}' | Intent: {intent}")

    # --- PRIORITY 1: Handle Mode Selection/Switching Intents ---
    if intent == "select_mode_it" or intent == "select_mode_hr":
        new_mode = "IT" if intent == "select_mode_it" else "HR"
        session_data["mode"] = new_mode
        session_data["assistant_name"] = f"{new_mode} Assistant"
        if new_mode == "IT":
            session_data.pop("jira_ticket_key", None); session_data.pop("reporter_email", None)
            session_data.pop("assigned_level", None); session_data.pop("pending_email_for_ticket_update", None)
        session_data.pop("mismatched_query_info", None); session_data["original_query_context"] = None
        logger.info(f"SID: {session_id} | Intent '{intent}': Mode switched to {new_mode}.")
        response_payload["response"] = random.choice([
                        f"You’re now connected to {session_data['assistant_name']}. What would you like help with in {new_mode}?",
                        f"Hello! I'm the {session_data['assistant_name']}. How can I help with your {new_mode} questions today?"])
        response_payload["mode_selected"] = new_mode
        response_payload["options"] = [f"Ask another {new_mode} question", f"Switch to {'HR' if new_mode == 'IT' else 'IT'} Assistant", "No, that's all"]
        return response_payload

    if not current_mode:
        logger.info(f"SID: {session_id} | No mode selected. Reprompting.")
        response_payload["response"] = "To get started, please choose a department below:"
        response_payload["options"] = ["IT Assistant", "HR Assistant"]
        return response_payload

    # --- PRIORITY 2: Handle Feedback, Email Intents ---
    query_context_for_feedback = session_data.get("original_query_context", "the previous issue")
    last_bot_response_text = session_data.get("last_bot_response_for_feedback", "Chatbot provided an answer.")
    ticket_key = session_data.get("jira_ticket_key") if current_mode == "IT" else None

    if intent == "user_feedback_helpful":
        logger.info(f"SID: {session_id} | Intent 'user_feedback_helpful' for query context: '{query_context_for_feedback}'")
        response_text = "I'm glad the information was helpful. Let me know if there's anything else I can assist you with."
        options = [f"Ask another {current_mode} question", "Switch to IT Assistant" if current_mode == "HR" else "Switch to HR Assistant", "No, I'm good"]
        if current_mode == "IT" and ticket_key:
            logger.info(f"SID: {session_id} | User found IT help for ticket {ticket_key} regarding '{query_context_for_feedback}'. Attempting to close.")
            add_jira_comment(ticket_key, f"Chatbot (IT): User indicated helpful. Query context: \"{query_context_for_feedback}\". Closing.", is_public=False)
            close_transition_id = JIRA_TRANSITION_ID_CLOSE or find_transition_id_by_name(ticket_key, ["Done", "Resolve Issue", "Close Issue", "Resolve", "Closed", "RESOLVED"])
            if close_transition_id:
                logger.info(f"SID: {session_id} | Found close transition ID '{close_transition_id}' for ticket {ticket_key}.")
                transition_result = transition_jira_ticket(ticket_key, close_transition_id)
                if transition_result.get("success"): 
                    logger.info(f"SID: {session_id} | Successfully closed Jira ticket {ticket_key}.")
                    response_text = random.choice([
                                "Glad I could help! Let me know if there’s anything else I can support you with.",
                                "Happy to assist! Feel free to ask another IT-related question anytime.",
                                "You're welcome! I'm here if you have any more technical questions."])
                else: 
                    logger.warning(f"SID: {session_id} | Failed to auto-close Jira ticket {ticket_key}: {transition_result.get('error')}")
                    response_text = random.choice([f"Glad I could help with the IT issue! (Ticket close attempt made).", f"Awesome! (Ticket close attempt made)."])
            else: 
                logger.warning(f"SID: {session_id} | Close transition not found for ticket {ticket_key}. Cannot auto-close.")
                response_text = random.choice([f"Glad I could help with the IT issue! (Close transition not found).", f"Awesome! (Close transition not found)."])
            session_data.pop("jira_ticket_key", None); session_data.pop("assigned_level", None); session_data.pop("pending_email_for_ticket_update", None)
        elif current_mode == "HR":
            response_text = random.choice([
            "Glad I could assist with that! Let me know if you have any other HR questions.",
            "You're welcome! I’m here for any other HR-related assistance.",
            "Happy to help! Feel free to ask more if needed."])

        session_data["original_query_context"] = None; session_data["last_bot_response_for_feedback"] = None
        return {"response": response_text, "links": [], "options": options, "session_id": session_id }

    if intent == "user_feedback_not_helpful":
        logger.info(f"SID: {session_id} | Intent 'user_feedback_not_helpful' for query context: '{query_context_for_feedback}'")
        options = [f"Ask another {current_mode} question", "Switch to IT Assistant" if current_mode == "HR" else "Switch to HR Assistant", "No, that's all"]
        if current_mode == "IT" and ticket_key:
            logger.info(f"SID: {session_id} | User NOT helped for IT ticket {ticket_key} ('{query_context_for_feedback}'). Initiating LLM-based routing.")
            add_jira_comment(ticket_key, f"Chatbot (IT): User NOT helped. Query context: \"{query_context_for_feedback}\". Bot's last response: \"{last_bot_response_text[:200]}...\". Initiating LLM assignment and routing.", is_public=True)
            assignment_prompt_text = TICKET_ASSIGNMENT_PROMPT_TEMPLATE.format(user_query=query_context_for_feedback, chatbot_response=last_bot_response_text, user_feedback="User found the chatbot's IT response not helpful.")
            assigned_to_level_str = "L1 (default on error)"; llm_priority_name_for_response = "Medium"
            try:
                logger.debug(f"SID: {session_id} | Sending assignment prompt to LLM for ticket {ticket_key}.")
                assignment_llm_response = llm.generate_content(assignment_prompt_text)
                assignment_details = clean_json_response(assignment_llm_response.text)
                if assignment_details:
                    logger.info(f"SID: {session_id} | LLM Assignment for IT ticket {ticket_key}: {assignment_details}")
                    llm_level = assignment_details.get("assignment_level", "L1").upper(); llm_priority_name = assignment_details.get("priority", "Medium").capitalize()
                    llm_reasoning = assignment_details.get("reasoning", "N/A"); llm_category = assignment_details.get("suggested_category", "N/A")
                    llm_priority_name_for_response = llm_priority_name; assigned_to_level_str = llm_level
                    add_jira_comment(ticket_key, f"LLM Routing Suggestion (IT):\nLevel: {llm_level}\nPriority: {llm_priority_name}\nCategory: {llm_category}\nReason: {llm_reasoning}", is_public=False)
                    assignee_id_to_set = None
                    if llm_level == "L1" and JIRA_L1_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L1_ASSIGNEE_ACCOUNT_ID
                    elif llm_level == "L2" and JIRA_L2_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L2_ASSIGNEE_ACCOUNT_ID
                    elif JIRA_L1_ASSIGNEE_ACCOUNT_ID: assignee_id_to_set = JIRA_L1_ASSIGNEE_ACCOUNT_ID; assigned_to_level_str = "L1 (defaulted)"
                    if assignee_id_to_set:
                        assign_result = assign_jira_issue(ticket_key, assignee_id_to_set)
                        if assign_result.get("success"): logger.info(f"SID: {session_id} | Successfully assigned ticket {ticket_key} to {assigned_to_level_str} ({assignee_id_to_set}).")
                        else: logger.error(f"SID: {session_id} | Failed to assign ticket {ticket_key} to {assigned_to_level_str}: {assign_result.get('error')}")
                    else: logger.warning(f"SID: {session_id} | No assignee ID for level {assigned_to_level_str} or default L1 for ticket {ticket_key}."); assigned_to_level_str = "Unassigned (by bot)"
                    priority_map = {"High": "1", "Highest": "1", "Medium": "2", "Low": "3", "Lowest": "4"} # ADJUST THESE IDs
                    jira_priority_id_to_set = priority_map.get(llm_priority_name, priority_map.get("Medium"))
                    priority_result = set_jira_issue_priority(ticket_key, jira_priority_id_to_set)
                    if priority_result.get("success"): logger.info(f"SID: {session_id} | Successfully set priority for ticket {ticket_key} to '{llm_priority_name}' (ID: {jira_priority_id_to_set}).")
                    else: logger.error(f"SID: {session_id} | Failed to set priority for ticket {ticket_key}: {priority_result.get('error')}")
                else: 
                    logger.warning(f"SID: {session_id} | Could not parse LLM assignment for IT ticket {ticket_key}. Applying default L1/Medium.")
                    if JIRA_L1_ASSIGNEE_ACCOUNT_ID: assign_jira_issue(ticket_key, JIRA_L1_ASSIGNEE_ACCOUNT_ID)
                    set_jira_issue_priority(ticket_key, "2") 
                    assigned_to_level_str = "L1 (default on parse error)"; llm_priority_name_for_response = "Medium"
            except Exception as e:
                logger.error(f"SID: {session_id} | Error during LLM ticket assignment/Jira update for ticket {ticket_key}: {e}", exc_info=True)
                if JIRA_L1_ASSIGNEE_ACCOUNT_ID: assign_jira_issue(ticket_key, JIRA_L1_ASSIGNEE_ACCOUNT_ID)
                set_jira_issue_priority(ticket_key, "2")
                assigned_to_level_str = "L1 (default on exception)"; llm_priority_name_for_response = "Medium"
            session_data["assigned_level"] = assigned_to_level_str
            if not session_data.get("reporter_email"):
                session_data["pending_email_for_ticket_update"] = ticket_key
                return {"response": f"Thanks for the IT feedback. Your ticket **{ticket_key}** has been escalated to our {assigned_to_level_str} support team with *{llm_priority_name_for_response}* urgency. Please share your email so we can follow up with you.",
                        "links": [], "options": [], "next_action": "expect_email_for_ticket_update", "session_id": session_id}
            else: # Email known, complete escalation and clear ticket from session for this problem
                session_data.pop("jira_ticket_key", None); session_data.pop("assigned_level", None)
                session_data["original_query_context"] = None; session_data["last_bot_response_for_feedback"] = None
                return {"response": f"I'm sorry the previous IT solution wasn't helpful. Your issue (Ticket: **{ticket_key}**) has been routed to our {assigned_to_level_str} team with *{llm_priority_name_for_response}* priority using your email {session_data.get('reporter_email')}. How else can I help?",
                        "links": [], "options": options, "session_id": session_id}
        elif current_mode == "HR":
            response_text = "Apologies for the inconvenience. Would you like to rephrase your question or ask something else related to HR?"
            options_hr_not_helpful = [f"Rephrase my HR question", "Ask another HR question", "Switch to IT Assistant", "No, that's all"]
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": options_hr_not_helpful, "session_id": session_id}
        else:
            return {"response": "I'll try to do better. How else can I help?", "links": [], "options": options, "session_id": session_id}

    if current_mode == "IT" and intent == "provide_email_for_ticket_update" and ticket_key:
        logger.info(f"SID: {session_id} | Intent 'provide_email_for_ticket_update' for ticket {ticket_key}")
        user_email = user_query_from_client
        if not (session_data.get("pending_email_for_ticket_update") == ticket_key and user_email and "@" in user_email and "." in user_email.split("@")[-1]):
            return {"response": "Please provide a valid email address so we can follow up regarding your request.", "links": [], "options": [], "next_action": "expect_email_for_ticket_update", "session_id": session_id}
        session_data.pop("pending_email_for_ticket_update", None)
        add_jira_comment(ticket_key, f"Chatbot (IT): User contact email: {user_email}", is_public=False)
        session_data["reporter_email"] = user_email
        retrieved_assigned_level = session_data.get("assigned_level", "support")
        final_ticket_key_for_message = ticket_key
        session_data.pop("jira_ticket_key", None); session_data.pop("assigned_level", None)
        session_data["original_query_context"] = None; session_data["last_bot_response_for_feedback"] = None
        options = [f"Ask another {current_mode} question", "Switch to HR Assistant", "No, that's all"]
        return {"response":f"Thanks! IT Ticket **{final_ticket_key_for_message}** is now being handled by our {retrieved_assigned_level} staff. We’ll contact you at **{user_email}** if needed. How else can I help?", 
                "links": [], "options": options, "session_id": session_id}

    # --- Determine the actual query to process for RAG/Analysis ---
    query_to_process = user_query_from_client
    simplified_query_to_process = user_query_from_client 
    source_classification = "Internal_Docs" # Default for "stay" or if analysis fails early

    if intent == "stay_in_current_mode":
        mismatched_info = session_data.get("mismatched_query_info")
        if mismatched_info:
            query_to_process = mismatched_info.get("original_query", user_query_from_client)
            simplified_query_to_process = mismatched_info.get("simplified_query", query_to_process)
            logger.info(f"SID: {session_id} | Intent 'stay_in_current_mode'. Processing original mismatched query: '{query_to_process}' in {current_mode} mode.")
            session_data.pop("mismatched_query_info", None)
        else:
            logger.warning(f"SID: {session_id} | 'stay_in_current_mode' intent but no mismatched_query_info found. Processing client query: '{query_to_process}'")
        session_data["original_query_context"] = query_to_process 
    elif not intent: 
        session_data["original_query_context"] = query_to_process
        analysis_prompt = INITIAL_ANALYSIS_PROMPT_TEMPLATE.format(user_query=query_to_process, assistant_mode=current_mode.upper())
        try:
            analysis_response = llm.generate_content(analysis_prompt)
            parsed_analysis = clean_json_response(analysis_response.text)
            if parsed_analysis:
                source_classification = parsed_analysis.get("best_source", "Internal_Docs")
                simplified_query_to_process = parsed_analysis.get("simplified_query_for_search", query_to_process)
            else:
                logger.warning(f"SID: {session_id} | Failed to parse JSON from analysis. Using default for query: '{query_to_process}'")
                simplified_query_to_process = query_to_process
        except Exception as e:
            logger.error(f"SID: {session_id} | Analysis step failed for query '{query_to_process}': {e}", exc_info=True)
            if current_mode == "HR": return {"response": HR_ERROR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": ["Ask another HR question", "Switch to IT Assistant"], "session_id": session_id}
            else: return {"response": f"Sorry, I had trouble understanding that {current_mode} query. Could you rephrase?", "links": [], "options": [f"Rephrase my {current_mode} question", "Switch to HR Assistant"], "session_id": session_id}
    logger.info(f"SID: {session_id} | Processing Query: '{query_to_process}' | Source: {source_classification}, Simplified: '{simplified_query_to_process}'")

    # --- Handle Greetings, OutOfScope, and TopicMismatch (after analysis) ---
    common_options_after_action = [f"Switch to IT Assistant" if current_mode == "HR" else "Switch to HR Assistant", "No thanks"]
    if source_classification == "Greeting":
        response_text = random.choice([f"Hi! This is your {assistant_name}. How can I assist you today?",
                        f"Hello! Need help with something in {current_mode}?",f"Hey there, I’m here to support your {current_mode} queries."])
        if "how are you" in query_to_process.lower() or "how are u" in query_to_process.lower(): response_text = f"Thanks for asking! I’m all set to assist with any {current_mode}-related queries you have."
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": common_options_after_action, "session_id": session_id}

    if source_classification == "OutOfScope":
        response_text = random.choice([f"My apologies, I can only assist with {current_mode}-related matters.", f"That seems outside my current scope as the {assistant_name}."]) + f" Do you have a {current_mode} question?"
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": common_options_after_action, "session_id": session_id}

    if source_classification == "TopicMismatch":
        other_mode = "HR" if current_mode == "IT" else "IT"
        other_assistant_name = "HR Assistant" if current_mode == "IT" else "IT Assistant"
        response_text = f"It appears your query aligns more with {other_mode} topics. You're currently connected to {current_mode} Support. Would you like to switch to the {other_assistant_name}?"
        options = [f"Yes, switch to {other_assistant_name}", f"No, stay with {assistant_name}"]
        session_data["mismatched_query_info"] = {"original_query": query_to_process, "simplified_query": simplified_query_to_process}
        session_data["last_bot_response_for_feedback"] = response_text
        return {"response": response_text, "links": [], "options": options, "session_id": session_id}

    # --- Jira Ticket Creation (IT Mode Only) ---
    if current_mode == "IT" and not ticket_key and source_classification in ["Internal_Docs", "Web_Search_IT"]:
        logger.info(f"SID: {session_id} | New IT query for ticket: '{query_to_process}'. Creating Jira ticket.")
        ticket_result = create_jira_ticket(summary=f"Chatbot IT: {query_to_process[:70]}...", description_text=f"User query (IT Mode): {query_to_process}", reporter_email=session_data.get("reporter_email"))
        if ticket_result.get("success"):
            ticket_key = ticket_result["ticket_key"]; session_data["jira_ticket_key"] = ticket_key
            session_data["assigned_level"] = "L1 (initial)" 
            add_jira_comment(ticket_key, f"Chatbot (IT): Ticket for query: \"{query_to_process}\". Bot attempting to resolve.", is_public=False)
            in_progress_id = JIRA_TRANSITION_ID_IN_PROGRESS or find_transition_id_by_name(ticket_key, ["Start Work", "In Progress", "Work In Progress", "OPEN"])
            if in_progress_id: transition_jira_ticket(ticket_key, in_progress_id)
        else: logger.error(f"SID: {session_id} | Failed to create IT Jira ticket for '{query_to_process}': {ticket_result.get('error')}")
    elif current_mode == "IT" and ticket_key and (not intent or intent != "stay_in_current_mode"):
        add_jira_comment(ticket_key, f"Chatbot (IT): User follow-up: \"{query_to_process}\"", is_public=False)

    # --- RAG Pipeline ---
    context = ""; retrieved_docs_source_type = f"{current_mode} Internal Docs"
    active_retriever = it_retriever if current_mode == "IT" else hr_retriever
    if not active_retriever:
        logger.error(f"SID: {session_id} | {current_mode} retriever is not available.")
        if current_mode == "HR":
            session_data["last_bot_response_for_feedback"] = HR_ERROR_FALLBACK_MESSAGE
            return {"response": HR_ERROR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": [f"Ask another {current_mode} question", "Switch to IT Assistant"], "session_id": session_id}
        else:
            response_text = f"I'm currently unable to search {current_mode} documents. Please try again later."
            if ticket_key: response_text += f" Your query for ticket {ticket_key} is logged."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": [f"Rephrase my {current_mode} question", "Switch to HR Assistant"], "session_id": session_id}

    if source_classification == "Internal_Docs":
        try:
            docs = active_retriever.get_relevant_documents(simplified_query_to_process)
            if docs:
                context_from_docs = "\n\n---\n\n".join([f"Source: {d.metadata.get('source', 'Document')}\n{d.page_content}" for d in docs])
                relevance_prompt_text = RELEVANCE_CHECK_PROMPT_TEMPLATE.format(user_query=query_to_process, simplified_query=simplified_query_to_process, retrieved_context=context_from_docs[:3000])
                rel_check_response = llm.generate_content(relevance_prompt_text)
                if "NO" in rel_check_response.text.strip().upper():
                    context = "";
                    if current_mode == "IT": source_classification = "Web_Search_IT"
                else: context = context_from_docs
            else:
                if current_mode == "IT": source_classification = "Web_Search_IT"
        except Exception as e:
            logger.error(f"SID: {session_id} | Retriever/relevance error for {current_mode} query '{simplified_query_to_process}': {e}", exc_info=True)
            if current_mode == "IT": source_classification = "Web_Search_IT"

    if not context and current_mode == "IT" and source_classification == "Web_Search_IT":
        logger.info(f"SID: {session_id} | Performing web search for IT query: {simplified_query_to_process}")
        context = perform_duckduckgo_search(simplified_query_to_process)
        retrieved_docs_source_type = "Web Search Results"
        if "did not yield specific results" in context or "failed" in context: context = ""

    no_context_options = [f"Rephrase my {current_mode} question","No, that's all"]
    if not context:
        if current_mode == "HR":
            logger.info(f"SID: {session_id} | No context found for HR query '{query_to_process}'. Providing Keka links.")
            session_data["last_bot_response_for_feedback"] = HR_FALLBACK_MESSAGE
            return {"response": HR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": no_context_options, "session_id": session_id}
        elif current_mode == "IT":
            response_text = "I couldn't find specific information for your IT query in my documents or via web search right now."
            if ticket_key: response_text += f" Your IT query has been logged (Ticket: {ticket_key}). An agent may review it if the issue persists."
            else: response_text += " You can try rephrasing or asking a different IT question."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": no_context_options, "session_id": session_id}

    final_prompt_for_llm = RESPONSE_GENERATION_PROMPT_TEMPLATE.format(user_query=query_to_process, source_type_used=retrieved_docs_source_type, context=context)
    try:
        final_response_content = llm.generate_content(final_prompt_for_llm)
        raw_llm_response_text = final_response_content.text
        processed_text_for_display, extracted_links = extract_and_prepare_links(raw_llm_response_text)
        session_data["last_bot_response_for_feedback"] = processed_text_for_display[:500]
        feedback_options = ["👍 Helpful", "👎 Not Helpful", f"Ask another {current_mode} question", "Switch to IT Assistant" if current_mode == "HR" else "Switch to HR Assistant"]
        if current_mode == "IT" and ticket_key: add_jira_comment(ticket_key, f"Chatbot IT response for \"{query_to_process}\":\n{processed_text_for_display[:500]}...", is_public=False)
        return {"response": processed_text_for_display, "links": extracted_links, "options": feedback_options, "session_id": session_id }
    except Exception as e:
        logger.error(f"SID: {session_id} | LLM response generation error for {current_mode} query '{query_to_process}': {e}. Ticket: {ticket_key or 'N/A'}", exc_info=True)
        error_response_options = [f"Rephrase my {current_mode} question", "Switch to IT Assistant" if current_mode == "HR" else "Switch to HR Assistant"]
        if current_mode == "HR":
            session_data["last_bot_response_for_feedback"] = HR_ERROR_FALLBACK_MESSAGE
            return {"response": HR_ERROR_FALLBACK_MESSAGE, "links": HR_KEKA_LINKS, "options": error_response_options, "session_id": session_id}
        else:
            response_text = f"Sorry, I encountered an issue generating an IT response."
            if ticket_key: response_text += f" Your IT query was logged (Ticket: {ticket_key}). Please try rephrasing."
            session_data["last_bot_response_for_feedback"] = response_text
            return {"response": response_text, "links": [], "options": error_response_options, "session_id": session_id}