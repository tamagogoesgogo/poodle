from config import *
import context

import json
import time
import os
import platform
import subprocess
import shutil
import contextlib
import tempfile
import zipfile
import re
import pyperclip
from lxml import etree as ET
import base64
import numpy as np
import copy
from pprint import pprint
from pymongo import MongoClient

# for the scrolled mongodb text
import tkinter as tk
from tkinter import scrolledtext

# for the export/import commands

import subprocess

### kara functions ###

def export_question(db_from, question_name, directory="q_in_out"):
    """
    Exports a question from a MongoDB database and saves it as a JSON file.
    
    Arguments:
        db_from (str): Name of the source database.
        question_name (str): Name of the question to export.
        directory (str): Directory to save the exported JSON file (default is 'q_in_out').
    """
    # Ensure the directory exists
    os.makedirs(directory, exist_ok=True)
    
    # Define the output file path
    file_path = os.path.join(directory, f"{question_name}.json")
    
    # Mongoexport command
    export_command = [
        "mongoexport",
        "--uri", "mongodb://localhost:27017",
        "--db", db_from,
        "--collection", "questions",
        "--query", f'{{"name": "{question_name}"}}',
        "--out", file_path
    ]
    
    try:
        # Run mongoexport
        print(f"Exporting question '{question_name}' from '{db_from}' to '{file_path}'...")
        subprocess.run(export_command, check=True)
        print(f"Export successful. File saved at '{file_path}'.")
        return file_path  # Return the file path for reference
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during export: {e}")
        return None


def import_question(db_to, question_name, directory="q_in_out"):
    """
    Imports a question JSON file into a MongoDB database.
    
    Arguments:
        db_to (str): Name of the target database.
        question_name (str): Name of the question to import.
        directory (str): Directory where the JSON file is stored (default is 'q_in_out').
    """
    # Define the input file path
    file_path = os.path.join(directory, f"{question_name}.json")
    
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist. Make sure to export the question first.")
        return
    
    # Mongoimport command
    import_command = [
        "mongoimport",
        "--uri", "mongodb://localhost:27017",
        "--db", db_to,
        "--collection", "questions",
        "--file", file_path
    ]
    
    try:
        # Run mongoimport
        print(f"Importing question '{question_name}' from '{file_path}' into '{db_to}'...")
        subprocess.run(import_command, check=True)
        print("Import successful.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during import: {e}")



def mongo_show():
    """
    Open a window displaying MongoDB control instructions.

    This window provides commands to check and start the MongoDB service.
    """

    # Create a new window
    window = tk.Tk()

    # create the text
    text = ("Vor jedem poodle-start:\n\n sudo systemctl status mongod\n\n"
            "Falls mongodb nicht aktiv:\n\n sudo systemctl start mongod")

    # Set the window title
    window.title("Mongo Control")

    # Set the window size
    window.geometry("400x200")

    # Create a scrollable text area
    text_area = scrolledtext.ScrolledText(window, wrap=tk.WORD, width=60, height=20)

    # Insert the provided text into the text area
    text_area.insert(tk.INSERT, text)

    # Make the text area read-only
    text_area.config(state=tk.DISABLED)

    # Pack the text area into the window
    text_area.pack(pady=10, padx=10)

    # Run the window loop
    window.mainloop()
    

def backup(db=DB.name) -> None:
    """
    Dependencies: config, time, os
    """
    backup_time = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime())
    os.mkdir(f'{BASE_PATH}/databases/{db}/backup/{backup_time}')
    with open(f'{BASE_PATH}/databases/{db}/backup/{backup_time}/timestamp', 'w') as wf:
        wf.write(str(time.time()))
    # Backup from server
    if 'localhost' not in CONNECTION:
        subprocess.run(
            ["mongodump", f"--db={db}",
             f"--out={BASE_PATH}/databases/{db}/backup/{backup_time}",
             f"--authenticationDatabase=admin", f"{CONNECTION}"]
        )
    # Local backup
    else:
        subprocess.run(
            ["mongodump", f"--db={db}",
             f"--out={BASE_PATH}/databases/{db}/backup/{backup_time}"]
        )
        
### kara ###

def delete_db(db_name):
    """
    Connect to the local MongoDB instance and delete the specified database.

    Arguments:
    db_name (str): Name of the database to delete.
    """
    try:
        # Connect to MongoDB (assuming it's running locally on the default port)
        client = MongoClient("mongodb://localhost:27017/")

        # List databases before deletion
        print("Databases before deletion:", client.list_database_names())

        # Delete the specified database
        client.drop_database(db_name)

        # Confirmation message
        print(f"Database '{db_name}' has been deleted.")

        # List databases after deletion to confirm
        print("Databases after deletion:", client.list_database_names())

    except Exception as e:
        print(f"An error occurred: {e}")


def restore(path=None, db=DB.name) -> None:
    """
    Dependencies: config, platform, subprocess
    """
    if path == None:
        folder = sorted(os.listdir(BASE_PATH + f'/databases/{db}/backup/'))[-1]
        path = BASE_PATH + f'/databases/{db}/backup/' + folder
    # Restore local backup files to server
    if 'localhost' not in CONNECTION:
        subprocess.run(
            ["mongorestore", f"--host={CONNECTION[CONNECTION.find('@')+1:]}",
             f"--username={CREDENTIALS[0]}", f"--password={CREDENTIALS[1]}",
             f"--authenticationDatabase=admin", f"--nsInclude={db}.*", f"{path}"]
        )
    # Restore backup files to localhost
    else:
        subprocess.run(["mongorestore", f"--nsInclude={db}.*", f"{path}"])


### Database update from a received database folder ###

# Folders of databases/<db>/ that belong to the database's content and are
# replaced by an update. backup/ is merged instead, config.json partly.
UPDATE_FOLDERS = ['exams', 'img', 'random_vars']
# Settings in config.json that describe the database itself. FONT_SIZE and
# THEME are each user's own choice and are never taken from an update.
UPDATE_SETTINGS = ['Q_CATEGORIES', 'SHUFFLE', 'RANDOM_ARR_SIZE', 'COLLECTIONS']


def _dump_db_name(folder):
    """Name of the database dumped in a backup folder, or None."""
    for name in sorted(os.listdir(folder)):
        sub = os.path.join(folder, name)
        if os.path.isdir(sub) and any(f.endswith('.bson') for f in os.listdir(sub)):
            return name
    return None


_BACKUP_NAME = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$')


def _dumps_in(folder):
    """
    Backup folders of a database folder as {name: path}, oldest first. They
    are found in its backup/ folder or, as in the copies sent from the server,
    directly inside it. Backups without a dump in them are left out.
    """
    found = {}
    for parent in (folder, os.path.join(folder, 'backup')):
        try:
            names = os.listdir(parent)
        except OSError:
            continue
        for name in names:
            # Only folders named the way backup() names them. Looking into
            # img/ or random_vars/ as well would check every file in them,
            # which on a network drive takes half a second per file.
            if not _BACKUP_NAME.match(name):
                continue
            path = os.path.join(parent, name)
            if os.path.isdir(path) and _dump_db_name(path):
                found[name] = path
    # Backup folders are named by time, so the newest sorts last
    return dict(sorted(found.items()))


