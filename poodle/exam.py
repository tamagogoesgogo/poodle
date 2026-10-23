from config import *
from core import *

import os
import re
from PIL import Image
import numpy as np
import json


def _load_moodle_json(path):
    """
    Load a Moodle-exported JSON file, handling two known Moodle export defects:

    1. Moodle sometimes appends an HTML error page directly after the JSON
       array's last bracket (e.g. '...}]<!DOCTYPE html>...'), and in doing
       so also omits the outer array's closing ']'.

    2. Multi-line student answers can contain literal control characters
       inside JSON strings, which violates the JSON spec.
    """
    def _strip_html_trailer(raw):
        for marker in ('<!DOCTYPE', '<html', '<!doctype'):
            idx = raw.find(marker)
            if idx != -1:
                truncated = raw[:idx].rstrip()
                # Re-balance any brackets that the truncation cut off.
                depth = truncated.count('[') - truncated.count(']')
                truncated += ']' * max(depth, 0)
                return truncated
        return raw

    def _sanitize(raw):
        out = []
        inside = False
        i = 0
        while i < len(raw):
            ch = raw[i]
            if inside:
                if ch == '\\':
                    out.append(ch)
                    i += 1
                    if i < len(raw):
                        out.append(raw[i])
                elif ch == '"':
                    inside = False
                    out.append(ch)
                elif ord(ch) < 0x20:
                    escapes = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
                    out.append(escapes.get(ch, f'\\u{ord(ch):04x}'))
                else:
                    out.append(ch)
            else:
                if ch == '"':
                    inside = True
                out.append(ch)
            i += 1
        return ''.join(out)

    for encoding in ('utf-8-sig', 'utf-8', 'latin-1'):
        try:
            with open(path, 'r', encoding=encoding) as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f'Could not decode file with any known encoding: {path}')

    # Pass 1: try the file as-is.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Pass 2: strip any HTML error page Moodle appended after the JSON.
    stripped = _strip_html_trailer(raw)
    if stripped != raw:
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Pass 3: fix bare control characters inside JSON strings, then try again.
    for candidate in (raw, stripped):
        try:
            return json.loads(_sanitize(candidate))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f'Could not parse Moodle JSON export "{path}".\n'
        f'Try re-exporting the file from Moodle.'
    )


def create_exam(exam, filename='import.xml', mode='terminal', questions=None, message=True):
    """
    Creates an xml file out of questions within the database. While using this
    function the user will be asked whether they want to use automatic or manual
    creation mode. In automatic mode a file which contains questions' names
    separated by whitespace is used to automatically generate the xml file. In
    manual mode the user will type in each question one by one.

    After the xml file is created, an exam document will be added to the EXAMS
    collection and all corresponding question documents will be modified within
    the QUESTIONS collection.

    Arguments:
    ----------
    exam (str):
      Name of the exam within Moodle/Poodle.
    filename (str):
      Name of the output xml file.
    mode (str):
      Changes behavior depending on if function is used in terminal or in GUI.
    questions (list):
      If used in GUI, a list of question names will be passed to this argument.
      The argument isn't used otherwise.

    ------------------------------
    Dependencies: config, core, re
    """

    # Write XML
    questionlist, info = create_xml(exam, filename, mode, questions)

    # Update database
    EXAMS.insert_one({
        'name': exam,
        'points_max': info[2],
        'time_est': info[0],
        'difficulty_avg': info[1],
        'questions': questionlist
    })
    for q in questionlist:
        QUESTIONS.find_one_and_update(
            {'name': q}, {'$set': {f'in_exams.{exam}': np.nan}}
        )

    # Final report
    if message:
        print((
            f'\nTotal points: {info[2]}\n'
            f'Average difficulty: {info[1]}\n'
            f'Estimated time: {info[0]} minutes\n'
        ))
        print('Database updated.')


def create_testexam(exam, filename='import.xml'):
    """
    This function is very similar to 'create_exam()' and is intended for
    experimenting with its features. It will not create any entries within the
    database upon creation of the exam. Apart from this, 'create_testexam()'
    functions exactly like 'create_exam()'.

    Arguments:
    ----------
    exam (str):
      Name of the exam within Moodle/Poodle.
    filename (str):
      Name of the output xml file.

    ------------------------------
    Dependencies: config, core, re
    """

    # Write XML
    questionlist, info = create_xml(exam, filename)

    print((
        f'\nTotal points: {info[2]}\n'
        f'Average difficulty: {info[1]}\n'
        f'Estimated time: {info[0]} minutes\n'
    ))
    print('Test exam successfully created.')
    

def remove_exam(exam, message=True):
    """
    Remove an exam from the database. This will remove the exam's document from
    the exams collection, as well as all entries of this exam within the
    questions.

    Arguments:
    ----------
    exam (str):
      Name of the exam that will be removed from the database.

    --------------------
    Dependencies: config
    """

    deletion = EXAMS.delete_many({'name': exam})
    updates = QUESTIONS.update_many(
        {'_id': {'$type': 7}}, {'$unset': {f'in_exams.{exam}': ''}}
    )
    # Final report
    if message:
        print(f'{deletion.deleted_count} document(s) have been removed ' +
              'from the exams collection.\n' +
              f'{updates.modified_count} question(s) have been updated.')


