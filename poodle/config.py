import pymongo
import os
import sys
import json

BASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def setup_db(db) -> None:
    # Check directories
    if db not in os.listdir(BASE_PATH + '/databases/'):
        os.mkdir(BASE_PATH + f'/databases/{db}')
    DB_PATH = BASE_PATH + f'/databases/{db}/'
    for d in ['backup', 'exams', 'img', 'random_vars']:
        if d not in os.listdir(DB_PATH):
            os.mkdir(DB_PATH + d)
    # Check JSON config
    if 'config.json' not in os.listdir(DB_PATH):
        config = {
            'NAME': db,
            'Q_CATEGORIES': [],
            'SHUFFLE': 1,
            'RANDOM_ARR_SIZE': 100,
            'COLLECTIONS': ['questions', 'exams']
        }
        with open(DB_PATH + 'config.json', 'w') as wf:
            json.dump(config, wf, indent=2)


def apply_config():
    db = DB.name
    path = BASE_PATH + f'/databases/{db}/config.json'
    try:
        with open(path, 'r') as rf:
            config = json.load(rf)
    except (json.JSONDecodeError, ValueError):
        # File is empty or corrupt (e.g. interrupted write). Reset to defaults.
        config = {}
        with open(path, 'w') as wf:
            json.dump(config, wf)
    # Check for config keys
    template = {
        'NAME': f'{db}',
        'Q_CATEGORIES': [],
        'SHUFFLE': 1,
        'RANDOM_ARR_SIZE': 100,
        'COLLECTIONS': ['questions', 'exams'],
        'FONT_SIZE': 13,
        'THEME': 'cobalt'
    }
    for i, j in template.items():
        if i not in config.keys():
            config[i] = j
    # Check for question categories
    if config['Q_CATEGORIES'] == []:
        db_categories = input(
            f'No question categories specified for database {db}!\n' +
            'Please input list of categories you want to set for this database\n' +
            'or input 0 if no predetermined categories are desired:\n'
        )
        try:
            db_categories = eval(db_categories)
        except SyntaxError:
            pass
        config['Q_CATEGORIES'] = db_categories
    # Update and reload JSON
    with open(BASE_PATH + f'/databases/{db}/config.json', 'w') as wf:
        json.dump(config, wf, indent=2)
    with open(BASE_PATH + f'/databases/{db}/config.json', 'r') as rf:
        config = json.load(rf)
    # Set variables defined in JSON
    Q_CATEGORIES = config['Q_CATEGORIES']
    SHUFFLE = config['SHUFFLE']
    RANDOM_ARR_SIZE = config['RANDOM_ARR_SIZE']
    FONT_SIZE = config['FONT_SIZE']

    return Q_CATEGORIES, SHUFFLE, RANDOM_ARR_SIZE, FONT_SIZE


def read_setting(key: str, default=None):
    """
    Read a single setting from the current database's config.json. Reads the
    file rather than the variables set at import, so a setting saved earlier in
    this session is seen as well.

    Arguments:
    ----------
    key (str):
      Name of the setting, e.g. 'FONT_SIZE'.
    default (any):
      Returned if the file or the key is missing.

    ----------------
    Dependencies: json
    """

    path = BASE_PATH + f'/databases/{DB.name}/config.json'
    try:
        with open(path, 'r') as rf:
            return json.load(rf).get(key, default)
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def save_setting(key: str, value) -> None:
    """
    Store a single setting in the current database's config.json, so a choice
    made in the GUI is still there on the next launch.

    Arguments:
    ----------
    key (str):
      Name of the setting, e.g. 'FONT_SIZE'.
    value (any):
      Value to store. Must be JSON-serializable.

    ----------------
    Dependencies: json
    """

    path = BASE_PATH + f'/databases/{DB.name}/config.json'
    try:
        with open(path, 'r') as rf:
            stored = json.load(rf)
    except (OSError, json.JSONDecodeError, ValueError):
        stored = {}
    stored[key] = value
    with open(path, 'w') as wf:
        json.dump(stored, wf, indent=2)


## Global variables
# Manage arguments passed from shell script to launch.py
args = [x for x in sys.argv if x != '']
if len(args) == 5:
    CREDENTIALS = (sys.argv[-4], sys.argv[-3])
del args
CONNECTION = sys.argv[-2]
CLIENT = pymongo.MongoClient(f'{CONNECTION}')
DB = eval(f'CLIENT.{sys.argv[-1]}')
QUESTIONS = DB.questions
EXAMS = DB.exams


setup_db(DB.name)
Q_CATEGORIES, SHUFFLE, RANDOM_ARR_SIZE, FONT_SIZE = apply_config()

# Expected value types for question keys
KEY_TYPES = {
    'general': {
        'name': str, 'question': str, 'family_type': str, 'moodle_type': str,
        'points': float, 'in_exams': dict, 'time_est': int, 'difficulty': int
    },
    'optional': {
        'img_files': list, 'tables': dict
    },
    # Moodle types
    'multichoice': {
        'correct_answers': list, 'false_answers': list, 'single': int
    },
    'numerical': {
        'correct_answers': list, 'tolerance': float
    },
    'shortanswer': {
        'correct_answers': list, 'usecase': int
    },
    'essay': {
        'answer_files': list
    },
    'matching': {
        'correct_answers': dict, 'false_answers': list
    },
    'gapselect': {
        'correct_answers': dict, 'false_answers': dict
    },
    'ddimageortext': {
        'correct_answers': list, 'drops': dict, 'img_files': list
    },
    'calculated': {
        'correct_answers': list, 'tolerance': list, 'vars': list
    }
}
# Expected value types for exam keys
EXAM_TYPES = {
    'name': str, 'points_max': float, 'points_avg': float, 'n_questions': int,
    'difficulty_avg': float, 'time_est': int, 'questions': (list, dict)
}