@contextlib.contextmanager
def _unpacked(source):
    """A received .zip unpacked into a temporary folder; a folder as it is."""
    if os.path.isfile(source) and zipfile.is_zipfile(source):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(source) as zf:
                zf.extractall(tmp)
            yield tmp
    else:
        yield source


def _locate_update(source):
    """(database folder or None, backup folder, dumped database name)"""
    while True:
        if any(f.endswith('.bson') for f in os.listdir(source)):
            return None, os.path.dirname(source), os.path.basename(source)
        dumps = _dumps_in(source)
        if dumps:
            dump = list(dumps.values())[-1]
            return source, dump, _dump_db_name(dump)
        if _dump_db_name(source):
            return None, source, _dump_db_name(source)
        # A folder that only wraps another one, as an unpacked .zip does
        entries = [e for e in os.listdir(source)
                   if not e.startswith('.') and e != '__MACOSX']
        if len(entries) == 1 and os.path.isdir(os.path.join(source, entries[0])):
            source = os.path.join(source, entries[0])
        else:
            raise ValueError('No database backup found in it.')


def _checked_source(source, db):
    source = os.path.abspath(source)
    if not os.path.exists(source):
        raise ValueError(f'{source} does not exist.')
    local = os.path.abspath(f'{BASE_PATH}/databases/{db}')
    if os.path.exists(local) and os.path.samefile(source, local):
        raise ValueError('This is the current database\'s own folder. '
                         'Choose the folder you received instead.')
    return source


def _copy_tree(src, dst, copied, progress):
    """
    Copy a folder file by file. One at a time on purpose: through a network
    drive mounted by the file manager (gvfs), copying in parallel measured
    three times slower. Python's __pycache__ is left behind.
    """
    os.makedirs(dst, exist_ok=True)
    for entry in os.scandir(src):
        if entry.name == '__pycache__':
            continue
        target = os.path.join(dst, entry.name)
        if entry.is_dir():
            _copy_tree(entry.path, target, copied, progress)
        else:
            shutil.copyfile(entry.path, target)
            copied[0] += 1
            if progress:
                progress(copied[0])


def fetch_update(source, dest, db=DB.name, progress=None) -> str:
    """
    Copy what update_database() uses from a received folder or .zip into the
    local folder dest, and return where the copy is, to update from there.

    On a network drive every file takes about half a second however small it
    is, so only the parts an update uses are copied: the newest backup,
    exams/, img/, random_vars/ and config.json. A .zip is one file and comes
    through in seconds; that is the fast way to hand out updates on BoxUP.

    Arguments:
    ----------
    progress (callable):
      Called with the number of files copied so far, after each one.

    ----------------------------------------
    Dependencies: config, os, shutil, zipfile
    """
    source = _checked_source(source, db)
    copied = [0]

    if os.path.isfile(source):
        if not zipfile.is_zipfile(source):
            raise ValueError(f'{source} is neither a folder nor a .zip file.')
        local_zip = os.path.join(dest, 'update.zip')
        shutil.copyfile(source, local_zip)
        if progress:
            progress(1)
        with zipfile.ZipFile(local_zip) as zf:
            zf.extractall(os.path.join(dest, 'unzipped'))
        os.remove(local_zip)
        return os.path.join(dest, 'unzipped')

    folder, dump, dump_db = _locate_update(source)
    if folder is None:
        target = os.path.join(dest, os.path.basename(dump))
        _copy_tree(dump, target, copied, progress)
        return target

    target = os.path.join(dest, os.path.basename(folder))
    _copy_tree(dump, os.path.join(target, os.path.basename(dump)), copied, progress)
    for sub in UPDATE_FOLDERS:
        if os.path.isdir(os.path.join(folder, sub)):
            _copy_tree(os.path.join(folder, sub), os.path.join(target, sub),
                       copied, progress)
    if os.path.isfile(os.path.join(folder, 'config.json')):
        shutil.copyfile(os.path.join(folder, 'config.json'),
                        os.path.join(target, 'config.json'))
    return target


def inspect_update(source, db=DB.name) -> dict:
    """
    Find the newest database dump inside a folder or .zip received as an
    update and describe it, without changing anything.

    Arguments:
    ----------
    source (str):
      The .zip or folder received, holding a database folder like
      databases/<db>/ (the usual case), or a single backup folder
      (databases/<db>/backup/<time>) or the dumped database inside one.

    Returns a dict with:
      'folder': the database folder, or None if only a backup was given
      'dump': the backup folder that will be restored
      'dump_db': the name of the database inside that dump
      'taken': when the dump was made, as 'YYYY-MM-DD HH:MM'
      'counts': {collection: (documents in update, documents now)}
      'files': {folder in UPDATE_FOLDERS: number of entries in it in the
                update, or None if the update does not have that folder}
      'newer_local': name of a local backup newer than the update, or None
    Paths are only valid while source is a folder, not a .zip.

    --------------------------------
    Dependencies: config, os, bson
    """
    import bson

    source = _checked_source(source, db)
    local = os.path.abspath(f'{BASE_PATH}/databases/{db}')

    with _unpacked(source) as unpacked:
        if not os.path.isdir(unpacked):
            raise ValueError(f'{source} is neither a folder nor a .zip file.')
        folder, dump, dump_db = _locate_update(unpacked)

        name = os.path.basename(dump)
        try:
            taken = time.strftime(
                '%Y-%m-%d %H:%M', time.strptime(name, '%Y-%m-%d_%H-%M-%S')
            )
        except ValueError:
            taken = name

        counts = {}
        for f in sorted(os.listdir(os.path.join(dump, dump_db))):
            if f.endswith('.bson'):
                collection = f[:-len('.bson')]
                with open(os.path.join(dump, dump_db, f), 'rb') as rf:
                    new = sum(1 for _ in bson.decode_file_iter(rf))
                counts[collection] = (new, DB[collection].count_documents({}))

        files = {}
        for sub in UPDATE_FOLDERS:
            path = os.path.join(folder, sub) if folder else None
            files[sub] = (len([f for f in os.listdir(path) if f != '__pycache__'])
                          if path and os.path.isdir(path) else None)

    newer = [b for b in _dumps_in(local) if b > name] if os.path.isdir(local) else []

    return {'folder': folder, 'dump': dump, 'dump_db': dump_db,
            'taken': taken, 'counts': counts, 'files': files,
            'newer_local': newer[-1] if newer else None}


