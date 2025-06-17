import os
import pandas as pd
from dotenv import load_dotenv
import google.generativeai as genai
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader, UnstructuredExcelLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from duckduckgo_search import DDGS
from langchain.docstore.document import Document
import json
import logging
import requests
from bs4 import BeautifulSoup
import re

# --- LOGGER SETUP ---
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "chatbot.log")

def setup_logger(name='chatbot_logger', log_file=LOG_FILE, level=logging.DEBUG):
    os.makedirs(LOG_DIR, exist_ok=True)
    logger_instance = logging.getLogger(name)
    if not logger_instance.handlers:
        logger_instance.setLevel(level)
        fh = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        fh.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        logger_instance.addHandler(fh)
        logger_instance.addHandler(ch)
    return logger_instance

logger = setup_logger()

# --- CONFIGURATION & INITIALIZATION ---
def load_env_vars():
    load_dotenv()
    logger.debug("Environment variables loaded.")

def get_gemini_llm():
    load_env_vars() 
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.critical("GOOGLE_API_KEY not found in environment variables.")
            raise ValueError("GOOGLE_API_KEY not set.")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info("Gemini LLM initialized ('gemini-1.5-flash-latest').")
        return model
    except Exception as e:
        logger.error(f"Error configuring Gemini: {e}", exc_info=True)
        raise

def get_embedding_model(model_name='all-MiniLM-L6-v2'):
    logger.info(f"Initializing embedding model: {model_name}")
    return HuggingFaceEmbeddings(model_name=model_name)

# --- HR SPECIFIC CONFIG ---
HR_KEKA_LINKS = [
    {"text": "View Documents", "url": "https://hoonartek.keka.com/#/org/documents/org/folder/414"} 
]
HR_FALLBACK_MESSAGE = "I couldn't find specific information for your HR query in my documents. You might find these Keka resources helpful:"
HR_ERROR_FALLBACK_MESSAGE = "I'm having a little trouble processing HR requests at the moment. You can try these Keka links or ask again later."

# --- PROMPT TEMPLATES ---
RELEVANCE_CHECK_PROMPT_TEMPLATE = """
Original User Query: "{user_query}"
Simplified Search Query Used: "{simplified_query}"
Retrieved Context Snippet(s) from Internal Documents:
---
{retrieved_context}
---
Based on the "Retrieved Context Snippet(s)", is it highly likely to contain a direct and useful answer to the "Original User Query"?
The context is only relevant if it directly addresses the main subject of the user's query.
Consider if the context is specific enough to be helpful or just vaguely related.
Answer strictly with only "YES" or "NO".
"""

