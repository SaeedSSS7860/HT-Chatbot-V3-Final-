// static/js/chat.js
document.addEventListener('DOMContentLoaded', () => {
    try {
        let markedInstance = null;
        if (typeof window.marked === 'object' && window.marked !== null && typeof window.marked.parse === 'function') {
            markedInstance = window.marked;
            markedInstance.setOptions({ breaks: true, gfm: true });
            console.log("Marked.js configured successfully.");
        } else {
            console.warn("Marked.js not found. Markdown rendering for main text will be plain.");
        }

        const chatMessages = document.getElementById('chatMessages');
        const messageInput = document.getElementById('messageInput');
        const sendMessageButton = document.getElementById('sendMessageButton');
        const typingIndicator = document.getElementById('typingIndicator');
        const initialBotTimeElement = document.getElementById('initialBotTime');
        const chatHeaderTitle = document.getElementById('chatHeaderTitle');

        if (!chatMessages || !messageInput || !sendMessageButton || !typingIndicator || !initialBotTimeElement || !chatHeaderTitle) {
            console.error("One or more critical chat UI elements not found! Aborting chat.js initialization.");
            if (chatMessages) {
                const errorDiv = document.createElement('div');
                errorDiv.innerHTML = '<p style="color: red; padding: 10px;">Chat interface could not load correctly. Please refresh.</p>';
                chatMessages.appendChild(errorDiv);
            }
            return;
        }
        
        if (initialBotTimeElement) {
            initialBotTimeElement.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        let currentSessionId = null;
        let expectingEmailForTicketUpdate = false;
        let currentAssistantMode = null;

        function generateSessionId() {
            return window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).substring(2);
        }

        function ensureSessionId() {
            if (!currentSessionId) {
                currentSessionId = generateSessionId();
                console.log("New chat session started with ID:", currentSessionId);
            }
            return currentSessionId;
        }

        function showTypingIndicator() {
            if (typingIndicator) typingIndicator.classList.remove('hidden');
            if (chatMessages) chatMessages.scrollTop = chatMessages.scrollHeight;
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
                svgIcon.classList.add('w-5', 'h-5');
                svgIcon.setAttribute('fill', 'none'); svgIcon.setAttribute('viewBox', '0 0 24 24');
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
            if (markedInstance) messageTextDiv.innerHTML = markedInstance.parse(message);
            else { const p = document.createElement('p'); p.textContent = message; messageTextDiv.appendChild(p); }
            messageBubble.appendChild(messageTextDiv);
            messageContentWrapper.appendChild(messageBubble);

            if (links && links.length > 0) {
                const linkButtonContainer = document.createElement('div');
                linkButtonContainer.classList.add('link-button-container', isUserMessage ? 'user-message-links' : 'bot-message-links');
                links.forEach(linkInfo => { 
                    const linkButton = document.createElement('a');
                    linkButton.href = linkInfo.url;
                    linkButton.textContent = linkInfo.text || "View Source";
                    linkButton.classList.add('chat-link-button');
                    linkButton.target = "_blank"; linkButton.rel = "noopener noreferrer";
                    const tooltip = document.createElement('span');
                    tooltip.classList.add('link-tooltip');
                    tooltip.textContent = linkInfo.title_preview || linkInfo.url;
                    linkButton.appendChild(tooltip);
                    linkButtonContainer.appendChild(linkButton);
                });
                messageContentWrapper.appendChild(linkButtonContainer);
            }

            if (!isUserMessage && options && options.length > 0) {
                const optionsContainer = document.createElement('div');
                optionsContainer.classList.add('mt-2', 'space-x-2', 'flex', 'flex-wrap', 'gap-y-2');
                options.forEach(optionText => {
                    const button = document.createElement('button');
                    button.classList.add(
                        'px-3', 'py-1.5', 'text-sm', 'rounded-full', 
                        'bg-blue-100', 'text-blue-700', // Consistent light blue
                        'hover:bg-blue-200', 'transition-colors', 
                        'quick-reply-button'
                    );
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

            messageWrapper.appendChild(avatarDiv);
            messageWrapper.appendChild(messageContentWrapper);
            if (typingIndicator) chatMessages.insertBefore(messageWrapper, typingIndicator);
            else chatMessages.appendChild(messageWrapper);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }

        async function handleSendMessage(messageOverride = null, intentOverride = null) {
            let messageText = messageOverride || (messageInput ? messageInput.value.trim() : '');
            let queryToSend = (messageText === null || messageText === undefined) ? '' : messageText;

            if (!queryToSend && !intentOverride) {
                 // Allow sending if it's the very first interaction and no mode is set (backend will prompt for mode)
                 // Or if initialModeSelectionContainer still exists (meaning user hasn't picked a mode yet)
                 if (currentAssistantMode || !document.getElementById('initialModeSelectionContainer')) {
                    return; 
                 }
            }

            const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            
            // Add user message to UI only if it's a newly typed message.
            // Quick reply clicks that represent user choices are added in the click event listener.
            if (!messageOverride && messageInput && queryToSend && !expectingEmailForTicketUpdate) {
                addMessageToChat(queryToSend, true, currentTime);
            }
            
            if (messageInput && !messageOverride && !expectingEmailForTicketUpdate) {
                messageInput.value = '';
            }

            showTypingIndicator();
            const sessionIdToSend = ensureSessionId();
            
            let payload = { user_query: queryToSend, session_id: sessionIdToSend, intent: intentOverride };

            if (expectingEmailForTicketUpdate) {
                payload.intent = "provide_email_for_ticket_update";
                payload.user_query = queryToSend; 
                expectingEmailForTicketUpdate = false;
                if (messageInput) messageInput.value = ''; 
            }
            console.log("Sending payload to /chat:", JSON.stringify(payload));
            try {
                const res = await fetch("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
                const botResponseTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                if (!res.ok) {
                    const errorData = await res.json().catch(() => ({ response: "Sorry, an error occurred." }));
                    addMessageToChat(errorData.response || "Sorry, an unexpected error.", false, botResponseTime, [], ["Rephrase my question"]);
                    hideTypingIndicator(); return;
                }
                const data = await res.json(); console.log("Received data from /chat:", data);

                if (data.mode_selected) {
                    currentAssistantMode = data.mode_selected;
                    if (chatHeaderTitle) chatHeaderTitle.textContent = `${currentAssistantMode} Assistant`;
                    if (messageInput) messageInput.placeholder = `Ask your ${currentAssistantMode} question...`;
                    console.log("Assistant mode confirmed by backend:", currentAssistantMode);
                }

                addMessageToChat(data.response, false, botResponseTime, data.links || [], data.options || []);

                if (data.session_id === null) {
                    console.log("Backend signaled to end session."); currentSessionId = null; currentAssistantMode = null;
                    if (chatHeaderTitle) chatHeaderTitle.textContent = "AI Support Assistant";
                    if (messageInput) messageInput.placeholder = "Session ended. Select a department to start.";
                } else if (data.session_id) { currentSessionId = data.session_id; }

                if (data.next_action === "expect_email_for_ticket_update") {
                    expectingEmailForTicketUpdate = true;
                    if (messageInput) { messageInput.placeholder = "Please enter your email..."; messageInput.focus(); }
                } else if (currentAssistantMode) {
                    if (messageInput) messageInput.placeholder = `Ask your ${currentAssistantMode} question...`;
                } else {
                    if (messageInput) messageInput.placeholder = "Select a department or type message...";
                }
            } catch (error) {
                console.error("Fetch error:", error); hideTypingIndicator();
                const botErrorTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                addMessageToChat("Connection error. Please try again.", false, botErrorTime, [], ["Rephrase my question"]);
            }
        }

        if (chatMessages) {
            chatMessages.addEventListener('click', async function(event) {
                const clickedButton = event.target.closest('button.quick-reply-button');
                if (clickedButton) {
                    const actionText = clickedButton.textContent;
                    const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const buttonContainer = clickedButton.parentElement;
                    let removeButtonContainerAfterProcessing = true;
                    let intentForBackend = null;
                    let frontendOnlyReply = null;
                    let needsInputFromUser = false;
                    let queryForBackend = null; 
                    let echoClickAsUserMessage = true;

                    if (actionText === "IT Assistant" || actionText === "HR Assistant") {
                        const initialModeContainer = document.getElementById('initialModeSelectionContainer');
                        if (initialModeContainer && initialModeContainer.contains(clickedButton)) {
                            echoClickAsUserMessage = false; 
                            initialModeContainer.remove(); 
                            removeButtonContainerAfterProcessing = false;
                        }
                        intentForBackend = (actionText === "IT Assistant") ? "select_mode_it" : "select_mode_hr";
                    } else if (actionText === "Yes, switch to IT Assistant" || actionText === "Switch to IT Assistant") {
                        intentForBackend = "select_mode_it";
                        // For "Switch to...", don't echo. For "Yes, switch to...", do echo.
                        echoClickAsUserMessage = (actionText === "Yes, switch to IT Assistant");
                    } else if (actionText === "Yes, switch to HR Assistant" || actionText === "Switch to HR Assistant") {
                        intentForBackend = "select_mode_hr";
                        echoClickAsUserMessage = (actionText === "Yes, switch to HR Assistant");
                    } else if (actionText.startsWith("No, stay with")) {
                        intentForBackend = "stay_in_current_mode";
                        // echoClickAsUserMessage remains true (default)
                    } else if (actionText === "👍 Helpful") {
                        intentForBackend = "user_feedback_helpful";
                        queryForBackend = actionText; 
                        // echoClickAsUserMessage remains true
                    } else if (actionText === "👎 Not Helpful") {
                        intentForBackend = "user_feedback_not_helpful";
                        queryForBackend = actionText;
                        // echoClickAsUserMessage remains true
                    } else if (actionText === "Ask an IT question" || actionText === "Ask another IT question") {
                        intentForBackend = "select_mode_it";
                        // echoClickAsUserMessage remains true
                    } else if (actionText === "Ask an HR question" || actionText === "Ask another HR question") {
                        intentForBackend = "select_mode_hr";
                        // echoClickAsUserMessage remains true
                    } else if (actionText === "Rephrase my question" || actionText.startsWith("Rephrase my")) {
                        frontendOnlyReply = "Okay, please rephrase your question."; needsInputFromUser = true; expectingEmailForTicketUpdate = false;
                        // echoClickAsUserMessage remains true
                    } else if (actionText === "No, I'm good" || actionText === "No, that's all" || actionText === "No thanks") {
                        frontendOnlyReply = "Alright! Have a great day."; currentSessionId = null; currentAssistantMode = null;
                        if (chatHeaderTitle) chatHeaderTitle.textContent = "AI Support Assistant";
                        if (messageInput) messageInput.placeholder = "Session ended. Select a department.";
                        expectingEmailForTicketUpdate = false;
                        // echoClickAsUserMessage remains true
                    } else { 
                        echoClickAsUserMessage = true; 
                        intentForBackend = null; 
                        queryForBackend = actionText; 
                    }

                    if (echoClickAsUserMessage) {
                        addMessageToChat(actionText, true, currentTime);
                    }

                    if (buttonContainer && removeButtonContainerAfterProcessing) buttonContainer.remove();

                    if (intentForBackend || queryForBackend !== null) {
                        await handleSendMessage(queryForBackend, intentForBackend);
                    } else if (frontendOnlyReply) {
                        hideTypingIndicator();
                        setTimeout(() => {
                            const botRTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                            addMessageToChat(frontendOnlyReply, false, botRTime, [], []);
                            if (needsInputFromUser && messageInput) {
                                messageInput.focus();
                                if (currentAssistantMode) messageInput.placeholder = `Rephrase your ${currentAssistantMode} question...`;
                                else messageInput.placeholder = "Type your message...";
                            }
                        }, 300);
                    }
                }
            });
        }

        if (sendMessageButton && messageInput) {
            sendMessageButton.addEventListener('click', () => handleSendMessage(null, null));
            messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(null, null); }
            });
        }
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