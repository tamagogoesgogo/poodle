from config import *
from core import *

import ast
import re
import pymongo
import runpy
import time
import pandas as pd
import numpy as np
import re
import json


def check_question(json_string: str, ignore_duplicates: bool = False) -> dict:
    """
    Used by add_json() to check for correct question formatting.

    Arguments:
    ----------
    json_string (str):
      String that will be interpreted as JSON.
    ignore_duplicates (bool):
      If set to True, duplicate question names in database won't be classified
      as formatting errors. Used specifically for overwriting questions in GUI.

    ------------------
    Dependencies: json
    """

    question_dict = json.loads(json_string)
    result_dict = {}

    # Function for missing question keys
    def check_missing(question: dict, keys: dict, output: dict) -> None:
        for k in keys.keys():
            if k not in question.keys():
                output[k] = 'Missing'
    # Check if values are empty strings
    def check_empty(question: dict, keys: dict, output: dict) -> None:
        for k in keys.keys():
            if k not in output.keys() and k in question.keys():
                try:
                    if re.match(r'^$|^\s+$', question[k]):
                        output[k] = 'Empty value'
                except TypeError:
                    pass
    # Check if values have correct data type
    def check_type(question: dict, keys: dict, output: dict) -> None:
        for k, v in keys.items():
            if k not in output.keys() and k in question.keys():
                if type(question[k]) != v:
                    output[k] = f'Wrong data type. Expected: {v}'
    # Check if certain values are zero
    def check_zero(question: dict, keys: list, output: dict) -> None:
        for k in keys:
            if k not in output.keys() and k in question.keys():
                if (
                    (type(question[k]) == int or type(question[k]) == float)
                    and question[k] <= 0
                ):
                    output[f] = 'Value needs to be > 0'
    # Check if value is in possible set of limited options
    def check_in_options(input_obj, input_key: str, options: list, output: dict) -> None:
        if input_key not in output.keys():
            if input_obj not in options:
                output[input_key] = f'{input_obj} not in  possible options: {options}'
    # Check if list or dict has required length
    def check_length(input_obj, input_key: str, required: int, mode: str, output: dict) -> None:
        if input_key not in output.keys():
            if mode == 'fixed':
                if len(input_obj) != required:
                    output[input_key] = f'Wrong number of entries. (Required: {required})'
            elif mode == 'min':
                if len(input_obj) < required:
                    output[input_key] = f'Wrong number of entries. (Required: {required} or more)'
            else:
                raise Exception('Wrong mode argument')

    # Functions for each moodle_type and general fields
    def check_general(question: dict) -> None:
        # Keys that are always present
        check_missing(question, KEY_TYPES['general'], result_dict)
        check_empty(question, KEY_TYPES['general'], result_dict)
        check_type(question, KEY_TYPES['general'], result_dict)
        check_zero(question, ['points', 'time_est', 'difficulty'], result_dict)
        # Check for correct naming scheme
        if Q_CATEGORIES and 'name' not in result_dict:
            if question['name'][:-4] not in Q_CATEGORIES:
                result_dict['name'] = 'Wrong naming scheme'
        # Check for duplicate question name
        if not ignore_duplicates:
            if QUESTIONS.find_one({'name': question['name']}):
                result_dict['name'] = 'Name already exists in database.'
        # Make sure family_type is one of three possibilities
        if 'family_type' not in result_dict.keys():
            check_in_options(
                question['family_type'], 'family_type',
                ['single', 'parent', 'child'], result_dict
            )

        # Optional keys
        check_type(question, KEY_TYPES['optional'], result_dict)

    def check_multichoice(question: dict) -> dict:

        check_general(question)
        check_missing(question, KEY_TYPES['multichoice'], result_dict)
        check_empty(question, KEY_TYPES['multichoice'], result_dict)
        check_type(question, KEY_TYPES['multichoice'], result_dict)
        # Make sure single is 0 or 1
        if 'single' not in result_dict.keys():
            check_in_options(
                question['single'], 'single',
                [0, 1], result_dict
            )
        # Needs at least one correct answer
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                1, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict

    def check_numerical(question: dict) -> dict:

        check_general(question)
        check_missing(question, KEY_TYPES['numerical'], result_dict)
        check_empty(question, KEY_TYPES['numerical'], result_dict)
        check_type(question, KEY_TYPES['numerical'], result_dict)
        # Needs at least one correct answer
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                1, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict

    def check_shortanswer(question: dict) -> dict:

        check_general(question)
        check_missing(question, KEY_TYPES['shortanswer'], result_dict)
        check_empty(question, KEY_TYPES['shortanswer'], result_dict)
        check_type(question, KEY_TYPES['shortanswer'], result_dict)
        # Make sure usecase is 0 or 1
        if 'usecase' not in result_dict.keys():
            check_in_options(
                question['usecase'], 'usecase',
                [0, 1], result_dict
            )
        # Needs at least one correct answer
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                1, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict

    def check_essay(question: dict):
        
        check_general(question)
        check_missing(question, KEY_TYPES['essay'], result_dict)
        check_empty(question, KEY_TYPES['essay'], result_dict)
        check_type(question, KEY_TYPES['essay'], result_dict)
        # answer_files has fixed length of 2
        if 'answer_files' not in result_dict.keys():
            check_length(
                question['answer_files'], 'answer_files',
                2, 'fixed', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict
        
    def check_matching(question: dict):

        check_general(question)
        check_missing(question, KEY_TYPES['matching'], result_dict)
        check_empty(question, KEY_TYPES['matching'], result_dict)
        check_type(question, KEY_TYPES['matching'], result_dict)
        # Needs at least 2 correct answers to make sense
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                2, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict
        
    def check_gapselect(question: dict):

        check_general(question)
        check_missing(question, KEY_TYPES['gapselect'], result_dict)
        check_empty(question, KEY_TYPES['gapselect'], result_dict)
        check_type(question, KEY_TYPES['gapselect'], result_dict)
        # Needs at least one correct and false answer
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                1, 'min', result_dict
            )
        if 'false_answers' not in result_dict.keys():
            check_length(
                question['false_answers'], 'false_answers',
                1, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict
        
    def check_ddimageortext(question: dict):

        check_general(question)
        check_missing(question, KEY_TYPES['ddimageortext'], result_dict)
        check_empty(question, KEY_TYPES['ddimageortext'], result_dict)
        check_type(question, KEY_TYPES['ddimageortext'], result_dict)
        # Needs at least two correct answers
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                2, 'min', result_dict
            )
        # Needs at least two drops
        if 'drops' not in result_dict.keys():
            check_length(
                question['drops'], 'drops',
                2, 'min', result_dict
            )
        # Drops always have X and Y value
        if 'drops' not in result_dict.keys():
            for k, v in question['drops'].items():
                check_length(
                    question['drops'][k], f'drops.{k}',
                    2, 'fixed', result_dict
                )
        # Image file needs to be supplied
        if 'img_files' not in result_dict.keys():
            check_length(
                question['img_files'], 'img_files',
                1, 'fixed', result_dict
            )
        # Correct answers needs to be equal to drops
        if not any(k in result_dict.keys() for k in ('correct_answers', 'drops')):
            check_length(
                question['drops'], 'drops',
                len(question['correct_answers']), 'fixed', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict
        
    def check_calculated(question: dict):

        check_general(question)
        check_missing(question, KEY_TYPES['calculated'], result_dict)
        check_empty(question, KEY_TYPES['calculated'], result_dict)
        check_type(question, KEY_TYPES['calculated'], result_dict)
        # Needs one correct answer
        if 'correct_answers' not in result_dict.keys():
            check_length(
                question['correct_answers'], 'correct_answers',
                1, 'fixed', result_dict
            )
        # Tolerance needs to be 3 long
        if 'tolerance' not in result_dict.keys():
            check_length(
                question['tolerance'], 'tolerance',
                3, 'fixed', result_dict
            )
        # Make sure tolerance type is correct
        if 'tolerance' not in result_dict.keys():
            check_in_options(
                question['tolerance'][1], 'tolerance.type',
                ['relative', 'nominal', 'geometric'], result_dict
            )
        # Must have at least one variable defined
        if 'vars' not in result_dict.keys():
            check_length(
                question['vars'], 'vars',
                1, 'min', result_dict
            )

        if result_dict:
            result_dict['__question_name__'] = question['name']

        return result_dict

    # Operate according to moodle_type
    match question_dict['moodle_type']:
        case 'multichoice':
            result = check_multichoice(question_dict)
            return dict(sorted(result.items()))
        case 'numerical':
            result = check_numerical(question_dict)
            return dict(sorted(result.items()))
        case 'shortanswer':
            result = check_shortanswer(question_dict)
            return dict(sorted(result.items()))
        case 'essay':
            result = check_essay(question_dict)
            return dict(sorted(result.items()))
        case 'matching':
            result = check_matching(question_dict)
            return dict(sorted(result.items()))
        case 'gapselect':
            result = check_gapselect(question_dict)
            return dict(sorted(result.items()))
        case 'ddimageortext':
            result = check_ddimageortext(question_dict)
            return dict(sorted(result.items()))
        case 'calculated':
            result = check_calculated(question_dict)
            return dict(sorted(result.items()))
        case _:
            return {'__question_name__': question_dict['name'], 'moodle_type': 'Unknown'}


def add_json(json_file: str) -> tuple[None, str]:
    """
    Add questions to the database automatically by reading a JSON file.
    Questions need to be enclosed in list brackets.

    -------------------------------
    Dependencies: re, json, pymongo
    """

    with open(json_file, 'r') as rf:
        question_list = json.load(rf)

    error_list = []
    for q in question_list:
        check_result = check_question(json.dumps(q))
        if not check_result:
            # Check for empty img_files/tables fields
            if 'img_files' in q.keys() and q['img_files'] == []:
                q.pop('img_files')
            if 'tables' in q.keys() and q['tables'] == {}:
                q.pop('tables')
            QUESTIONS.insert_one(q)
        else:
            error_list.append(check_result)

    if not error_list:
        print('All questions added successfully!')
        return None
    else:
        print('Some questions could not be added due to errors:')
        pprint(error_list)
        return ''


def create_template(file_path: str, file_type: str) -> None:
    """
    Creates a template file for later question import.

    Arguments:
    ----------
    file_path (str):
      Location where file will be saved.
    file_type (str):
      Accepted types are 'xls'/'excel' or 'json'.

    ------------------------------
    Dependencies: re, pandas, json
    """
        
    def fill_fields(moodle_type: dict) -> dict:

        all_fields = moodle_type
        all_fields['name'] = 'X'
        all_fields['family_type'] = 'X'
        all_fields['points'] = 0
        all_fields['difficulty'] = 0
        all_fields['time_est'] = 0
        all_fields['img_files'] = []
        all_fields['tables'] = {}
        all_fields['question'] = 'X'

        optional_fields = [
            'correct_answers', 'false_answers', 'single', 'tolerance',
            'usecase', 'answer_files', 'drops', 'vars'
        ]
        for f in optional_fields:
            if f not in all_fields.keys():
                all_fields[f] = ''

        return all_fields

    # Define template fields for each moodle_type
    multichoice = {
        'moodle_type': 'multichoice',
        'correct_answers': '["X", "..."]',
        'false_answers': '["X", "..."]',
        'single': 1
    }
    numerical = {
        'moodle_type': 'numerical',
        'correct_answers': '["X", "..."]',
        'tolerance': 0
    }
    shortanswer = {
        'moodle_type': 'shortanswer',
        'correct_answers': '["X", "..."]',
        'usecase': 0
    }
    essay = {
        'moodle_type': 'essay',
        'answer_files': '[0, 0]'
    }
    matching = {
        'moodle_type': 'matching',
        'correct_answers': '{"X1": "Y1", "...": "..."}',
        'false_answers': '["X", "..."]'
    }
    gapselect = {
        'moodle_type': 'gapselect',
        'correct_answers': '{"1": ["X"], "...": ["..."]}',
        'false_answers': '{"1": ["X", "..."], "...": ["..."]}'
    }
    ddimageortext = {
        'moodle_type': 'ddimageortext',
        'correct_answers': '["X", "..."]',
        'drops': '{"1": [0, 0], "...": [0, 0]}'
    }
    calculated = {
        'moodle_type': 'calculated',
        'correct_answers': '["X", "..."]',
        'tolerance': '[0, "X", 0]',
        'vars': '["X", "..."]'
    }

    moodle_types = [
        fill_fields(multichoice), fill_fields(numerical), fill_fields(shortanswer),
        fill_fields(essay), fill_fields(matching), fill_fields(gapselect),
        fill_fields(ddimageortext), fill_fields(calculated)
    ]

    fields = [
        'name', 'moodle_type', 'family_type', 'points', 'difficulty', 'time_est',
        'img_files', 'tables', 'question', 'correct_answers', 'false_answers',
        'single', 'tolerance', 'usecase', 'answer_files', 'drops', 'vars'
    ]

    if  bool(re.match('xls', file_type.lower())) or bool(re.match('excel', file_type.lower())):
        df = pd.DataFrame({
            f: [m[f] for m in moodle_types] for f in fields
        })
        df.to_excel(f'{file_path}/template.xlsx', index=False)
    elif bool(re.match('json', file_type.lower())):
        # Remove empty fields
        moodle_types = [
            {x: y for x,y in m.items() if y != ''} for m in moodle_types
        ]
        # Add in_exams field
        for m in moodle_types:
            m['in_exams'] = {}
        # Write to file
        with open(f'{file_path}/template.json', 'w') as rf:
            json.dump(moodle_types, rf, indent=2)
    else:
        print(f'Unknown file type: {file_type}')


def add_question():
    """
    This function's purpose is to add new questions to the database. It allows
    for manual input of questions with auto-completion features targeted at
    child questions.

    ---------------------
    Dependencies: config, core, re, pymongo
    """

    # Define sub-functions for each different moodle_type
    def add_numerical(dictionary):
        dictionary['correct_answers'] = []
        dictionary['tolerance'] = 0.5

    def add_multichoice(dictionary):
        dictionary['correct_answers'] = []
        dictionary['false_answers'] = []

    def add_shortanswer(dictionary):
        dictionary['correct_answers'] = []
        dictionary['usecase'] = False

    def add_essay(dictionary):
        dictionary['answer_files'] = []

    def add_matching(dictionary):
        dictionary['correct_answers'] = {}
        dictionary['false_answers'] = []

    def add_gapselect(dictionary):
        dictionary['correct_answers'] = {}
        dictionary['false_answers'] = {}

    def add_ddimageortext(dictionary):
        dictionary['correct_answers'] = []
        dictionary['drops'] = {}
        dictionary['img_files'] = []

    def add_coderunner(dictionary):
        dictionary['correct_answers'] = []


    family_type = fast_input(['parent', 'child', 'single'],
                             "Please specify question's family type." +
                        "(Available types: 'parent', 'child', 'single')\n")
    if family_type == 'child':
        # Create dict of parent question
        parent_name = input('Please specify the parent question: ')
        if parent_name[-2:] != '00':
            parent_name = parent_name + '00'
        parent_question = None
        while parent_question == None:
            try:
                if QUESTIONS.find_one({'name': parent_name})['family_type'] == 'parent':
                    parent_question = QUESTIONS.find_one({'name': parent_name})
                else:
                    parent_name = input('Please specify a question with parent family type. ')
            except:
                parent_name = input('Question not in database! Please specify ' +
                                    'a valid parent question. ')
        parent_question['family_type'] = family_type
        parent_question['in_exams'] = {}
        # Look for placeholders in parent_question
        for p in range(
                len(re.findall(r'\[\[.+?\]\]', parent_question['question']))
        ):
            print(parent_question['question'])
            insertion = input(
                'Please input the text for placeholder %d: ' % (p+1)
            )
            parent_question['question'] = re.sub(
                r'\[\[.+?\]\]', insertion, parent_question['question'], count=1
            )
        print(parent_question['question'])
        # Go through question properties and potentially make changes
        parent_question = inspect_properties(parent_question, mode = 'child')
        # Drop _id-field of overwritten parent via dict comprehension
        new_question = {
            i:parent_question[i] for i in parent_question if i != '_id'
        }
        # Adjust last two digits of question name
        # --------------------------------------------
        # Create search criterion based on parent name
        q_name = re.compile(r'%s\d{2}' % (parent_name[:-2]))
        # Look through collection
        digits = [q['name'][-2:] for q in QUESTIONS.find({'name': q_name})]
        digits.sort()
        new_question['name'] = new_question['name'][:-2] + '%02d' % (int(digits[-1])+1)
        result = QUESTIONS.insert_one(new_question)
    else:
        # Create general question template
        new_question = {
            'name': '',
            'question': '',
            'family_type': family_type,
            'moodle_type': '',
            'points': 0,
            'in_exams': {},
            'time_est': 0,
            'difficulty': 0
        }
        # Ask for category
        if Q_CATEGORIES:
            category = fast_input(Q_CATEGORIES,
                                  "Please specify question's category.\n(Available " +
                                  "categories: %s)\n" % (Q_CATEGORIES))
        else:
            category = input("Please specify question's category: ")
        # Determine new question's name
        last_question = 0
        for q in QUESTIONS.find({'name': re.compile(category)}):
            q_number = int(q['name'][-4:-2])
            if q_number > last_question:
                last_question = q_number
        if family_type == 'parent':
            new_question['name'] = category + '%.2d' % (last_question+1) + '00'
        else:
            new_question['name'] = category + '%.2d' % (last_question+1) + '99'
        # Ask for moodle_type to determine needed sub-function
        available_moodle_types = [
            'multichoice', 'numerical', 'essay', 'matching',
            'gapselect', 'shortanswer', 'coderunner', 'ddimageortext'
        ]
        moodle_type = fast_input(available_moodle_types,
                                 "Please specify question's moodle_type.\n" +
                                 "(Available types: %s)\n"  % (available_moodle_types))
        new_question['moodle_type'] = moodle_type
        # Execute needed sub-function to modify new_question
        eval('add_' + moodle_type + '(new_question)')
        # Ask if img_files field should be added
        if moodle_type != 'ddimageortext':
            if yesno('Do you want to add an img_files field? (y/n)\n') == 'y':
                new_question['img_files'] = []
        # Modify properties
        new_question = inspect_properties(new_question, 'parsingle', inspect = False)
        # Account for special multichoice cases
        if (
                moodle_type == 'multichoice' and
                len(new_question['correct_answers']) == 1
        ):
            prompt = ('Is this question supposed to allow checking of ' +
                      'only one answer box? (y/n)\n')
            if yesno(prompt) == 'n':
                new_question['single'] = False
        # Add question to collection
        result = QUESTIONS.insert_one(new_question)
    # Summary
    if type(result) == pymongo.results.InsertManyResult:
        added_list = [
            QUESTIONS.find_one({'_id': i})['name'] for i in result.inserted_ids
        ]
        print('Questions ' + ("'{}', " * len(added_list))[:-2].format(
            *added_list
        ) + ' succesfully added.')
    else:
        print('Question {} successfully added.'.format(
            QUESTIONS.find_one({'_id': result.inserted_id})['name']
        ))


def edit_question(question, edits={}, history=False):
    """
    This function allows for fast editing of questions, slimming down the bulky
    syntax of pymongo.

    Arguments:
    ----------
    question (str):
      Name of the question you want to edit.
    edits (dict):
      Changes to be made in form of a dictionary where key is field name and
      value is field content. Fields can be edited manually if left empty.
    history (bool):
      If set to True, will add or modify the history field which contains a
      documentation of the changes.

    ------------------
    Dependencies: config, core, time
    """

    if edits:
        if history:
            # Get old or create new history field
            try:
                history_dict = QUESTIONS.find_one({'name': question})['history']
            except:
                history_dict = {}
            for k,v in edits.items():
                try:
                    # Save old contents for documentation
                    old_key = str(k) + '_old'
                    old_value = QUESTIONS.find_one({'name': question})[k]
                except:
                    pass
                new_key = str(k) + '_new'
                new_value = v
                # Overwrite history field
                try:
                    history_dict[
                        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    ] = {old_key: old_value, new_key: new_value}
                except:
                    history_dict[
                        time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    ] = {new_key: new_value}
                QUESTIONS.find_one_and_update(
                    {'name': question}, {'$set': {'history': history_dict}}
                )
                QUESTIONS.find_one_and_update(
                    {'name': question}, {'$set': {k: v}}
                )
        else:
            for k,v in edits.items():
                QUESTIONS.find_one_and_update(
                    {'name': question}, {'$set': {k: v}}
                )
    # Manual editing
    else:
        if history:
            # Get old or create new history field
            try:
                history_dict = QUESTIONS.find_one({'name': question})['history']
            except:
                history_dict = {}
        q_dict = QUESTIONS.find_one({'name': question})
        print("Enter 'quit' at the following prompt to quit editing.")
        field = input('Edit field: ')
        while field.lower() != 'quit':
            if field not in q_dict.keys():
                print('Please input a valid field key.')
            else:
                q_dict = inspect_properties(q_dict, mode=field)
                if history:
                    try:
                        # Save old contents for documentation
                        old_key = field + '_old'
                        old_value = QUESTIONS.find_one({'name': question})[field]
                    except:
                        pass
                    new_key = field + '_new'
                    new_value = q_dict[field]
                    # Overwrite history field
                    try:
                        history_dict[
                            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                        ] = {old_key: old_value, new_key: new_value}
                    except:
                        history_dict[
                            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                        ] = {new_key: new_value}
                    QUESTIONS.find_one_and_update(
                    {'name': question}, {'$set': {'history': history_dict}}
                    )
                QUESTIONS.find_one_and_update(
                    {'name': question}, {'$set': {field: q_dict[field]}}
                )
            field = input('Edit field: ')


def remove_question(question, archive=False):
    """
    Simple function for question deletion.

    Arguments:
    ----------
    question (str):
      Name of the question that will be removed from the database.
    archive (bool):
      If set to True, a copy of the question will be moved to the archive
      collection.

    --------------------
    Dependencies: config
    """

    if archive == False:
        result = QUESTIONS.delete_one({'name': question})
    else:
        q = QUESTIONS.find_one({'name': question})
        q.pop('_id')
        DB.archive.insert_one(q)
        result = QUESTIONS.delete_one({'name': question})
    if result.deleted_count:
        print('Question successfully removed.')
    else:
        print(f"Question '{question}' not in collection. Nothing to remove.")


def dataset_items(question_name: str, variables: list) -> list:
    """
    Run a question's variable creation file and return the values it produced,
    formatted exactly as create_exam() writes them into Moodle's dataset items.

    Each element of the returned list is one dataset item: a dictionary mapping
    every variable name to the value Moodle would substitute for {name} in that
    item. Used by the GUI to preview a calculated question with real numbers.

    The file is executed fresh on every call, so edits made in the variable
    editor show up in the next preview.

    Arguments:
    ----------
    question_name (str):
      Name of the question whose rv_<name>.py file will be run.
    variables (list):
      Names of the variables to read out of that file.

    -------------------------------
    Dependencies: config, core, numpy, runpy
    """

    path = f'{BASE_PATH}/databases/{DB.name}/random_vars/rv_{question_name}.py'
    namespace = runpy.run_path(path)

    missing = [v for v in variables if v not in namespace]
    if missing:
        raise KeyError(
            f"not defined in rv_{question_name}.py: {', '.join(missing)}"
        )

    columns = {}
    for v in variables:
        values = np.atleast_1d(namespace[v])
        decimals = CalculatedQuestion.count_decimals(values)
        columns[v] = [
            str(np.int64(x)) if decimals == 0 else str(x) for x in values
        ]

    item_count = min(len(c) for c in columns.values())

    return [
        {v: columns[v][i] for v in columns}
        for i in range(item_count)
    ]