INITIAL_ANALYSIS_PROMPT_TEMPLATE = """
User Query: "{user_query}"
Current Assistant Mode: "{assistant_mode}" # e.g., "IT" or "HR"

Analyze the user query for our L1 {assistant_mode} support chatbot. Your goal is to determine the query's nature.

Consider the following categories:
1.  **Internal Documentation ("Internal_Docs"):**
    *   Query is clearly related to {assistant_mode} and likely answerable by internal {assistant_mode} documents.
    *   Examples for IT: "how to install VPN client", "reset windows password", "software license request".
    *   Examples for HR: "what is the leave policy", "employee benefits inquiry", "requesting a salary slip", "understanding performance review process".

2.  **Web Search for IT Topics ("Web_Search_IT"):** (This source is ONLY for IT Mode)
    *   Query is IT-related but might be too new, specific, or about third-party software not extensively covered internally by IT docs.
    *   If Assistant Mode is HR, this category should NOT be chosen.

3.  **Greeting ("Greeting"):**
    *   Simple social greetings like "hi", "hello", "how are you?".

4.  **Topic Mismatch ("TopicMismatch"):**
    *   Query seems to be about the *other* department's scope.
    *   **If Current Assistant Mode is "IT", but the query is clearly about HR topics.**
        *   HR topics include: employee policies (like **dress code**, leave, work from home), payroll, benefits, recruitment, onboarding, employee relations, performance management, HR system questions (e.g., Keka).
        *   Examples: "what is our company's maternity leave policy?", "questions about my salary slip", "**what is the dress code policy?**", "how to apply for internal job posting?".
    *   **If Current Assistant Mode is "HR", but the query is clearly about IT topics.**
        *   IT topics include: hardware issues (laptop, printer), software problems/requests, network connectivity (VPN, Wi-Fi), password resets, system access, IT security.
        *   Examples: "VPN setup", "software installation error", "printer not working", "my computer is slow".
    *   Be reasonably confident about the mismatch. If unsure, prefer "Internal_Docs" for the current mode UNLESS the query strongly suggests the other department's core responsibilities as listed above.

5.  **Out of Scope ("OutOfScope"):**
    *   Query is clearly not related to either IT or HR support (e.g., "what's the weather?", "capital of France").
    *   Query is gibberish or random characters.

If the source is "Internal_Docs" or "Web_Search_IT", provide a concise version of the query suitable for semantic search.
For "Greeting", "TopicMismatch", or "OutOfScope", the simplified query can be the original query or a note reflecting the category (e.g., "HR query: dress code policy", "greeting").

Output your decision strictly in JSON format like this:
{{
  "best_source": "Internal_Docs" | "Web_Search_IT" | "Greeting" | "TopicMismatch" | "OutOfScope",
  "simplified_query_for_search": "concise version of the query or note"
}}

Example 1 (IT - Internal):
User Query: "How do I reset my Windows password?"
Current Assistant Mode: "IT"
JSON Output: {{ "best_source": "Internal_Docs", "simplified_query_for_search": "reset windows password" }}

Example 2 (Topic Mismatch - HR query in IT mode):
User Query: "What is our company's maternity leave policy?"
Current Assistant Mode: "IT"
JSON Output: {{ "best_source": "TopicMismatch", "simplified_query_for_search": "HR query: maternity leave policy" }}

Example 3 (Topic Mismatch - IT query in HR mode):
User Query: "My laptop screen is flickering."
Current Assistant Mode: "HR"
JSON Output: {{ "best_source": "TopicMismatch", "simplified_query_for_search": "IT query: laptop screen flickering" }}

**Example 4 (Topic Mismatch - HR query 'dress code' in IT mode):**
User Query: "what is the dress code policy"
Current Assistant Mode: "IT"
JSON Output: {{ "best_source": "TopicMismatch", "simplified_query_for_search": "HR query: dress code policy" }}


Now, analyze the User Query and Assistant Mode at the top of this prompt.
"""


RESPONSE_GENERATION_PROMPT_TEMPLATE = """
You are a helpful IT support assistant. Your goal is to provide clear, concise, and actionable answers.
Answer the user's query: "{user_query}"
Based *only* on the following provided context.
**Instructions for Answering:**
1.  **Natural Language:** Formulate your answer in a natural, conversational way. Avoid overly technical jargon unless the query implies a technical user.
2.  **Conciseness:** Get straight to the point. Provide the information the user needs without unnecessary fluff.
3.  **Markdown Formatting:** Use Markdown formatting where appropriate to enhance readability and clarity. This includes:
    *   **Lists:** For sequences of steps or instructions, use bullet points (e.g., `- Item` or `* Item`) or numbered lists (e.g., `1. Item`). Ensure steps are clear and easy to follow.
    *   **Emphasis:** Use bold (`**text**`) or italics (`*text*`) for emphasis where it aids understanding.
    *   **Code Blocks:** If providing code snippets or commands, use Markdown code blocks (e.g., ```python\ncode\n``` or `inline code`).
    *   **Headings:** For longer, structured answers, consider using Markdown headings (`## Heading`) if it improves organization, but use sparingly.
    *   **Link Previews (IMPORTANT!):** If you include an external URL that the user would benefit from visiting (e.g., a support article, documentation), YOU MUST format it for a preview like this: `[PREVIEW](https://example.com/some-article)`. The system will then attempt to fetch the page title to make the link more informative. For any other links where a title preview is not necessary or for internal references, use standard Markdown: `[Visible Text](https://example.com)`.
4.  **Relevance:** If the context contains information relevant to the user's query, synthesize it into a helpful answer.
5.  **Address Specificity (If Applicable):**
    *   If the user asks for a *specific section, notice, or type of document* and the context *does not explicitly contain that exact section title or document type*, clearly state that the specific "notice" or "section" was not found.
    *   However, *crucially*, even if the specific "notice" or "section" is not found, if the context *does* contain general information related to the query, you MUST still provide that available relevant information to the user.
6.  **Handling Insufficient Context:** If the context is genuinely insufficient or contains no relevant information at all, then politely state that you couldn't find specific information for that query.
7.  **No Fabrication:** Do not make up information.
8.  **Source Attribution (Subtle):**
    *   Do NOT explicitly state "This information is from FAQ file X" or "According to SOP Y."
    *   **Citing Web Sources**: If `Context (Source: ...)` indicates "Web Search" and your answer directly uses information from a specific article or support page URL found within that web search context, you **MUST** cite that URL. Use the `[PREVIEW](URL_HERE)` format for this citation.
    *   For internal documents, integrate the information seamlessly.
! important: If there are steps or points make sure that response is formatted in a way that is easy to follow, like using bullet points or numbered lists.
Context (Source: {source_type_used}):
"{context}"
---
Answer:
"""

