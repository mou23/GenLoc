import os
import json
import logging
import threading
from openai_client_manager import OpenAIClientManager
from file_data_processor import FileDataProcessor

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": "Check if a Java file with a given name exists in the codebase. Useful when inferring filenames from bug report keywords or discovering filenames by examining a method body. Returns the filepath if found.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Inferred filename to search (e.g., Person.java)"
                    }
                },
                "required": ["filename"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_method",
            "description": "Locate all Java files that define a method with the given name. Useful when the bug report or method body references a specific method. Returns a list of filepaths.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "method_name": {
                        "type": "string",
                        "description": "The name of the method to search for (e.g., updatePersonDetails)"
                    }
                },
                "required": ["method_name"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_candidate_files",
            "description": "Retrieve 50 filepaths from the codebase that may be relevant. Useful when no strong inference can be made from the bug report.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_method_signatures_of_a_file",
            "description": "Retrieve all method signatures from a Java file. Useful for inspecting the file's high-level structure, determining relevance to the bug report and identifying methods of interest.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "The path of the file to inspect."
                    }
                },
                "required": ["filepath"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_method_body",
            "description": "Retrieve the implementation body of a specified method from a Java file. Useful for analyzing the logic of a method of interest to assess its alignment with the bug report's symptoms.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "The path of the file that contains the method."
                    },
                    "method_signature": {
                        "type": "string",
                        "description": "The exact signature of the method whose body should be returned."
                    }
                },
                "required": ["filepath", "method_signature"],
                "additionalProperties": False
            }
        }
    }
]



