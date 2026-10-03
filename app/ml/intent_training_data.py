# app/ml/intent_training_data.py

TRAINING_DATA = [
    # create_task
    ("add a task to fix the bug",              "create_task"),
    ("remind me to call dentist",              "create_task"),
    ("i need to submit the report by friday",  "create_task"),
    ("schedule a meeting with the client",     "create_task"),
    ("put review PR on my list",               "create_task"),
    ("new task: prepare slides",               "create_task"),
    ("dont forget to pay rent",                "create_task"),
    ("create task for gym session tomorrow",   "create_task"),

    # complete_task
    ("done with task 3",                       "complete_task"),
    ("i finished task #5",                     "complete_task"),
    ("mark 2 as completed",                    "complete_task"),
    ("completed the report",                   "complete_task"),
    ("close task 7",                           "complete_task"),
    ("task 4 is done",                         "complete_task"),

    # list_tasks
    ("show my tasks",                          "list_tasks"),
    ("what do i have pending",                 "list_tasks"),
    ("list everything",                        "list_tasks"),
    ("whats on my plate today",                "list_tasks"),
    ("show high priority stuff",               "list_tasks"),

    # get_plan
    ("plan my day",                            "get_plan"),
    ("what should i do first",                 "get_plan"),
    ("give me my schedule",                    "get_plan"),
    ("help me prioritize today",               "get_plan"),
    ("what order should i do things",          "get_plan"),

    # task_analytics
    ("how productive have i been",             "task_analytics"),
    ("show my stats",                          "task_analytics"),
    ("how am i doing",                         "task_analytics"),
    ("what is my completion rate",             "task_analytics"),

    # set_priority
    ("set task 3 to high",                     "set_priority"),
    ("change priority of 5 to critical",       "set_priority"),
    ("task 2 should be urgent",                "set_priority"),
    ("make task 1 low priority",               "set_priority"),

    # general_chat
    ("im feeling overwhelmed",                 "general_chat"),
    ("any productivity tips",                  "general_chat"),
    ("how does pomodoro work",                 "general_chat"),
    ("i cant focus today",                     "general_chat"),
    ("thanks",                                 "general_chat"),
    ("what time is it",                        "general_chat"),
]