TICKET_ASSIGNMENT_PROMPT_TEMPLATE = """
You are an AI assistant helping to intelligently route IT support tickets.
Analyze the following IT support query, the chatbot's attempted resolution (if any), and any user feedback.
Based on this information, determine the appropriate assignment level (L1 or L2) and priority (Low, Medium, or High).
**Guidelines for Assignment:**
- **L1 Support:** Handles common, well-documented issues, password resets, basic software troubleshooting (e.g., "how to use X feature"), first-line connectivity problems, and information gathering for more complex issues. Queries that seem straightforward or have known solutions.
- **L2 Support:** Handles complex technical problems, issues requiring administrative access or deeper system knowledge, bugs in software/systems, problems where L1 troubleshooting has likely failed or is insufficient, or issues with broader impact.
- **Priority - High:** User is completely blocked from performing critical work, a system-wide service is down for the user, or a security concern is raised. Significant business impact.
- **Priority - Medium:** User's work is significantly impacted or a core function is impaired, but some workarounds might exist or the issue is not completely blocking all activities.
- **Priority - Low:** Minor issue, inconvenience, request for information that is not time-sensitive, or user can still perform most of their work.
**Input Context:**
User's Original Query: "{user_query}"
Chatbot's Last Response to User: "{chatbot_response}"
User Feedback (if provided, e.g., "Not helpful"): "{user_feedback}"
**Output Instructions:**
Provide your response strictly in JSON format with the following keys:
- "assignment_level": "L1" or "L2"
- "priority": "Low", "Medium", or "High" (Do not use "Urgent" or "Lowest" for now)
- "reasoning": "A brief (1-2 sentences) explanation for your assignment and priority choice."
- "suggested_category": "A brief category for the issue (e.g., 'VPN', 'Password Reset', 'Software Install', 'Hardware Failure', 'Network Connectivity', 'Application Error')."
Example JSON Output:
{{
  "assignment_level": "L1",
  "priority": "Medium",
  "reasoning": "User is unable to connect to VPN. Standard L1 troubleshooting steps for VPN connectivity should be attempted first. Priority is Medium as it likely impacts user's ability to perform some tasks.",
  "suggested_category": "VPN"
}}
Now, analyze the provided input:
User's Original Query: "{user_query}"
Chatbot's Last Response to User: "{chatbot_response}"
User Feedback: "{user_feedback}"
"""

