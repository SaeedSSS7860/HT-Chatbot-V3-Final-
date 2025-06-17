// static/js/chat.js
document.addEventListener('DOMContentLoaded', () => {
    try {
        let markedInstance = null;
        if (typeof window.marked === 'object' && window.marked !== null && typeof window.marked.parse === 'function') {
            markedInstance = window.marked;
            markedInstance.setOptions({ breaks: true, gfm: true });
            console.log("Marked.js configured with breaks: true");
        } else {
            console.warn("Marked.js not found.");
        }

        const chatMessages = document.getElementById('chatMessages');
        const messageInput = document.getElementById('messageInput');
        const sendMessageButton = document.getElementById('sendMessageButton');
        const originalTypingIndicator = document.getElementById('typingIndicator');
        let typingIndicator = originalTypingIndicator;
        const chatHeaderTitle = document.getElementById('chatHeaderTitle');

        if (!chatMessages || !messageInput || !sendMessageButton || !originalTypingIndicator || !chatHeaderTitle) {
            console.error("One or more critical chat UI elements not found!"); return;
        }

        let currentSessionId = null;
        let expectingEmailForTicketUpdate = false;
        let currentAssistantMode = null;
        let expectingEmployeeId = true;
        let echoClickAsUserMessageForNextSend = false;


        function showTypingIndicator() {
            if (typingIndicator) {
                typingIndicator.classList.remove('hidden');
                if (chatMessages.contains(typingIndicator) && chatMessages.lastChild !== typingIndicator) {
                    chatMessages.appendChild(typingIndicator);
                } else if (!chatMessages.contains(typingIndicator)) {
                    chatMessages.appendChild(typingIndicator);
                }
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }
        function hideTypingIndicator() {
            if (typingIndicator) typingIndicator.classList.add('hidden');
        }

        function addMessageToChat(message, isUserMessage, time, links = [], options = []) {
            hideTypingIndicator();
            if (!chatMessages) return;

            const messageWrapper = document.createElement('div');
            messageWrapper.classList.add('flex', 'items-start', 'mb-4');
            if (isUserMessage) messageWrapper.classList.add('justify-end');

            const avatarDiv = document.createElement('div');
            avatarDiv.classList.add('w-8', 'h-8', 'rounded-full', 'flex', 'items-center', 'justify-center', 'flex-shrink-0');
            let avatarContent;
            if (isUserMessage) {
                avatarDiv.classList.add('bg-gray-300', 'text-gray-600', 'ml-2', 'order-2');
                const svgIcon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svgIcon.classList.add('w-5', 'h-5'); svgIcon.setAttribute('fill', 'none'); svgIcon.setAttribute('viewBox', '0 0 24 24');
                svgIcon.setAttribute('stroke-width', '1.5'); svgIcon.setAttribute('stroke', 'currentColor');
                const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round');
                path.setAttribute('d', 'M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z');
                svgIcon.appendChild(path); avatarContent = svgIcon;
            } else {
                avatarDiv.classList.add('bg-transparent', 'mr-2', 'order-1');
                const imgLogo = document.createElement('img');
                imgLogo.src = '/static/images/bot_avatar_logo.svg'; imgLogo.alt = 'Bot Avatar';
                imgLogo.classList.add('w-full', 'h-full', 'object-contain'); avatarContent = imgLogo;
            }
            avatarDiv.appendChild(avatarContent);

            const messageContentWrapper = document.createElement('div');
            messageContentWrapper.classList.add(isUserMessage ? 'order-1' : 'order-2');
            const messageBubble = document.createElement('div');
            messageBubble.classList.add('p-3', 'rounded-lg', 'shadow', 'max-w-xs', 'md:max-w-md');
            const messageTextDiv = document.createElement('div');
            const proseBaseClasses = ['prose', 'prose-sm', 'message-bubble-content'];
            if (isUserMessage) {
                messageBubble.classList.add('bg-blue-500', 'text-white', 'rounded-tr-none');
                messageTextDiv.classList.add(...proseBaseClasses, 'prose-invert');
            } else {
                messageBubble.classList.add('bg-gray-200', 'text-gray-800', 'rounded-tl-none');
                messageTextDiv.classList.add(...proseBaseClasses);
            }

            if (markedInstance) {
                messageTextDiv.innerHTML = markedInstance.parse(message);
            } else {
                messageTextDiv.innerHTML = message.replace(/\n/g, '<br>');
            }
            messageBubble.appendChild(messageTextDiv);
            messageContentWrapper.appendChild(messageBubble);

            if (links && links.length > 0) {
                const linkButtonContainer = document.createElement('div');
                linkButtonContainer.classList.add('link-button-container', isUserMessage ? 'user-message-links' : 'bot-message-links');
                links.forEach(linkInfo => {
                    const linkButton = document.createElement('a');
                    linkButton.href = linkInfo.url; linkButton.textContent = linkInfo.text || "View Source";
                    linkButton.classList.add('chat-link-button');
                    linkButton.target = "_blank"; linkButton.rel = "noopener noreferrer";
                    const tooltip = document.createElement('span');
                    tooltip.classList.add('link-tooltip'); tooltip.textContent = linkInfo.title_preview || linkInfo.url;
                    linkButton.appendChild(tooltip); linkButtonContainer.appendChild(linkButton);
                });
                messageContentWrapper.appendChild(linkButtonContainer);
            }

            if (!isUserMessage && options && options.length > 0) {
                const optionsContainer = document.createElement('div');
                optionsContainer.classList.add('mt-2', 'space-x-2', 'flex', 'flex-wrap', 'gap-y-2');
                options.forEach(optionText => {
                    const button = document.createElement('button');
                    button.classList.add('px-3', 'py-1.5', 'text-sm', 'rounded-full', 'bg-blue-100', 'text-blue-700', 'hover:bg-blue-200', 'transition-colors', 'quick-reply-button');
                    button.textContent = optionText;
                    optionsContainer.appendChild(button);
                });
                messageContentWrapper.appendChild(optionsContainer);
            }

            const timeText = document.createElement('p');
            timeText.classList.add('text-xs', 'text-gray-500', 'mt-1', isUserMessage ? 'mr-1' : 'ml-1');
            if(isUserMessage) timeText.classList.add('text-right');
            timeText.textContent = time;
            messageContentWrapper.appendChild(timeText);
            messageWrapper.appendChild(avatarDiv); messageWrapper.appendChild(messageContentWrapper);

            const initialPlaceholder = document.getElementById('initialBotMessagePlaceholder');
            if(initialPlaceholder && chatMessages.contains(initialPlaceholder) && !isUserMessage){
                initialPlaceholder.remove();
            }

            if (typingIndicator && chatMessages.contains(typingIndicator)) {
                 chatMessages.insertBefore(messageWrapper, typingIndicator);
            } else {
                 chatMessages.appendChild(messageWrapper);
            }
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        async function initialBotFlow() {
            showTypingIndicator();
            try {
                const res = await fetch("/chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_query: "", session_id: currentSessionId, intent: null })
                });
                const botResponseTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                if (!res.ok) {
                    hideTypingIndicator();
                    const errorData = await res.json().catch(() => ({ response: "Error connecting to assistant." }));
                    addMessageToChat(errorData.response || "Could not initialize chat session.", false, botResponseTime); return;
                }
                const data = await res.json();
                console.log("Received initial data from /chat:", data);

                const initialPlaceholder = document.getElementById('initialBotMessagePlaceholder');
                if (initialPlaceholder && chatMessages.contains(initialPlaceholder)) initialPlaceholder.remove();

                addMessageToChat(data.response, false, botResponseTime, data.links || [], data.options || []);

                if (data.session_id) currentSessionId = data.session_id;

                if (data.next_action === "expect_employee_id") {
                    expectingEmployeeId = true;
                    if (messageInput) messageInput.placeholder = "Enter your Employee ID...";
                    if (chatHeaderTitle) chatHeaderTitle.textContent = "AI Support Assistant";
                    currentAssistantMode = null;
                } else {
                     expectingEmployeeId = false;
                }

            } catch (error) {
                hideTypingIndicator();
                console.error("Fetch error on initial flow:", error);
                addMessageToChat("Connection error. Please try refreshing the page.", false, new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
            }
        }

        async function handleSendMessage(messageOverride = null, intentOverride = null) {
            let messageText = messageOverride || (messageInput ? messageInput.value.trim() : '');
            let queryToSend = (messageText === null || messageText === undefined) ? '' : messageText;

            // Allow empty query if an intent is present that doesn't require a query (e.g. init type intents)
            if (!queryToSend && !intentOverride && !expectingEmailForTicketUpdate) {
                 if (expectingEmployeeId && !queryToSend) return; // Waiting for ID input
                 if (!expectingEmployeeId && currentAssistantMode && !queryToSend &&
                     intentOverride !== "ask_another_question_init" &&
                     intentOverride !== "rephrase_question_init" &&
                     intentOverride !== "continue_with_current_mode") return; // Need query unless specific init intent
                 if (!expectingEmployeeId && !currentAssistantMode && !queryToSend) return; // No mode selected yet
            }
            const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            if (echoClickAsUserMessageForNextSend && queryToSend) {
                addMessageToChat(queryToSend, true, currentTime);
            } else if (!messageOverride && messageInput && queryToSend && !expectingEmailForTicketUpdate) { // Standard typed message
                addMessageToChat(queryToSend, true, currentTime);
            }
            echoClickAsUserMessageForNextSend = false; // Reset flag

            if (messageInput && !messageOverride) { messageInput.value = ''; }

            showTypingIndicator();

            let payload = { user_query: queryToSend, session_id: currentSessionId, intent: intentOverride };

            // This logic is tricky. If expecting email, the typed text IS the email.
            // The intent should be set by the send button/enter key press for email.
            if (expectingEmailForTicketUpdate && intentOverride !== "provide_email_for_ticket_update") {
                // This case means user typed something while email was expected, but didn't click a button
                // So, the typed text is the email query, and intent should be provide_email
                payload.intent = "provide_email_for_ticket_update";
                // The user's typed email would have been added above if not a messageOverride
            }


            console.log("Sending payload to /chat:", JSON.stringify(payload));
            try {
                const res = await fetch("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                const botResponseTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

                let data;
                try {
                    data = await res.json();
                } catch (e) {
                    hideTypingIndicator();
                    const rawErrorText = await res.text().catch(() => "Unknown server error response.");
                    console.error("Failed to parse JSON from server response. Status:", res.status, "Raw:", rawErrorText);
                    addMessageToChat(`Error processing server response. (Status: ${res.status})`, false, botResponseTime);
                    return;
                }

                if (!res.ok) {
                    hideTypingIndicator();
                    addMessageToChat(data.response || "Sorry, an unexpected error occurred.", false, botResponseTime, data.links || [], data.options || []);
                    return;
                }

                addMessageToChat(data.response, false, botResponseTime, data.links || [], data.options || []);

                // Handle full session reset (e.g. for an explicit "reset_session_for_new_employee" intent)
                if (data.session_id === null && data.next_action === "expect_employee_id") {
                    console.log("Backend signaled to end/reset session fully. Resetting client.");
                    currentSessionId = null;
                    currentAssistantMode = null;
                    expectingEmployeeId = true;
                    expectingEmailForTicketUpdate = false;

                    if (chatHeaderTitle) chatHeaderTitle.textContent = "AI Support Assistant";

                    chatMessages.innerHTML = '';
                    if (originalTypingIndicator) {
                        typingIndicator = originalTypingIndicator.cloneNode(true);
                        typingIndicator.classList.add('hidden');
                        chatMessages.appendChild(typingIndicator);
                    }
                    await initialBotFlow(); // This fetches the "Dear User, Welcome..."
                    return; // Stop further processing for this old session
                } else if (data.session_id) {
                    currentSessionId = data.session_id;
                }


                if (data.next_action !== "expect_email_for_ticket_update") {
                    expectingEmailForTicketUpdate = false;
                }

                // Update UI based on backend's next_action or mode_selected
                if (data.next_action === "expect_employee_id") {
                    expectingEmployeeId = true; currentAssistantMode = null;
                    if (chatHeaderTitle) chatHeaderTitle.textContent = "AI Support Assistant";
                    if (messageInput) messageInput.placeholder = "Enter your Employee ID...";
                } else if (data.next_action === "expect_mode_selection") {
                    expectingEmployeeId = false; currentAssistantMode = null;
                    if (messageInput) messageInput.placeholder = "Select IT or HR Related...";
                } else if (data.next_action === "paused_wait_for_greeting_or_query") {
                    expectingEmployeeId = false; // ID is known
                    // currentAssistantMode remains as is, or could be null if user said No Thank You before mode selection
                    if (messageInput) messageInput.placeholder = currentAssistantMode ? `Ask your ${currentAssistantMode} question or type 'Hi'` : "Type 'Hi' or select a department";
                } else if (data.mode_selected) {
                    expectingEmployeeId = false; currentAssistantMode = data.mode_selected;
                    if (chatHeaderTitle) chatHeaderTitle.textContent = `${currentAssistantMode} Assistant`;
                    if (messageInput) messageInput.placeholder = `Ask your ${currentAssistantMode} question...`;
                } else { // Fallback placeholder logic if no specific next_action
                    if (expectingEmployeeId) {
                        if (messageInput) messageInput.placeholder = "Enter your Employee ID...";
                    } else if (!currentAssistantMode && !expectingEmailForTicketUpdate) { // ID verified, but no mode yet
                        if (messageInput) messageInput.placeholder = "Select IT or HR Related...";
                    } else if (currentAssistantMode && !expectingEmailForTicketUpdate) {
                        if (messageInput) messageInput.placeholder = `Ask your ${currentAssistantMode} question...`;
                    } else if (!expectingEmailForTicketUpdate) { // General fallback
                         if (messageInput) messageInput.placeholder = "Type your message...";
                    }
                }

                if (data.next_action === "expect_email_for_ticket_update") {
                    expectingEmailForTicketUpdate = true;
                    if (messageInput) { messageInput.placeholder = "Please enter your email..."; messageInput.focus(); }
                }

            } catch (error) {
                hideTypingIndicator();
                console.error("Fetch error in handleSendMessage:", error);
                addMessageToChat("Connection error during message send. Please try again.", false, new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), [], ["Rephrase my question"]);
            }
        }


        if (chatMessages) {
            chatMessages.addEventListener('click', async function(event) {
                const clickedButton = event.target.closest('button.quick-reply-button');
                if (clickedButton) {
                    const actionText = clickedButton.textContent;
                    const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const buttonContainer = clickedButton.parentElement;

                    let intentForBackend = null;
                    let queryForBackend = ""; // Default to empty
                    echoClickAsUserMessageForNextSend = true; // Default to echo button text

                    if (expectingEmployeeId) { return; }

                    if (actionText === "IT Related") {
                        intentForBackend = "select_mode_it";
                        echoClickAsUserMessageForNextSend = false; // Backend gives confirm message
                    } else if (actionText === "HR Related") {
                        intentForBackend = "select_mode_hr";
                        echoClickAsUserMessageForNextSend = false; // Backend gives confirm message
                    } else if (actionText === "Yes, I need assistance with something else" || actionText.startsWith("Ask another ")) {
                        intentForBackend = "ask_another_question_init";
                        queryForBackend = actionText; // Echo this phrase
                    } else if (actionText.startsWith("Rephrase my ") && actionText.endsWith(" question")) {
                        intentForBackend = "rephrase_question_init";
                        queryForBackend = actionText; // Echo this phrase
                    } else if (actionText.startsWith("Switch to")) {
                        if (actionText.includes("IT Assistant")) intentForBackend = "select_mode_it";
                        else if (actionText.includes("HR Assistant")) intentForBackend = "select_mode_hr";
                        queryForBackend = actionText; // Echo "Switch to..."
                    } else if (actionText.startsWith("Yes, switch to")) {
                        if (actionText.includes("IT Assistant")) intentForBackend = "select_mode_it";
                        else if (actionText.includes("HR Assistant")) intentForBackend = "select_mode_hr";
                        queryForBackend = actionText;
                    } else if (actionText.startsWith("No, stay with")) {
                        intentForBackend = "stay_in_current_mode";
                        queryForBackend = actionText;
                    } else if (actionText.startsWith("Continue with ")) {
                        intentForBackend = "continue_with_current_mode";
                        queryForBackend = actionText;
                    } else if (actionText === "No, Thank you.") {
                        intentForBackend = "user_said_no_thank_you"; // For pause, not full reset
                        queryForBackend = actionText;
                    } else if (actionText === "👍 Helpful") {
                        intentForBackend = "user_feedback_helpful";
                        queryForBackend = actionText;
                    } else if (actionText === "👎 Not Helpful") {
                        intentForBackend = "user_feedback_not_helpful";
                        queryForBackend = actionText;
                    } else { // Any other button text is treated as a direct query
                        intentForBackend = null;
                        queryForBackend = actionText;
                    }

                    if (buttonContainer) {
                        buttonContainer.remove();
                    }
                    // `queryForBackend` will be used by handleSendMessage if echoClickAsUserMessageForNextSend is true
                    await handleSendMessage(queryForBackend, intentForBackend);
                }
            });
        }

        if (sendMessageButton && messageInput) {
            sendMessageButton.addEventListener('click', () => {
                echoClickAsUserMessageForNextSend = false; // Typed messages are not from "echoed" clicks
                handleSendMessage(null, null);
            });
            messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    echoClickAsUserMessageForNextSend = false;
                    handleSendMessage(null, null);
                }
            });
         }
        initialBotFlow();
    } catch (e) {
        console.error("Critical error in chat.js:", e);
        const chatMessagesDiv = document.getElementById('chatMessages');
        if (chatMessagesDiv) {
            const errorMsg = document.createElement('p');
            errorMsg.textContent = "A critical error occurred with the chat interface. Please refresh the page.";
            errorMsg.style.color = 'red'; errorMsg.style.padding = '10px';
            chatMessagesDiv.appendChild(errorMsg);
        }
    }
});