def _mongo_tool(tool, *args):
    """Run mongodump/mongorestore against the current connection."""
    if 'localhost' not in CONNECTION:
        login = [f"--host={CONNECTION[CONNECTION.find('@')+1:]}",
                 f"--username={CREDENTIALS[0]}", f"--password={CREDENTIALS[1]}",
                 "--authenticationDatabase=admin"]
    else:
        login = [f'--uri={CONNECTION}']
    result = subprocess.run([tool, *login, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'{tool} failed:\n{result.stderr.strip()}')


def _replace_folder(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def update_database(source, db=DB.name, progress=None) -> str:
    """
    Replace the database with a newer version received as a folder or .zip,
    e.g. a copy of databases/<db>/ from the university's server. The update wins:
    afterwards the database is an exact copy of the newest backup inside the
    folder, and exams/, img/ and random_vars/ match the folder's.

    The current state is saved first to databases/<db>/before_update/<time>/
    and can be brought back with undo_last_update(). If restoring fails, that
    is done automatically.

    This replaces running remove_exam() and restore() by hand: restore() alone
    skips every document that already exists, so changed questions were never
    updated.

    Arguments:
    ----------
    source (str):
      The received folder or .zip; see inspect_update() for what it may be.
    progress (callable):
      See fetch_update().

    Returns a short report of what was updated.

    ----------------------------------------
    Dependencies: config, os, shutil, subprocess
    """
    if 'localhost' not in CONNECTION:
        raise RuntimeError('Updating from a folder only works on a local '
                           'database; this would overwrite the server.')

    # Everything is read from a local copy: a network drive is slow to read
    # twice, and a connection lost halfway must not leave a half update.
    with tempfile.TemporaryDirectory() as tmp:
        return _update_database(fetch_update(source, tmp, db, progress), db)


def _update_database(source, db):
    info = inspect_update(source, db)
    local = f'{BASE_PATH}/databases/{db}'

    # 1. Save the current state
    saved = f'{local}/before_update/{time.strftime("%Y-%m-%d_%H-%M-%S")}'
    os.makedirs(f'{saved}/files')
    _mongo_tool('mongodump', f'--db={db}', f'--out={saved}')
    for name in UPDATE_FOLDERS + ['config.json']:
        path = f'{local}/{name}'
        if os.path.isdir(path):
            shutil.copytree(path, f'{saved}/files/{name}')
        elif os.path.isfile(path):
            shutil.copy2(path, f'{saved}/files/{name}')

    # 2. Replace the database. --drop empties each collection first, so
    #    documents that already exist are updated instead of skipped.
    rename = []
    if info['dump_db'] != db:
        rename = [f'--nsFrom={info["dump_db"]}.*', f'--nsTo={db}.*']
    try:
        _mongo_tool('mongorestore', '--drop', f'--nsInclude={info["dump_db"]}.*',
                    *rename, info['dump'])
    except RuntimeError as e:
        undo_last_update(db)
        raise RuntimeError(f'{e}\n\nThe database was left as it was.') from None

    report = [f'Database updated to the version of {info["taken"]}.']
    for collection, (new, old) in info['counts'].items():
        report.append(f'{collection}: {old} → {new}')

    # 3. Files belonging to the database
    folder = info['folder']
    if folder is None:
        report.append('Only a backup was given, so exams/, img/ and '
                      'random_vars/ were not changed.')
        return '\n'.join(report)

    for name in UPDATE_FOLDERS:
        if os.path.isdir(f'{folder}/{name}'):
            _replace_folder(f'{folder}/{name}', f'{local}/{name}')

    # The backup restored, so the local history has it as well
    for name, path in _dumps_in(folder).items():
        if not os.path.exists(f'{local}/backup/{name}'):
            shutil.copytree(path, f'{local}/backup/{name}')

    configs = []
    for path in (f'{folder}/config.json', f'{local}/config.json'):
        try:
            with open(path, 'r') as rf:
                configs.append(json.load(rf))
        except (OSError, json.JSONDecodeError, ValueError):
            configs.append({})
    received, current = configs
    changed = [k for k in UPDATE_SETTINGS
               if k in received and received[k] != current.get(k)]
    if changed:
        current.update({k: received[k] for k in changed})
        with open(f'{local}/config.json', 'w') as wf:
            json.dump(current, wf, indent=2)
        report.append(f'Settings changed ({", ".join(changed)}); '
                      'restart Poodle for them to take effect.')

    return '\n'.join(report)


def last_update_backup(db=DB.name):
    """Path of the state saved by the last update_database(), or None."""
    path = f'{BASE_PATH}/databases/{db}/before_update'
    saved = sorted(os.listdir(path)) if os.path.isdir(path) else []
    return f'{path}/{saved[-1]}' if saved else None


def undo_last_update(db=DB.name) -> str:
    """
    Bring back the state saved by the last update_database(). The saved copy
    is removed afterwards, so calling this again goes one update further back.

    ----------------------------------------
    Dependencies: config, os, shutil, subprocess
    """
    saved = last_update_backup(db)
    if saved is None:
        raise RuntimeError('There is no update to undo.')
    local = f'{BASE_PATH}/databases/{db}'

    if os.path.isdir(f'{saved}/{db}'):
        _mongo_tool('mongorestore', '--drop', f'--nsInclude={db}.*', saved)
    else:
        # The database was empty before the update
        for collection in DB.list_collection_names():
            DB.drop_collection(collection)

    for name in UPDATE_FOLDERS:
        if os.path.isdir(f'{saved}/files/{name}'):
            _replace_folder(f'{saved}/files/{name}', f'{local}/{name}')
    if os.path.isfile(f'{saved}/files/config.json'):
        shutil.copy2(f'{saved}/files/config.json', f'{local}/config.json')

    shutil.rmtree(saved)
    name = os.path.basename(saved)
    return f'Restored the state from before the update of {name}.'


def yesno(prompt=''):
    choice = input(prompt)
    while choice.lower() != 'y' and choice.lower() != 'n':
        choice = input("Please type either 'y' or 'n'. ")

    return choice.lower()


def smart_input(prompt=''):
    """
    Input function that is able to distinguish between different storage types.
    Since it has to exclude placeholders from lists, this function will
    interpret nested lists as strings.

    Arguments:
    ----------
    prompt (str):
      Input prompt that will be displayed.

    ----------------
    Dependencies: re
    """
    input_obj = input(prompt)
    # Define storage types
    is_bool = re.compile(r'^True$|^False$')
    is_int = re.compile(r'^\d+$')
    is_float = re.compile(r'^\d+\.\d*$')
    is_str = re.compile(r'.+|$')
    is_list = re.compile(r'^\[.*\]$')
    is_tuple = re.compile(r'^\(.*\)$')
    is_dict = re.compile(r'^\{.*\}$')
    # Check for storage type
    storage_dict = {
        is_bool: 'bool', is_list: 'list', is_tuple: 'tuple', is_dict: 'dict',
        is_int: 'int', is_float: 'float', is_str: 'str'
    }
    # Different syntax needed for these storage types
    special_types = [is_bool, is_list, is_tuple, is_dict]

    for k, v in storage_dict.items():
        if k.match(input_obj) and k in special_types:
            return(eval(v + '(' + input_obj + ')'))
        elif k.match(input_obj):
            return(eval(v + '(input_obj)'))


def fast_input(options, prompt=''):
    """
    Input function that utilizes regular expressions to uniquely identify input
    among available options and minimize required typing.

    Arguments:
    ----------
    options (list):
      Available options that can be entered.
    prompt (str):
      Input prompt that will be displayed.

    ----------------
    Dependencies: re
    """

    def check(pattern):
        for o in options:
            if re.match(pattern, o):
                matches.append(o)
        return matches

    matches = []
    regex = re.compile(input(prompt) + '.*')
    # In case of no match
    while len(check(regex)) == 0:
        regex = input('Please choose one of the available options:\n' +
                      str(options) + '\n')
    # Pick unique match
    if len(matches) == 1:
        return matches[0]
    # Let user choose match if more than one
    else:
        choice = smart_input(f'Multiple matches: {matches}\nType index of desired match ' +
                             '(e.g. 1, 2, ...): ')
        while type(choice) != int or choice > len(matches):
            choice = smart_input('Please specify an integer index that is in range.\n')
        return matches[choice - 1]


def inspect_properties(dictionary, mode = 'standard', inspect = True, add = False):
    """
    The purpose of this function is to inspect and potentially modify the fields
    of a question.

    It will go through the keys and values of a dictionary and allows the user
    to make changes individually. It returns the dictionary including any
    changes made during inspection.

    Arguments:
    ----------
    dictionary (dict):
      Object that will be inspected.
    mode (str):
      Decides which keys (question fields) will be included in the inspection.
      The 'standard' setting excludes fields that should never change in case of
      an already created question. The 'specific' setting allows for inspection
      of specified keys. You can simply pass a field's name to only modify that
      field.
    inspect (bool):
      If set to True, the function will print the current values contained in
      the dictionary's keys.
    add (bool):
      If set to True, allows the user to add keys to the dictionary.

    ---------------------------
    Dependencies: re, pyperclip
    """

    # Set fixed_values according to mode
    if mode == 'standard':
        fixed_values = r'_id|name$|family_type|moodle_type|in_exams'
    elif mode == 'child':
        fixed_values = r'_id|name$|question$|family_type|moodle_type|in_exams'
    elif mode == 'parsingle':
        fixed_values = r'_id|name$|family_type|in_exams|moodle_type'
    elif mode == 'all':
        fixed_values = r'_id'
    elif mode == 'specific':
        inspect_keys = smart_input('Which fields do you wish to inspect/modify?\n' +
                                   '(Please input a list.)\n')
        # Insert each key into regular expression
        counter = 1
        fixed_values = r'^(?!.*('
        for key in inspect_keys:
            if counter == len(inspect_keys):
                fixed_values = fixed_values + r'%s$))' % (key)
            else:
                fixed_values = fixed_values + r'%s$|' % (key)
            counter += 1
    elif mode == 'none':
        fixed_values = r'.*'
    else:
        fixed_values = r'^(?!.*%s(?=$))' % (mode)

    ## Inspect/modify dictionary
    if inspect:
        for k, v in dictionary.items():
            if not bool(re.compile(fixed_values).match(str(k))):
                pyperclip.copy(str(v))
                prompt = (str(k) + ': ' + str(v) +
                  '\nDo you want to make any changes? (y/n)\n')
                if yesno(prompt) == 'y':
                    # Check for lists and apply special procedure
                    if type(v) == list:
                        counter = len(v)
                        for i in range(len(v)):
                            print('Element %d is: ' % (i+1) + "'" + str(v[i]) + "'")
                            new_value = smart_input(
                                'New value (press Enter to keep old value): '
                            )
                            if new_value != '':
                                dictionary[k][i] = new_value
                                print('New value has been set.')
                            counter -= 1
                        # Ask about adding values to empty or exhausted lists
                        while counter == 0:
                            if yesno('Do you want to add a value to the list? (y/n)\n') == 'y':
                                new_value = smart_input('New value: ')
                                dictionary[k].append(new_value)
                                print('New value has been added.')
                            else:
                                break
                    # Check for dictionaries and apply special procedure
                    elif type(v) == dict:
                        counter = len(v)
                        for kk, vv in v.items():
                            print('Current element: ' + str(kk) +
                                  '\nCurrent value: ' + str(vv)
                            )
                            new_value = smart_input(
                                'New value (press Enter to keep old value): '
                            )
                            if new_value != '':
                                dictionary[k][kk] = new_value
                                print('New value has been set.')
                            counter -= 1
                        # Ask about adding keys and values to empty
                        # or exhausted dictionaries
                        while counter == 0:
                            if yesno('Do you want to add a key to the dictionary? (y/n)\n') == 'y':
                                new_key = input('New key: ')
                                new_value = smart_input('New value: ')
                                dictionary[k][new_key] = new_value
                                print('New key and value have been added.')
                            else:
                                break
                    else:
                        dictionary[k] = smart_input('New value: ')
                        if k == 'name' and Q_CATEGORIES:
                            # Check for correct question naming scheme
                            # and duplicates
                            collection_names = [q['name'] for q in QUESTIONS.find()]
                            while (dictionary[k][:-4] not in Q_CATEGORIES or
                                   dictionary[k] in collection_names):
                                dictionary[k] = input('Please input a valid ' +
                                                      'question name: ')
                        print('New value has been set.')
                else:
                    print('No changes made.')

    ## Only modify dictionary
    else:
        for k, v in dictionary.items():
            if not bool(re.compile(fixed_values).match(str(k))):
                pyperclip.copy(str(v))
                print('Current field: ' + str(k))
                # Check for lists and apply special procedure
                if type(v) == list:
                    counter = len(v)
                    for i in range(len(v)):
                        new_value = smart_input(
                            'New value of element %d: ' % (i+1)
                        )
                        dictionary[k][i] = new_value
                        print('New value has been set.')
                        counter -= 1
                    # Ask about adding values to empty or exhausted lists
                    while counter == 0:
                        new_value = smart_input(
                            'New value to add to list ' +
                            '(press Enter to add no value): '
                        )
                        if new_value != '':
                            dictionary[k].append(new_value)
                            print('New value has been added.')
                        else:
                            break
                # Check for dictionaries and apply special procedure
                elif type(v) == dict:
                    counter = len(v)
                    for kk, vv in v.items():
                        print('Current element: ' + str(kk))
                        new_value = smart_input(
                            'New value (press Enter to keep old value): '
                        )
                        if new_value != '':
                            dictionary[k][kk] = new_value
                            print('New value has been set.')
                        counter -= 1
                    # Ask about adding keys and values to empty
                    # or exhausted dictionaries
                    while counter == 0:
                        new_key = input(
                            'New key to add to dictionary ' +
                            '(press Enter to add no key): '
                        )
                        if new_key != '':
                            new_value = smart_input('New value: ')
                            dictionary[k][new_key] = new_value
                            print('New key and value have been added.')
                        else:
                            break
                else:
                    dictionary[k] = smart_input('New value: ')
                    if k == 'name' and Q_CATEGORIES:
                        # Check for correct question naming scheme
                        # and duplicates
                        collection_names = [q['name'] for q in QUESTIONS.find()]
                        while (dictionary[k][:-4] not in Q_CATEGORIES or
                               dictionary[k] in collection_names):
                            dictionary[k] = input('Please input a valid ' +
                                                  'question name: ')
                    print('New value has been set.')

    if add:
        n_of_keys = smart_input('How many fields do you want to add?\n')
        for i in range(n_of_keys):
            add_key = input("Please specify the new field's name.\n")
            add_value = smart_input("Please specify the field's content.\n")
            dictionary[add_key] = add_value
            print('Field added.')
    return dictionary


## Exam creation

class MoodleQuestion(ET.ElementBase):

    def _init(self):
        self.tag = 'question'
        self.name = ET.SubElement(self, 'name')
        self.name_text = ET.SubElement(self.name, 'text')
        self.qt = ET.SubElement(self, 'questiontext', {'format': 'html'})
        self.qt_text = ET.SubElement(self.qt, 'text')
        self.gf = ET.SubElement(self, 'generalfeedback', {'format': 'html'})
        self.gf_text = ET.SubElement(self.gf, 'text')
        self.gf_text.text = ''
        self.dg = ET.SubElement(self, 'defaultgrade')
        self.penalty = ET.SubElement(self, 'penalty')
        self.penalty.text = '0.3333333'
        self.hidden = ET.SubElement(self, 'hidden')
        self.hidden.text = '0'
        self.idnumber = ET.SubElement(self, 'idnumber')
        self.idnumber.text = ''

    # A column with no header of its own is there to label the rows rather
    # than to carry figures, so it takes this share of a normal column's width.
    LABEL_COLUMN_WIDTH = 0.5

    @staticmethod
    def _narrow_columns(header):
        """Indexes of the columns that carry no header of their own."""
        narrow, index = set(), 0
        for item in header:
            names = item[1:] if isinstance(item, list) else [item]
            for name in names:
                if not str('' if name is None else name).strip():
                    narrow.add(index)
                index += 1
        return narrow

    @staticmethod
    def _column_widths(header):
        """Return width_of(index, span=1) giving each column's CSS width.

        Columns are equal except for those whose header is empty, which a
        spanning row header writes into and which stay narrow.
        """
        narrow = MoodleQuestion._narrow_columns(header)
        count = sum(len(h) - 1 if isinstance(h, list) else 1 for h in header)
        weights = [
            MoodleQuestion.LABEL_COLUMN_WIDTH if index in narrow else 1.0
            for index in range(count)
        ]
        total = sum(weights) or 1.0

        def width_of(index, span=1):
            share = sum(weights[index:index + span]) or 1.0
            return f'{100 * share / total:.4f}%'

        return width_of

    @staticmethod
    def _row_cells(row, start=0):
        """Walk a row as (value, colspan, index), honouring merged cells.

        A cell written as None is merged into the cell on its left, which is
        how a figure like a Fallzahl covers both columns of its group.
        """
        cells = []
        col = start
        while col < len(row):
            span = 1
            while col + span < len(row) and row[col + span] is None:
                span += 1
            value = row[col]
            cells.append(('' if value is None else value, span, col))
            col += span
        return cells

    @staticmethod
    def _table_to_html(data, row_headers=False):
        border = 'border-width: 1px; border-style: solid;'
        widths = MoodleQuestion._column_widths(data[0])
        col_w = widths(0)

        root = ET.Element('table', attrib={
            'style': 'table-layout: fixed; width: 100%;'
        })
        thead = ET.SubElement(root, 'thead')
        has_split = any(isinstance(h, list) for h in data[0])
        tr1 = ET.SubElement(thead, 'tr')
        sub_headers = []
        flat_index = 0
        for h in data[0]:
            if isinstance(h, list):
                n_sub = len(h) - 1
                th = ET.SubElement(tr1, 'th', attrib={
                    'scope': 'col',
                    'colspan': str(n_sub),
                    'style': (f'{border} text-align: center;'
                              f' font-weight: bold;'
                              f' width: {widths(flat_index, n_sub)};'),
                })
                th.text = str(h[0])
                sub_headers.extend((sub, flat_index + offset)
                                   for offset, sub in enumerate(h[1:]))
                flat_index += n_sub
            else:
                style = (f'{border} text-align: center;'
                         f' font-weight: bold; width: {widths(flat_index)};')
                attrib = {'scope': 'col', 'style': style}
                if has_split:
                    attrib['rowspan'] = '2'
                    attrib['style'] += ' vertical-align: middle;'
                th = ET.SubElement(tr1, 'th', attrib=attrib)
                th.text = str(h)
                flat_index += 1
        if has_split:
            tr2 = ET.SubElement(thead, 'tr')
            for sh, index in sub_headers:
                th = ET.SubElement(tr2, 'th', attrib={
                    'scope': 'col',
                    'style': (f'{border} text-align: center;'
                              f' font-weight: bold; width: {widths(index)};'),
                })
                th.text = str(sh)
        tbody = ET.SubElement(root, 'tbody')
        for item in data[1:]:
            if isinstance(item, dict) and 'group' in item:
                label = item['group']
                sub_rows = item['rows']
                n_sub = len(sub_rows)
                for si, sub_row in enumerate(sub_rows):
                    tr = ET.SubElement(tbody, 'tr')
                    if si == 0:
                        cell = ET.SubElement(tr, 'th', attrib={
                            'scope': 'rowgroup',
                            'rowspan': str(n_sub),
                            'style': (f'{border} text-align: center;'
                                      f' font-weight: bold; width: {col_w};'
                                      f' vertical-align: middle;'),
                        })  # col_w is column 0, where the header sits
                        cell.text = str(label)
                    # column 0 is occupied by the rowspan cell
                    for value, span, index in MoodleQuestion._row_cells(sub_row, 1):
                        attrib = {'style': (f'{border} text-align: center;'
                                            f' width: {widths(index, span)};')}
                        if span > 1:
                            attrib['colspan'] = str(span)
                        cell = ET.SubElement(tr, 'td', attrib=attrib)
                        cell.text = str(value)
            else:
                tr = ET.SubElement(tbody, 'tr')
                for value, span, index in MoodleQuestion._row_cells(item):
                    width = widths(index, span)
                    if row_headers and index == 0:
                        attrib = {'scope': 'row',
                                  'style': (f'{border} text-align: center;'
                                            f' font-weight: bold; width: {width};')}
                        tag = 'th'
                    else:
                        attrib = {'style': (f'{border} text-align: center;'
                                            f' width: {width};')}
                        tag = 'td'
                    if span > 1:
                        attrib['colspan'] = str(span)
                    cell = ET.SubElement(tr, tag, attrib=attrib)
                    cell.text = str(value)
        return root

    @staticmethod
    def make_tables(q, el):
        for m in re.finditer(r'(?<=\[\[)tbl\d+(?=\]\])', el.text):
            raw = q['tables'][m.group()]
            if isinstance(raw, dict):
                data = raw['data']
                row_headers = raw.get('row_headers', False)
            else:
                data = raw
                row_headers = False

            root = MoodleQuestion._table_to_html(data, row_headers)
            repl = ET.tostring(root, pretty_print=True).decode('utf-8')
            el.text = ET.CDATA(re.sub(r'\[\[%s\]\]' % (m.group()), repl, el.text))

    @staticmethod
    def encode_images(q, el):
        for m in re.finditer(r'(?<=\[\[file)\d+(?=\]\])', el.text):
            file_index = int(m.group()) - 1
            current_file = q['img_files'][file_index]
            file_format = re.search(r'(?<=\.)\D+$', current_file)
            file_format = file_format.group()
            with open(f'{BASE_PATH}/databases/{DB.name}/img/' + current_file, 'rb') as rf:
                b64 = base64.b64encode(rf.read()).decode('utf-8')
            repl = f'<img src="data:image/{file_format};base64,{b64}" alt="" />'
            el.text = ET.CDATA(re.sub(r'\[\[file%s\]\]' % (m.group()), repl, el.text))

    def set_defaults(self, q):
        self.name_text.text = q['name']
        self.qt_text.text = ET.CDATA(q['question'])
        self.__class__.make_tables(q, self.qt_text)
        self.__class__.encode_images(q, self.qt_text)
        self.dg.text = str(q['points'])
        self.loc = self.find('idnumber')

    def feedback(self):
        self.loc.addnext(ET.SubElement(self, 'correctfeedback', attrib={'format': 'html'}))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = 'Die Antwort ist richtig.'

        self.loc.addnext(ET.SubElement(self, 'partiallycorrectfeedback', attrib={'format': 'html'}))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = 'Die Antwort ist teilweise richtig.'

        self.loc.addnext(ET.SubElement(self, 'incorrectfeedback', attrib={'format': 'html'}))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = 'Die Antwort ist falsch.'


class MultichoiceQuestion(MoodleQuestion):

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'single'))
        self.loc = self.loc.getnext()
        self.single = False
        if len(q['correct_answers']) == 1:
            self.single = True
        try:
            self.single = q['single']
        except KeyError:
            pass
        self.loc.text = str(bool(self.single)).lower()

        self.loc.addnext(ET.SubElement(self, 'shuffleanswers'))
        self.loc = self.loc.getnext()
        self.loc.text = str(bool(SHUFFLE)).lower()

        self.loc.addnext(ET.SubElement(self, 'answernumbering'))
        self.loc = self.loc.getnext()
        self.loc.text = 'abc'

        self.loc.addnext(ET.SubElement(self, 'showstandardinstruction'))
        self.loc = self.loc.getnext()
        self.loc.text = '1'

        self.feedback()

        self.loc.addnext(ET.SubElement(self, 'shownumcorrect'))
        self.loc = self.loc.getnext()

        for a in q['correct_answers']:
            fraction = '%f' % (100./len(q['correct_answers']))
            self.loc.addnext(ET.SubElement(self, 'answer', attrib={
                'fraction': fraction, 'format': 'html'
            }))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = ET.CDATA(str(a))
            self.__class__.encode_images(q, child)
            child = ET.SubElement(self.loc, 'feedback', attrib={'format': 'html'})
            child = ET.SubElement(self.loc.find('feedback'), 'text')
            child.text = ''
        for a in q['false_answers']:
            if self.single:
                self.loc.addnext(ET.SubElement(self, 'answer', attrib={
                    'fraction': '0', 'format': 'html'
                }))
            else:
                self.loc.addnext(ET.SubElement(self, 'answer', attrib={
                    'fraction': '-%f' % (100./len(q['correct_answers'])),
                    'format': 'html'
                }))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = ET.CDATA(str(a))
            self.__class__.encode_images(q, child)
            child = ET.SubElement(self.loc, 'feedback', attrib={'format': 'html'})
            child = ET.SubElement(self.loc.find('feedback'), 'text')
            child.text = ''