# --- DATA LOADING & PROCESSING (IT) ---
def load_it_faqs(file_path="data/faqs/faq_data.xlsx"):
    docs = []
    logger.info(f"Attempting to load IT FAQs from: {file_path}")
    try:
        df = pd.read_excel(file_path)
        if 'Question' not in df.columns or 'Answer' not in df.columns:
            logger.error("IT FAQ Excel must contain 'Question' and 'Answer' columns.")
            return []
        for _, row in df.iterrows():
            content = f"Question: {row['Question']}\nAnswer: {row['Answer']}"
            metadata = {"doc_type": "faq_it", "source": os.path.basename(file_path)}
            if pd.notna(row.get('ref link')) and row.get('ref link'):
                content += f"\nReference Link: {str(row.get('ref link'))}"
                metadata["reference_link"] = str(row.get('ref link'))
            docs.append(Document(page_content=content, metadata=metadata))
        logger.info(f"Loaded {len(docs)} IT FAQs.")
    except FileNotFoundError: logger.error(f"IT FAQ file not found: {file_path}.")
    except Exception as e: logger.error(f"Error loading IT FAQs: {e}", exc_info=True)
    return docs

def load_it_sops(sops_dir="data/sops/"):
    raw_docs = []
    logger.info(f"Attempting to load IT SOPs from: {sops_dir}")
    if not os.path.exists(sops_dir) or not os.listdir(sops_dir):
        logger.warning(f"IT SOPs directory '{sops_dir}' is empty or does not exist.")
        return []
    for filename in os.listdir(sops_dir):
        file_path = os.path.join(sops_dir, filename)
        loader = None
        try:
            if filename.lower().endswith(".pdf"): loader = PyPDFLoader(file_path)
            elif filename.lower().endswith(".docx"): loader = UnstructuredWordDocumentLoader(file_path)
            if loader:
                loaded_docs = loader.load()
                for doc_content in loaded_docs: # PyPDFLoader returns list of Document objects
                    doc_content.metadata["doc_type"] = "sop_it"
                    doc_content.metadata["source"] = filename
                raw_docs.extend(loaded_docs)
        except Exception as e: logger.error(f"Error loading IT SOP {filename}: {e}", exc_info=True)
    if not raw_docs: return []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    split_docs = text_splitter.split_documents(raw_docs)
    logger.info(f"Loaded and split IT SOPs into {len(split_docs)} chunks.")
    return split_docs

def load_it_documents():
    logger.info("Loading all IT documents.")
    all_docs = load_it_faqs() + load_it_sops()
    if not all_docs: logger.warning("No IT documents loaded.")
    else: logger.info(f"Total IT documents loaded: {len(all_docs)}")
    return all_docs

# --- DATA LOADING & PROCESSING (HR) ---
def load_hr_documents_from_folder(hr_docs_dir="data/hr_documents/"):
    raw_docs = []
    logger.info(f"Attempting to load HR documents from: {hr_docs_dir}")
    if not os.path.exists(hr_docs_dir): logger.warning(f"HR documents directory '{hr_docs_dir}' does not exist."); return []
    if not os.listdir(hr_docs_dir): logger.warning(f"HR documents directory '{hr_docs_dir}' is empty."); return []
    for filename in os.listdir(hr_docs_dir):
        file_path = os.path.join(hr_docs_dir, filename)
        loader = None; doc_type_prefix = "hr_doc"
        try:
            if filename.lower().endswith(".pdf"): loader = PyPDFLoader(file_path); doc_type_prefix = "hr_pdf"
            elif filename.lower().endswith(".docx"): loader = UnstructuredWordDocumentLoader(file_path); doc_type_prefix = "hr_docx"
            elif filename.lower().endswith((".xlsx", ".xls")): loader = UnstructuredExcelLoader(file_path, mode="elements"); doc_type_prefix = "hr_excel"
            if loader:
                loaded_docs = loader.load()
                for doc_content in loaded_docs: 
                    doc_content.metadata["doc_type"] = doc_type_prefix
                    doc_content.metadata["source"] = filename
                raw_docs.extend(loaded_docs)
        except Exception as e: logger.error(f"Error loading HR document {filename}: {e}", exc_info=True)
    if not raw_docs: logger.warning(f"No HR documents successfully loaded from {hr_docs_dir}."); return []
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    split_docs = text_splitter.split_documents(raw_docs)
    logger.info(f"Loaded and split HR documents from '{hr_docs_dir}' into {len(split_docs)} chunks.")
    return split_docs

