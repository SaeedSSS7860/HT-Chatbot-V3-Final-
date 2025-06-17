
### Get All Service Desks (to find serviceDeskId):

https://saidshaikhnagar.atlassian.net/rest/servicedeskapi/servicedesk


#### Get All Request Types for a Service Desk (to find requestTypeId):
###### (Replace 2 with your actual serviceDeskId)

https://saidshaikhnagar.atlassian.net/rest/servicedeskapi/servicedesk/2/requesttype

##### Create a New Ticket (Customer Request):

https://saidshaikhnagar.atlassian.net/rest/servicedeskapi/request



#### Get All Transitions for a Ticket (to find "Close" transition ID):
##### (Replace ITSSS-8 with your actual issue key)

https://saidshaikhnagar.atlassian.net/rest/api/3/issue/ITSSS-8/transitions

#### To get the request types

https://saidshaikhnagar.atlassian.net/rest/servicedeskapi/servicedesk/2/requesttype



## Tasks

| Task (Changes)                                                                 | Status & Updates |
| ------------------------------------------------------------------------------ | ---------------- |
| Change the chatbot utterances                                                  |                  |
| Add two options: IT Helpdesk and HR Chatbot                                    |                  |
| Create separate conversation journeys for IT Helpdesk and HR                   |                  |
| Store chatbot data in a database (Oracle or MongoDB)                           |                  |
| Change the chatbot logo for both user and bot responses (use SVG)              |                  |
| Remove fallback logic (DuckDuckGo integration)                                 |                  |
| Add fallback message: “Please connect to IT helpdesk via Teams or mail”        |                  |
| Log all chatbot history in JSON format for dashboard purposes                  |                  |
| Design dashboard in UI using HTML and CSS                                      |                  |
| Implement interruption handling (ask if user wants to switch when topics mismatch) |                  |
| Greet user using Emp ID and Name (e.g., “Hi Saeed”)                            |                  |

## To DO list P-1
- Change the chatbot utterances                                                
- Add two options: IT Helpdesk and HR Chatbot   --added done                             
- Create separate conversation journeys for IT Helpdesk and HR --added done (testing remains)
- Implement interruption handling (ask if user wants to switch when topics mismatch) (currently its beign handled by options working on this)