def inspect_moodle_export(path) -> tuple:
    """
    Determine which of Moodle's two exports a JSON file is, so the GUI can sort
    dropped files without asking the user which is which.

    Returns a (kind, exam_name) pair. kind is 'stats' for an export from
    'Statistik', 'grades' for one from 'Bewertung', or '' if the file is
    neither. exam_name is read from a stats file and is '' otherwise, since the
    grades export does not name the exam anywhere in its contents.

    Arguments:
    ----------
    path (str):
      Path of the JSON file to inspect.

    ----------------
    Dependencies: json
    """

    data = _load_moodle_json(path)
    first = data[0][0] if isinstance(data[0], list) else data[0]
    keys = first.keys()

    # The same key names evaluate_exam() uses to detect the export's language
    for name_key in ('quizname', 'test-name'):
        if name_key in keys:
            return 'stats', first[name_key]
    for last_name_key in ('lastname', 'nachname'):
        if last_name_key in keys:
            return 'grades', ''

    return '', ''


def evaluate_exam(exam_name, stats_file, grades_file, mode='terminal'):
    """
    This function will evaluate the JSON files which are exported from Moodle
    within the categories 'Statistik' and 'Bewertung'. The evaluated information
    regarding individual questions' and the exam's average score will be passed
    to the database.

    Arguments:
    ----------
    exam_name (str):
      Name of the exam within the database.
    stats_file (str):
      Path of the JSON file exported from 'Statistik'.
    grades_file (str):
      Path of the JSON file exported from 'Bewertung'.
    mode (str):
      Changes behavior depending on if function is used in terminal or in GUI.
      In 'gui' mode a missing exam directory is reported instead of prompting,
      because the GUI has already asked and nothing is reading stdin.

    ------------------------
    Dependencies: json, numpy
    """

    # Check for correct exam name
    if exam_name not in os.listdir(f'{BASE_PATH}/databases/{DB.name}/exams/'):
        if mode == 'gui':
            print(f'Warning: {exam_name} was not found in the exams directory.')
        else:
            prompt = ('Warning! Exam name was not found in directory. ' +
                      f'Do you still wish to evaluate exam {exam_name}? (y/n)\n')
            if yesno(prompt) == 'y':
                pass
            else:
                return 'Evaluation aborted.'
    assert EXAMS.find_one({'name': exam_name}), \
        f'Exam {exam_name} does not exist in database!'

    stats = _load_moodle_json(stats_file)

    # Define languages
    english = {
        'quiz_name': 'quizname', 'index': 'q', 'question_name': 'questionname',
        'last_name': 'lastname', 'overall_average': 'Overall average',
        'grade': 'grade'
    }
    german = {
        'quiz_name': 'test-name', 'index': 'f', 'question_name': 'titelderfrage',
        'last_name': 'nachname', 'overall_average': 'Gesamtdurchschnitt',
        'grade': 'bewertung'
    }
    # Detect language
    if 'quizname' in stats[0][0].keys():
        lang_profile = english
    elif 'test-name' in stats[0][0].keys():
        lang_profile = german

    # Check again for correct exam name
    assert stats[0][0][lang_profile['quiz_name']] == exam_name, \
        f'Exam name in stats file is not {exam_name}!'
    name_pairs = {}
    for q in stats[1]:
        # Ignore "clones" from rvar questions
        if '.' not in q[lang_profile['index']]:
            # Check question in database
            question = QUESTIONS.find_one(
                {'name': q[lang_profile['question_name']]}
            )
            if question:
                # Moodle uses column names like 'f1200' (no decimal). Build the
                # column name by multiplying points by 100 and formatting as an
                # integer to avoid trailing '.0' (which caused KeyError).
                points_hundred = int(round(question['points'] * 100))
                moodle_name = (
                    lang_profile['index'] + q[lang_profile['index']] +
                    str(points_hundred)
                )
                name_pairs[moodle_name] = [
                    q[lang_profile['question_name']], question['points']
                ]
            else:
                print(f'{q[lang_profile["question_name"]]} not in database. ' +
                      'Ignoring question for evaluation.')

    # Read grades_file for exam and question scores
    averages = _load_moodle_json(grades_file)[0][-1]
    assert averages[lang_profile['last_name']] == lang_profile['overall_average'], \
        f'Last entry in grades is not {lang_profile["overall_average"]}, ' + \
        f'but {averages[lang_profile["last_name"]]} instead!'
    # Append average question scores to name_pairs
    for q in name_pairs:
        # Use safe lookup to avoid KeyError when Moodle's export column name
        # doesn't exactly match our constructed name. If missing, warn and
        # store NaN so evaluation can continue.
        raw = averages.get(q)
        if raw is None:
            print(f'Warning: no average found for column "{q}" in grades file.')
            avg = np.nan
        elif raw == '-':
            avg = np.nan
        else:
            avg = float(raw.replace(',', '.'))
        name_pairs[q].append(avg)
    # Get average exam score
    exam_average = float([
        averages[k] for k, v in averages.items() if k.startswith(lang_profile['grade'])
    ][0].replace(',', '.'))
    # Update questions in DB
    for k, v in name_pairs.items():
        QUESTIONS.find_one_and_update(
            {'name': v[0]}, {'$set': {f'in_exams.{exam_name}': v[2]}}
        )
    # Update exam in DB
    rel_averages = {
        v[0]: np.round(v[2] / v[1], 2) for k, v in name_pairs.items()
    }
    EXAMS.find_one_and_update(
        {'name': exam_name},
        {'$set': {
            'points_avg': exam_average,
            'questions_avgs': rel_averages
         }}
    )

    print(f'\nExam {exam_name} succesfully evaluated.')