class NumericalQuestion(MoodleQuestion):

    def set_additional(self, q):
        for a in q['correct_answers']:
            self.loc.addnext(ET.SubElement(self, 'answer', attrib={
                'fraction': '100', 'format': 'moodle_auto_format'
            }))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = str(a)
            child = ET.SubElement(self.loc, 'feedback', attrib={'format': 'html'})
            child = ET.SubElement(self.loc.find('feedback'), 'text')
            child.text = ''
            child = ET.SubElement(self.loc, 'tolerance')
            try:
                child.text = str(q['tolerance'])
            except Exception:
                child.text = '0'

        self.loc.addnext(ET.SubElement(self, 'unitgradingtype'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'unitpenalty'))
        self.loc = self.loc.getnext()
        self.loc.text = '0.1000000'

        self.loc.addnext(ET.SubElement(self, 'showunits'))
        self.loc = self.loc.getnext()
        self.loc.text = '3'

        self.loc.addnext(ET.SubElement(self, 'unitsleft'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'


class ShortanswerQuestion(MoodleQuestion):

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'usecase'))
        self.loc = self.loc.getnext()
        try:
            self.loc.text = str(int(q['usecase']))
        except KeyError:
            self.loc.text = '0'

        for a in q['correct_answers']:
            self.loc.addnext(ET.SubElement(self, 'answer', attrib={
                'fraction': '100', 'format': 'moodle_auto_format'
            }))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = str(a)
            child = ET.SubElement(self.loc, 'feedback', attrib={'format': 'html'})
            child = ET.SubElement(self.loc.find('feedback'), 'text')
            child.text = ''