# --- VECTOR STORE & RETRIEVAL (Generic and Specific) ---
def create_or_load_faiss_index(index_name, docs_loader_func, embedding_model,
                               vector_store_base_path, force_recreate=False):
    os.makedirs(vector_store_base_path, exist_ok=True)
    index_path = os.path.join(vector_store_base_path, index_name)
    if os.path.exists(index_path) and not force_recreate:
        logger.info(f"Loading existing FAISS index from: {index_path}")
        try: return FAISS.load_local(index_path, embedding_model, allow_dangerous_deserialization=True)
        except Exception as e: logger.warning(f"Error loading FAISS index '{index_name}' from {index_path}: {e}. Recreating.", exc_info=True)
    else: logger.info(f"Force recreate is {force_recreate} or index not found at {index_path}. Will attempt to create.")
    logger.info(f"Creating FAISS index: '{index_name}' at {vector_store_base_path}")
    docs = docs_loader_func()
    if not docs: logger.warning(f"No documents for '{index_name}'. Index not created."); return None
    try:
        vector_store = FAISS.from_documents(docs, embedding_model)
        vector_store.save_local(index_path)
        logger.info(f"FAISS index '{index_name}' created and saved to {index_path}.")
        return vector_store
    except Exception as e: logger.error(f"Error creating FAISS index '{index_name}': {e}", exc_info=True); return None

def get_it_retriever(embedding_model, force_recreate=False, k_results=5):
    it_index_name = "faiss_it_combined_index"; it_vector_store_path = "data/vector_store_it"
    vector_store = create_or_load_faiss_index(it_index_name, load_it_documents, embedding_model, it_vector_store_path, force_recreate)
    if vector_store: return vector_store.as_retriever(search_kwargs={"k": k_results})
    logger.warning(f"IT vector store '{it_index_name}' not available."); return None

def get_hr_retriever(embedding_model, force_recreate=False, k_results=3):
    hr_index_name = "faiss_hr_documents_index"; hr_vector_store_path = "data/vector_store_hr"
    vector_store = create_or_load_faiss_index(hr_index_name, load_hr_documents_from_folder, embedding_model, hr_vector_store_path, force_recreate)
    if vector_store: return vector_store.as_retriever(search_kwargs={"k": k_results})
    logger.warning(f"HR vector store '{hr_index_name}' not available."); return None

# --- SEARCH TOOL ---
def perform_duckduckgo_search(query_text: str, max_results: int = 3) -> str:
    logger.info(f"DDG search: '{query_text}' (max_results={max_results})")
    try:
        with DDGS() as ddgs: search_results = list(ddgs.text(query_text, max_results=max_results))
        if not search_results: return "Web search did not yield specific results."
        return "Web Search Results:\n\n" + "\n---\n".join([f"Title: {r.get('title', 'N/A')}\nURL: {r.get('href', 'N/A')}\nSnippet: {r.get('body', 'N/A')}" for r in search_results]).strip()
    except Exception as e: logger.error(f"DDG search error: {e}", exc_info=True); return "Web search failed."