class BugReportProcessor:
    _dir_creation_lock = threading.Lock()
    def __init__(self, project, bug_id, bug_report_summary, bug_report_description):
        if not all([project, bug_id, bug_report_summary, bug_report_description]):
            raise ValueError("All parameters must be non-empty")
        self.project = project
        self.bug_id = bug_id
        self.bug_report_summary = bug_report_summary
        self.bug_report_description = bug_report_description
        self.file_data_processor = FileDataProcessor(self.project, self.bug_id)
        self.openai_client_manager = OpenAIClientManager()
        
        self.project_log_dir = os.path.join(os.getcwd(), self.project)
        with BugReportProcessor._dir_creation_lock:
            os.makedirs(self.project_log_dir, exist_ok=True)

        self.logger = logging.getLogger(f"bug_{bug_id}")
        if not self.logger.handlers:
            log_file = os.path.join(self.project_log_dir, f"bug_{bug_id}_log.txt")
            file_handler = logging.FileHandler(log_file)
            formatter = logging.Formatter('%(asctime)s - %(message)s')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
            self.logger.setLevel(logging.INFO)

    def create_prompt(self):
        prompt = f"""
Given a bug report, your goal is to analyze and rank files by their likelihood of containing the bug. 

Bug Report Summary:
{self.bug_report_summary}

Bug Report Description:
{self.bug_report_description}
"""
        clean_string = prompt.encode('utf-8', 'ignore').decode()
        # print(clean_string)
        # print("**********************************************************************")
        return clean_string
    
    def rank_files(self):
        system_content = """You are an expert software engineer specializing in bug localization. Your goal is to identify the most probable buggy Java files based on a given bug report. You have access to five functions that help you search for file names, locate methods and analyze source code. You must follow an iterative, reasoning-based approach, refining your strategy dynamically based on insights gathered during each step.

At each iteration, you should:
- Maintain a working shortlist of files that appear potentially buggy.
- Update the shortlist based on new evidence (e.g., method matches, code analysis).
- Avoid redundant operations—do not recheck the same filenames, methods or file contents multiple times.

Continue this process until you either: (a) Produce a well-justified ranked list of the 10 most relevant files, or (b) Reach the maximum limit of 10 iterations. In the 10th iteration, you must output your final ranked list.

Workflow
1. Analyze the Bug Report:
- Extract relevant keywords, error messages and functional hints from the bug summary and description.
- Identify potentially affected components (e.g., UI, database, networking).

2. File Discovery:
- Use `search_file()` to check if filenames derived from the bug report's keywords or functionality exist in the codebase.
- If the bug report references a specific method name, use `search_method()` to find all files defining it.
- If an inferred filename or method location does not exist, refine your strategy: adjust assumptions, explore variations and retry.
- If strong matches are not found, use `get_candidate_files()` to retrieve 50 potentially relevant filepaths.
- Add promising files to your shortlist by prioritizing those align with terminology, functionality or methods discussed in the bug report.

3. Method Analysis:
- For each file in the shortlist that hasn't been analyzed yet:
    - Use `get_method_signatures_of_a_file()` to list its methods.
    - Identify methods that directly align with the bug's context (e.g., related functionality, naming hints).
    - For any method of interest, retrieve its implementation using `get_method_body()`.
    - Analyze the logic of any identified method(s) of interest to determine whether they align with the bug's symptoms. 
- If this analysis reveals new relevant class names, filenames, or methods, use the appropriate search functions.
- Continuously update the shortlist by promoting, demoting or removing files based on evolving understanding.

4. Shortlist Refinement & Ranking:
- Rank files based on:
    - Semantic alignment with the bug report's keywords and described functionality
    - Method or filename alignment with bug context
    - Code logic alignment with the bug description
- If needed, iterate with refined assumptions or explore previously overlooked filenames or methods.

5. Final Output:
- Provide a ranked list of the 10 most relevant filepaths based on their likelihood of containing the bug.
- Ensure filepaths exactly match those provided—do not modify case, structure or abbreviate them.
- Justify each file's inclusion by referencing keywords, method matches or code logic that supports its relevance to the bug report. 
"""
        try:
            client = self.openai_client_manager.get_client()
            messages = [
                {"role": "system", "content": system_content}, {"role": "user", "content": self.create_prompt()}
            ]
            iteration_count = 0
            max_iterations = 10
            while iteration_count < max_iterations:
                self.logger.info(f"Iteration {iteration_count}")
                # print("iteration",iteration_count)
                if iteration_count == 0:
                    tool_choice = "required"
                elif iteration_count == max_iterations-2:
                    tool_choice = "none"
                else:
                    tool_choice = "auto"
                response = client.chat.completions.create(
                    model = "gpt-4o-mini",
                    # temperature= 0,
                    messages = messages,
                    tools = tools,
                    tool_choice = tool_choice,
                    response_format = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "output_format",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "analysis_of_the_bug_report": {
                                        "type": "string",
                                        "description": "Detailed analysis of the bug summary and description, including extracted keywords, error messages, affected components and any referenced methods or functionality that help guide the file search."
                                    },
                                    "ranked_list": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "file": {
                                                    "type": "string",
                                                    "description": "filepath, exactly as it appears in the codebase (case and structure preserved)."
                                                },
                                                "justification": {
                                                    "type": "string",
                                                    "description": "Explanation of why the file is considered relevant, including connections to bug report keywords, functionality, related method names and any analysis of method(s) of interest that reveal potential faults."
                                                }
                                            },
                                            "required": ["file", "justification"],
                                            "additionalProperties": False
                                        },
                                    },
                                },
                                "required": ["analysis_of_the_bug_report", "ranked_list"],
                                "additionalProperties": False
                            }
                        }
                    }
                )
                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls
                
                if tool_calls:
                    # print(tool_calls)
                    messages.append(response_message)

                    for tool_call in tool_calls:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                        self.logger.info(f"Function called: {function_name}, Arguments: {function_args}")

                        if function_name == "search_file":
                            function_response = self.file_data_processor.search_file(function_args.get("filename"))
                        elif function_name == "search_method":
                            function_response = self.file_data_processor.search_method(function_args.get("method_name"))
                        elif function_name == "get_candidate_files":
                            function_response = self.file_data_processor.get_candidate_files()
                        elif function_name == "get_method_signatures_of_a_file":
                            function_response = self.file_data_processor.get_method_signatures_of_a_file(function_args.get("filepath"))
                        elif function_name == "get_method_body":
                            method_signature = function_args.get("method_signature")
                            filepath = function_args.get("filepath")
                            function_response = self.file_data_processor.get_method_body(filepath, method_signature)
                        else:
                            function_response = {"error": f"Unknown function: {function_name}"}
                        
                        self.logger.info(f"Function response for {function_name}: {function_response}")
                        
                        messages.append(
                            {
                                "tool_call_id": tool_call.id,
                                "role": "tool",
                                "name": function_name,
                                "content": json.dumps(function_response),
                            }
                        )
                    iteration_count = iteration_count + 1
                else:
                    self.logger.info(f"API Usage: {response.usage}")
                    # print("messages",messages,iteration_count)
                    return response_message.content
        
        except Exception as e:
            print(f"An error occurred: {e}")