class EssayQuestion(MoodleQuestion):

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'responseformat'))
        self.loc = self.loc.getnext()
        self.loc.text = 'noinline'

        self.loc.addnext(ET.SubElement(self, 'responserequired'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'responsefieldlines'))
        self.loc = self.loc.getnext()
        self.loc.text = '15'

        self.loc.addnext(ET.SubElement(self, 'attachments'))
        self.loc = self.loc.getnext()
        self.loc.text = str(q['answer_files'][0])

        self.loc.addnext(ET.SubElement(self, 'attachmentsrequired'))
        self.loc = self.loc.getnext()
        self.loc.text = str(q['answer_files'][1])

        self.loc.addnext(ET.SubElement(self, 'filetypeslist'))
        self.loc = self.loc.getnext()
        self.loc.text = ''

        self.loc.addnext(ET.SubElement(self, 'graderinfo', attrib={'format': 'html'}))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = ''

        self.loc.addnext(ET.SubElement(self, 'responsetemplate', attrib={'format': 'html'}))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = ''


class MatchingQuestion(MoodleQuestion):

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'shuffleanswers'))
        self.loc = self.loc.getnext()
        self.loc.text = str(bool(SHUFFLE)).lower()

        self.feedback()

        for k, v in q['correct_answers'].items():
            self.loc.addnext(ET.SubElement(self, 'subquestion', attrib={'format': 'html'}))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = ET.CDATA(str(k))
            self.__class__.encode_images(q, child)
            child = ET.SubElement(self.loc, 'answer')
            child = ET.SubElement(child, 'text')
            child.text = ET.CDATA(str(v))
            self.__class__.encode_images(q, child)

        try:
            for a in q['false_answers']:
                self.loc.addnext(ET.SubElement(self, 'subquestion', attrib={'format': 'html'}))
                self.loc = self.loc.getnext()
                child = ET.SubElement(self.loc, 'text')
                child.text = ''
                child = ET.SubElement(self.loc, 'answer')
                child = ET.SubElement(child, 'text')
                child.text = ET.CDATA(str(a))
                self.__class__.encode_images(q, child)
        except Exception:
            pass