# --- LLM UTILITY ---
def clean_json_response(llm_response_text):
    logger.debug(f"Attempting to clean JSON from LLM response (first 100 chars): '{llm_response_text[:100]}...'")
    try:
        text_to_parse = llm_response_text.strip()
        if text_to_parse.startswith("```json"):
            text_to_parse = text_to_parse[len("```json"):].strip()
            if text_to_parse.endswith("```"): text_to_parse = text_to_parse[:-len("```")].strip()
        elif text_to_parse.startswith("```"):
            text_to_parse = text_to_parse[len("```"):].strip()
            if text_to_parse.endswith("```"): text_to_parse = text_to_parse[:-len("```")].strip()
        json_start = text_to_parse.find("{"); json_end = text_to_parse.rfind("}") + 1
        if json_start != -1 and json_end != 0 and json_end > json_start:
            json_str = text_to_parse[json_start:json_end]
            parsed_json = json.loads(json_str); logger.info(f"Successfully parsed JSON: {parsed_json}"); return parsed_json
        else:
            match = re.search(r'\{.*\}', text_to_parse, re.DOTALL)
            if match:
                json_str = match.group(0)
                try: parsed_json = json.loads(json_str); logger.info(f"Successfully parsed JSON (from regex fallback): {parsed_json}"); return parsed_json
                except json.JSONDecodeError as e_regex: logger.error(f"Error parsing JSON from regex fallback: {e_regex}\nRegex Matched String: {json_str}", exc_info=True)
            logger.error(f"Could not extract valid JSON from: {text_to_parse[:200]}..."); return None
    except Exception as e: logger.error(f"Unexpected error during clean_json_response: {e}", exc_info=True); return None

# --- URL TITLE FETCHER ---
def fetch_url_title(url: str) -> str:
    logger.info(f"Fetching title for URL: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        title_tag = soup.find('title')
        if title_tag and title_tag.string: return title_tag.string.strip()
        h1_tag = soup.find('h1')
        if h1_tag and h1_tag.string: return h1_tag.string.strip()
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"): return og_title["content"].strip()
        return url 
    except requests.exceptions.RequestException as e: logger.error(f"Request error fetching title for {url}: {e}", exc_info=False); return url
    except Exception as e: logger.error(f"Generic error fetching title for {url}: {e}", exc_info=True); return url

# --- LINK EXTRACTION ---
def extract_and_prepare_links(markdown_text: str):
    processed_text = markdown_text; links_data = []
    link_pattern = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
    matches_for_text_replacement = []
    unique_links_by_url: Dict[str, Dict[str, Any]] = {}

    for match in link_pattern.finditer(markdown_text):
        original_markdown_link_text = match.group(1).strip()
        url = match.group(2).strip()
        is_preview_style = (original_markdown_link_text.upper() == "PREVIEW")
        matches_for_text_replacement.append({
            "start": match.start(), "end": match.end(),
            "original_text": original_markdown_link_text,
            "is_preview_style": is_preview_style, "url": url
        })
        if url not in unique_links_by_url:
            unique_links_by_url[url] = {"url": url, "text_options": [original_markdown_link_text], "is_preview_style_option": is_preview_style}
        else:
            unique_links_by_url[url]["text_options"].append(original_markdown_link_text)
            if is_preview_style: unique_links_by_url[url]["is_preview_style_option"] = True
    
    for url, link_details in unique_links_by_url.items():
        title = fetch_url_title(url)
        button_text = "View Link" 
        valid_texts = [t for t in link_details["text_options"] if t and t.upper() != "PREVIEW"]
        if valid_texts: button_text = min(valid_texts, key=len) 
        elif title != url : button_text = title
        links_data.append({"url": url, "text": button_text, "title_preview": title if title != url else url})

    matches_for_text_replacement.sort(key=lambda x: x["start"], reverse=True)
    temp_processed_text_list = list(markdown_text)
    for rep_info in matches_for_text_replacement:
        title_for_placeholder = fetch_url_title(rep_info["url"]) 
        placeholder_text = rep_info["original_text"]
        if not placeholder_text or rep_info["is_preview_style"]:
            if title_for_placeholder != rep_info["url"]: placeholder_text = title_for_placeholder
            else: placeholder_text = "link details" 
        replacement_span = f" ({placeholder_text} - see link below)"
        temp_processed_text_list[rep_info["start"]:rep_info["end"]] = list(replacement_span)
    processed_text = "".join(temp_processed_text_list)
            
    logger.info(f"Extracted links data (v3): {links_data}")
    logger.debug(f"Processed text (links replaced v3): {processed_text[:300]}...")
    return processed_text, links_data