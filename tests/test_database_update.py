"""End-to-end test of core.update_database() / undo_last_update().

Needs a running mongod on localhost:$POODLE_TEST_PORT (default 27017) and a
copy
as the "received" folder. Works in a throwaway database 'updtest' and removes
it, and databases/updtest/, afterwards.

Run from the repository root:  venv/bin/python tests/test_database_update.py
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'poodle')]
PORT = os.environ.get('POODLE_TEST_PORT', '27017')
sys.argv = ['launch.py', f'mongodb://localhost:{PORT}', 'updtest']
sys.stdin = io.StringIO('0\n')          # Q_CATEGORIES prompt of a new database

import core                              # noqa: E402

DB = core.DB
LOCAL = f'{ROOT}/databases/updtest'
SOURCE_DB = f'{ROOT}/databases/methoden1b'


def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond:
        raise SystemExit(1)


def main(tmp):
    received = f'{tmp}/methoden1b'
    shutil.copytree(SOURCE_DB, received)
    backups = sorted(os.listdir(f'{received}/backup'))

    # Local state: the OLDEST backup, plus a local edit and a local-only file
    subprocess.run(['mongorestore', f'--uri=mongodb://localhost:{PORT}', '--drop', '--nsInclude=methoden1b.*',
                    '--nsFrom=methoden1b.*', '--nsTo=updtest.*',
                    f'{received}/backup/{backups[0]}'],
                   check=True, capture_output=True)
    q = DB.questions.find_one()
    DB.questions.update_one({'_id': q['_id']}, {'$set': {'question': 'LOCAL EDIT'}})
    with open(f'{LOCAL}/img/local_only.png', 'w') as wf:
        wf.write('x')
    before = {c: DB[c].count_documents({}) for c in ('questions', 'exams')}

    info = core.inspect_update(received)
    check(info['dump'].endswith(backups[-1]), 'newest backup chosen')
    check(info['dump_db'] == 'methoden1b', 'dump database name read')
    check(info['counts']['questions'][1] == before['questions'], 'current counts')

    try:
        core.inspect_update(LOCAL)
        check(False, 'own folder rejected')
    except ValueError:
        check(True, 'own folder rejected')

    print(core.update_database(received))
    for c, (new, _) in info['counts'].items():
        check(DB[c].count_documents({}) == new, f'{c} has {new} documents')
    after = DB.questions.find_one({'_id': q['_id']})
    check(after is None or after['question'] != 'LOCAL EDIT',
          'existing question overwritten (the old restore() skipped it)')
    check(sorted(os.listdir(f'{LOCAL}/img')) == sorted(os.listdir(f'{received}/img')),
          'img/ mirrors the received folder')
    check(os.path.basename(info['dump']) in os.listdir(f'{LOCAL}/backup'),
          'restored backup added to the local backups')
    check(core.last_update_backup() is not None, 'state saved before update')

    print(core.undo_last_update())
    check(DB.questions.find_one({'_id': q['_id']})['question'] == 'LOCAL EDIT',
          'undo brings back the local edit')
    check({c: DB[c].count_documents({}) for c in ('questions', 'exams')} == before,
          'undo brings back the counts')
    check(os.path.exists(f'{LOCAL}/img/local_only.png'), 'undo brings back files')
    check(core.last_update_backup() is None, 'saved state removed after undo')

    # A failing restore must leave the database as it was
    broken = f'{tmp}/broken/backup/2099-01-01_00-00-00/methoden1b'
    os.makedirs(broken)
    with open(f'{broken}/questions.bson', 'wb') as wf:
        wf.write(b'\x05\x00\x00\x00garbage')
    try:
        core.update_database(f'{tmp}/broken')
        check(False, 'broken dump raises')
    except Exception as e:
        check(True, f'broken dump raises ({type(e).__name__})')
    check(DB.questions.find_one({'_id': q['_id']})['question'] == 'LOCAL EDIT',
          'database unchanged after failed update')

    # The layout sent from the server, as a .zip: methoden1b/ holding its
    # backup folder directly (no backup/), img/ and random_vars/, no exams/
    sent = f'{tmp}/sent/methoden1b'
    os.makedirs(sent)
    shutil.copytree(f'{received}/backup/{backups[-1]}', f'{sent}/{backups[-1]}')
    shutil.copytree(f'{received}/img', f'{sent}/img')
    shutil.copytree(f'{received}/random_vars', f'{sent}/random_vars')
    zipped = shutil.make_archive(f'{tmp}/methoden1b(1)', 'zip', f'{tmp}/sent')
    zinfo = core.inspect_update(zipped)
    check(zinfo['taken'].replace(' ', '_').replace(':', '-') == backups[-1][:16],
          'zip in server layout: newest backup found')
    check(zinfo['files']['img'] == len(os.listdir(f'{received}/img'))
          and zinfo['files']['exams'] is None, 'zip: files counted, exams/ absent')
    shutil.rmtree(f'{LOCAL}/img')
    os.makedirs(f'{LOCAL}/img')
    print(core.update_database(zipped))
    check(sorted(os.listdir(f'{LOCAL}/img')) == sorted(os.listdir(f'{received}/img')),
          'zip: img/ replaced')
    check(os.path.isdir(f'{LOCAL}/exams'), 'zip: exams/ kept')
    check(DB.questions.count_documents({}) == info['counts']['questions'][0],
          'zip: database replaced')
    print(core.undo_last_update())

    # An older version is flagged
    old_sent = f'{tmp}/old/methoden1b'
    shutil.copytree(f'{received}/backup/{backups[0]}', f'{old_sent}/{backups[0]}')
    shutil.copytree(f'{received}/backup/{backups[-1]}', f'{LOCAL}/backup/{backups[-1]}',
                    dirs_exist_ok=True)
    check(core.inspect_update(f'{tmp}/old')['newer_local'] == backups[-1],
          'older update flagged')

    # mongorestore failing halfway: --drop has already emptied a collection
    real_tool = core._mongo_tool

    def failing_tool(tool, *args):
        # The update's restore, not the rollback from before_update/
        if tool == 'mongorestore' and 'before_update' not in args[-1]:
            DB.questions.drop()
            raise RuntimeError('mongorestore failed: simulated')
        return real_tool(tool, *args)

    core._mongo_tool = failing_tool
    try:
        core.update_database(received)
        check(False, 'failed restore raises')
    except RuntimeError as e:
        check('left as it was' in str(e), 'failed restore raises')
    finally:
        core._mongo_tool = real_tool
    check(DB.questions.find_one({'_id': q['_id']})['question'] == 'LOCAL EDIT',
          'rolled back after mongorestore failed halfway')
    check(core.last_update_backup() is None, 'rollback consumed its saved state')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        try:
            main(tmp)
        finally:
            core.CLIENT.drop_database('updtest')
            shutil.rmtree(LOCAL, ignore_errors=True)
    print('all passed')