class GapselectQuestion(MoodleQuestion):

    @staticmethod
    def insert_indices(q, el):
        for k, v in q['correct_answers'].items():
            pattern = r'(?<=\[\[){value}(?=\]\])'.format(value=re.escape(str(v[0])))
            el.text = re.sub(pattern, str(k), el.text)

    def set_option(self, a, g):
        self.loc.addnext(ET.SubElement(self, 'selectoption'))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = ET.CDATA(a)
        child = ET.SubElement(self.loc, 'group')
        child.text = g

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'shuffleanswers'))
        self.loc = self.loc.getnext()
        self.loc.text = str(bool(SHUFFLE)).lower()

        self.feedback()

        self.loc.addnext(ET.SubElement(self, 'shownumcorrect'))
        self.loc = self.loc.getnext()

        # Modify question text indices
        self.__class__.insert_indices(q, self.qt_text)

        # Add options
        for k, v in q['correct_answers'].items():
            self.set_option(str(v[0]), str(k))

        for k, v in q['false_answers'].items():
            for i in v:
                self.set_option(str(i), str(k))


class DdimageortextQuestion(MoodleQuestion):

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'shuffleanswers'))
        self.loc = self.loc.getnext()
        self.loc.text = str(bool(SHUFFLE)).lower()

        self.feedback()

        self.loc.addnext(ET.SubElement(self, 'shownumcorrect'))
        self.loc = self.loc.getnext()

        self.loc.addnext(ET.SubElement(self, 'file', attrib={'name': q['img_files'][0], 'encoding': 'base64'}))
        self.loc = self.loc.getnext()

        with open(f'{BASE_PATH}/databases/{DB.name}/img/' + q['img_files'][0], 'rb') as rf:
            b64 = base64.b64encode(rf.read())
        self.loc.text = b64.decode('utf-8')

        for a in q['correct_answers']:
            self.loc.addnext(ET.SubElement(self, 'drag'))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'no')
            child.text = str(q['correct_answers'].index(a)+1)
            child = ET.SubElement(self.loc, 'text')
            child.text = ET.CDATA(a)
            child = ET.SubElement(self.loc, 'draggroup')
            child.text = '1'

        for k, v in q['drops'].items():
            self.loc.addnext(ET.SubElement(self, 'drop'))
            self.loc = self.loc.getnext()
            child = ET.SubElement(self.loc, 'text')
            child.text = ''
            child = ET.SubElement(self.loc, 'no')
            child.text = str(k)
            child = ET.SubElement(self.loc, 'choice')
            child.text = str(k)
            child = ET.SubElement(self.loc, 'xleft')
            child.text = str(v[0])
            child = ET.SubElement(self.loc, 'ytop')
            child.text = str(v[1])


class CalculatedQuestion(MoodleQuestion):

    @staticmethod
    def count_decimals(arr):
        pattern = r'(?<=\.)[0-9e+-]*'
        
        def get_len(n):
            if np.int64(n) == n:
                return 0
            elif not re.search(r'e', str(n)):
                return len(re.search(pattern, str(n)).group())
            elif re.search(r'e\+', str(n)):
                return 0
            elif re.search(r'e\-', str(n)):
                return int(re.search(r'(?<=e\-)[0-9]+', str(n)).group()) - 1
            else:
                raise ValueError
        get_lens = np.vectorize(get_len)
    
        lens = get_lens(arr)
        return np.max(lens)

    def set_additional(self, q):
        self.loc.addnext(ET.SubElement(self, 'synchronize'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'single'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'shuffleanswers'))
        self.loc = self.loc.getnext()
        self.loc.text = str(bool(SHUFFLE)).lower()

        self.loc.addnext(ET.SubElement(self, 'answernumbering'))
        self.loc = self.loc.getnext()
        self.loc.text = 'abc'

        self.feedback()

        self.loc.addnext(ET.SubElement(self, 'answer', attrib={
            'fraction': "100"
        }))
        self.loc = self.loc.getnext()
        child = ET.SubElement(self.loc, 'text')
        child.text = q['correct_answers'][0]
        child = ET.SubElement(self.loc, 'tolerance')
        child.text = str(q['tolerance'][0])
        child = ET.SubElement(self.loc, 'tolerancetype')
        if q['tolerance'][1] == 'relative':
            child.text = '1'
        elif q['tolerance'][1] == 'nominal':
            child.text = '2'
        elif q['tolerance'][1] == 'geometric':
            child.text = '3'
        child = ET.SubElement(self.loc, 'correctanswerformat')
        child.text = '1'
        child = ET.SubElement(self.loc, 'correctanswerlength')
        child.text = str(q['tolerance'][2])

        child = ET.SubElement(self.loc, 'feedback', attrib={
            'format': "html"
        })
        child = ET.SubElement(child, 'text')
        child.text = ''

        self.loc.addnext(ET.SubElement(self, 'unitgradingtype'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'unitpenalty'))
        self.loc = self.loc.getnext()
        self.loc.text = '0.1000000'

        self.loc.addnext(ET.SubElement(self, 'showunits'))
        self.loc = self.loc.getnext()
        self.loc.text = '3'

        self.loc.addnext(ET.SubElement(self, 'unitsleft'))
        self.loc = self.loc.getnext()
        self.loc.text = '0'

        self.loc.addnext(ET.SubElement(self, 'dataset_definitions'))
        self.loc = self.loc.getnext()
        
        # Create all vars
        code = f'from databases.{DB.name}.random_vars.rv_{q["name"]} import *'
        rvn = {}
        exec(code, rvn)
        for v in q['vars']:
            datadef = ET.SubElement(self.loc, 'dataset_definition')

            child = ET.SubElement(datadef, 'status')
            subchild = ET.SubElement(child, 'text')
            subchild.text = 'private'

            child = ET.SubElement(datadef, 'name')
            subchild = ET.SubElement(child, 'text')
            subchild.text = f'{v}'

            child = ET.SubElement(datadef, 'type')
            child.text = 'calculated'

            child = ET.SubElement(datadef, 'distribution')
            subchild = ET.SubElement(child, 'text')
            subchild.text = 'uniform'

            child = ET.SubElement(datadef, 'minimum')
            subchild = ET.SubElement(child, 'text')
            subchild.text = f'{np.floor(np.min(rvn[v]))}'

            child = ET.SubElement(datadef, 'maximum')
            subchild = ET.SubElement(child, 'text')
            subchild.text = f'{np.ceil(np.max(rvn[v]))}'

            child = ET.SubElement(datadef, 'decimals')
            subchild = ET.SubElement(child, 'text')
            decimals = self.__class__.count_decimals(rvn[v])
            subchild.text = str(decimals)

            child = ET.SubElement(datadef, 'itemcount')
            child.text = str(len(rvn[v]))

            d_items = ET.SubElement(datadef, 'dataset_items')

            for i, n in zip(rvn[v], range(len(rvn[v]))):
                child = ET.SubElement(d_items, 'dataset_item')
                subchild = ET.SubElement(child, 'number')
                subchild.text = str(n+1)
                subchild = ET.SubElement(child, 'value')
                if decimals == 0:
                    subchild.text = str(np.int64(i))
                else:
                    subchild.text = str(i)

            child = ET.SubElement(datadef, 'number_of_items')
            child.text = str(len(rvn[v]))


def create_xml(exam, filename='import.xml', mode='terminal', questions=None):
    # Create directory
    try:
        os.mkdir(f'{BASE_PATH}/databases/{DB.name}/exams/{exam}')
    except FileExistsError:
        pass
    # Possibly adjust filename
    if filename[-4:] != '.xml':
        filename += '.xml'
    # Don't overwrite existing files
    version = 0
    pattern = re.compile(r'^.+?(?=[-0-9]*\.xml)')
    while filename in os.listdir(f'{BASE_PATH}/databases/{DB.name}/exams/{exam}'):
        version += 1
        m = re.match(pattern, filename)
        filename = m.group() + f'-{version}.xml'

    # Create XML base document
    xml_string = (
        '<?xml version="1.0"?>\n'
        '<quiz>\n\n'
        '<!-- question: 0  -->\n'
        '  <question type="category">\n'
        '    <category>\n'
        f'      <text>$course$/top/{exam}</text>\n'
        '    </category>\n'
        '    <info format="moodle_auto_format">\n'
        '      <text></text>\n'
        '    </info>\n'
        '    <idnumber></idnumber>\n'
        '  </question>\n\n'
        '</quiz>'
    )
    root = ET.XML(xml_string)

    def gather_info(ql):
        time_est_total = sum([QUESTIONS.find_one({'name': q})['time_est']
                    for q in ql])
        difficulty_avg = np.round(np.mean(
            [QUESTIONS.find_one({'name': q})['difficulty'] for q in ql]), 2)
        max_points = sum([QUESTIONS.find_one({'name': q})['points'] for q in ql])

        return (time_est_total, difficulty_avg, max_points)

    def questionlist_delete(ql):
        if len(ql) == 0:
            print('No questions in question list!')

            return None

        else:
            del_choice = fast_input(ql,
                                    ('Please input the name of the question '
                                     'you wish to delete.\n')
                                    )
            while del_choice not in ql:
                del_choice = fast_input(ql,
                                        ('Input the name of a question which '
                                         'is in the question list.\n')
                                        )
            ql.remove(del_choice)
            print(f'Question {del_choice} removed from question list.')

            return None

    def questionlist_auto(questions=None):
        if questions == None:
            # Open question list file
            listfile = input(
                ('Please specify whitespace-separated file which '
                 'contains the list of questions.\n')
            )
            while os.path.isfile(listfile) == False:
                listfile = input('Please input correct path/filename: ')
            with open(listfile, 'r') as rf:
                questionlist = rf.read().split()
        else:
            questionlist = questions

        # Clean question list
        questionlist_copy = copy.copy(questionlist)
        for q in questionlist_copy:
            if QUESTIONS.find_one({'name': q}) == None:
                questionlist.remove(q)
                print(
                    (f'Question {q} not in database! '
                      'Question removed from question list.')
                )

        # Get exam info
        info = gather_info(questionlist)

        return questionlist, info

    def questionlist_manual():
        # Category patterns for separated output
        if Q_CATEGORIES:
            cat_patterns = []
            for c in Q_CATEGORIES:
                cat_patterns.append(re.compile(r'%s\d+' % (c)))

        # Create question list
        questionlist = []
        info = ()
        q_choice = ''
        while q_choice.lower() != 'done' and q_choice.lower() != 'd':
            q_choice = input(('\nPlease input the name of the next question '
                                   "you wish to add.\nInput 'done' if the question "
                                   "list is complete.\nInput 'delete' if you want "
                                   'to remove a question from the list.\n'))

            if q_choice in questionlist:
                print(f'Question {q_choice} already in question list!')
            elif q_choice.lower() == 'delete' or q_choice.lower() == 'del':
                questionlist_delete(questionlist)
            elif (QUESTIONS.find_one({'name': q_choice}) == None and
                  q_choice.lower() != 'done' and q_choice.lower() != 'd'):
                print(f'Question {q_choice} not in database!')
            elif QUESTIONS.find_one({'name': q_choice}) != None:
                questionlist.append(q_choice)

                # Question list status
                if Q_CATEGORIES:
                    for r in cat_patterns:
                        print(list(filter(r.match, questionlist)))
                else:
                    pprint(questionlist)

                # Print current exam info
                info = gather_info(questionlist)
                print('Current estimated time:', info[0],
                      '\nCurrent average difficulty:', info[1],
                      '\nCurrent maximum points:', info[2])
            
        return questionlist, info

    # Choose question list creation mode
    if mode == 'terminal':
        mode_choice = fast_input(['auto', 'manual'],
                                 ('Please select a mode for question list creation. '
                                  "(Available: 'auto' or 'manual')\n")
                                 )
        if mode_choice == 'auto':
            questionlist, info = questionlist_auto()
        elif mode_choice == 'manual':
            questionlist, info = questionlist_manual()
    elif mode == 'gui':
        questionlist, info = questionlist_auto(questions)


    for q in questionlist:
        q_dict = QUESTIONS.find_one({'name': q})
        try:
            # Print question details before processing
            print(f'Processing question: {q}')
            print(f'Question details (q_dict): {q_dict}')
        
            # Try to create the question element
            q_el = eval((
                f'{q_dict["moodle_type"].capitalize()}'
                f'Question(attrib={{"type": "{q_dict["moodle_type"]}"}})'
            ))
            print(f'Created question element: {q_el}')

            # Set defaults and additional attributes
            q_el.set_defaults(q_dict)
            print('Set defaults successfully.')
        
            q_el.set_additional(q_dict)
            print('Set additional attributes successfully.')

            # Append question element to the XML root
            root.append(q_el)
            print(f'Successfully appended question {q} to XML.')
        
        except KeyError as ke:
            # If a key is missing in q_dict
            print(f'KeyError with question {q}: {ke}')
            print(f'Missing key in question dict: {q_dict}')
        
        except AttributeError as ae:
            # If q_el or q_dict has missing attributes or methods
            print(f'AttributeError with question {q}: {ae}')
            print(f'Question dict (q_dict): {q_dict}')
            print(f'Possible missing method or attribute in q_el or q_dict.')
        
        except Exception as e:
            # Catch any other exceptions and print a detailed message
            print(f'Question {q} has errors! {e}')
            print(f'Error occurred while processing question: {q}')
            print(f'Question dict (q_dict): {q_dict}')
            print(f'Failed question element (q_el if created): {locals().get("q_el")}')
            

    with open(f'{BASE_PATH}/databases/{DB.name}/exams/{exam}/{filename}', 'w') as wf:
        wf.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        wf.write((f'<!-- Estimated time: {info[0]}, '
                  f'average difficulty: {info[1]}, '
                  f'maximum possible points: {info[2]} -->\n')
                )
        wf.write(ET.tostring(root, pretty_print=True).decode('utf-8'))

    print('Import file successfully created.')

    return questionlist, info
