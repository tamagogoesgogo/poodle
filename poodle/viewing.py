from config import *
import gui.windows

from pprint import pprint
import re
import numpy as np
import pandas as pd


def view(collection, search=None, field='name'):
    """
    Simple function to examine questions from the database. Pass 'any' to field
    argument to search all available question fields for (non-list) search
    argument.

    Arguments:
    ----------
    collection (var):
      Determines which collection is being searched (QUESTIONS and EXAMS are standard).
    search (any/list):
      Search criterion that will be applied to the field. If passed as list,
      multiple criteria will be applied.
    field (str/list):
      Question field to look through with search argument. If passed as list,
      multiple fields will be looked through.

    --------------------
    Dependencies: config, pprint, re
    """

    if field == 'any':
        # Determine all existing question fields
        fields = {}
        for q in collection.find():
            fields |= q.keys()
        fields.discard('_id')
        for f in fields:
            try:
                for q in collection.find({f: re.compile(search)}):
                    pprint(q)
            except:
                for q in collection.find({f: search}):
                    pprint(q)
    elif not (type(search) == list or type(field) == list):
        if search==None:
            for q in collection.find():
                pprint(q)
        else:
            try:
                for q in collection.find({field: re.compile(search)}):
                    pprint(q)
            except:
                for q in collection.find({field: search}):
                    pprint(q)
    else:
        # Transform into list if needed
        if type(search) != list:
            search = [search] * len(field)
        elif type(field) != list:
            field = [field] * len(search)
        # Combine lists into dictionary
        dictionary = dict(zip(field, search))
        # Turn strings into compiled regular expressions
        for q in collection.find(
                {k: (re.compile(v) if type(v)==str else v)
                 for (k, v) in dictionary.items()}
        ):
            pprint(q)


def qt_overview() -> None:
    """
    Launch the main GUI window (blocks until the window is closed).

    Dependencies: PySide6, gui.windows
    """
    import sys
    import os
    from PySide6.QtWidgets import QApplication, QStyleFactory
    import gui.theming

    # Prevent the GTK/system platform theme from overriding QSS
    os.environ['QT_QPA_PLATFORMTHEME'] = ''
    os.environ['QT_STYLE_OVERRIDE'] = 'Fusion'

    global _APP
    # Held module-level: a QApplication in a local would be destroyed when this
    # function returns, while its windows are still alive.
    _APP = QApplication.instance() or QApplication(sys.argv)
    app = _APP
    app.setStyle(QStyleFactory.create('Fusion'))
    print('[poodle] Qt style set to Fusion')

    # Loads style.qss and applies the text size stored for this database
    gui.theming.load()
    print(f'[poodle] {gui.theming.palette_name()} theme, '
          f'text size {gui.theming.size()}px (Ctrl+± to change)')

    win = gui.windows.MainWindow()
    win.show()
    # TEMPORARY test of the automatic update from GitHub: remove this commit
    # with `git revert` once the message has been seen on another computer.
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: gui.dialogs.OKDialog(
        win, 'GitHub update test 2',
        'If you can read this, this Poodle has updated itself from GitHub (test 2).'
    )._run())
    app.exec()

    # Leave nothing open: a surviving window would keep the next qt_overview()
    # from ever returning to the prompt.
    for window in list(gui.windows._OPEN_WINDOWS):
        window.close()

    if gui.windows.RESTART_INTO:
        _restart_poodle(gui.windows.RESTART_INTO)


def _restart_poodle(db: str) -> None:
    """
    Replace this Python process with a fresh one running launch.py with the
    same arguments, but database db, so every module is read anew. The
    terminal, the MongoDB daemon and launch.sh carry on as they were;
    POODLE_OPEN_GUI tells the new process to open the GUI straight away.
    """
    import sys
    import os

    print(f'\n[poodle] Restarting into {db}…\n')
    sys.stdout.flush()
    sys.stderr.flush()
    os.environ['POODLE_OPEN_GUI'] = '1'
    launch = os.path.abspath(sys.argv[0])
    os.execv(sys.executable, [sys.executable, '-i', launch, *sys.argv[1:-1], db])


# Backward-compatible alias
gtk_overview = qt_overview


def export_overview(path=BASE_PATH, filename='overview', candidates=None):
    """
    Export an overview of the database as a csv file. See overview() function's
    docstring for an explanation of cell values.

    Arguments:
    ----------
    path (str):
      Directory to which the output file will be saved.
    filename (str):
      Name of the output file.
    candidates (bool):
      If set to True, will only show possible candidates for inclusion in the
      next exam and will exclude questions that appeared in the last exam or in
      the mock exam.

    ---------------------------
    Dependencies: numpy, pandas
    """

    # Generate dataframe
    exam_list = sorted([e['name'] for e in EXAMS.find()])
    data = pd.DataFrame(sorted(
        [
            [q['name'], q['difficulty'], q['time_est']] +
            [np.round(q['in_exams'][e] / q['points'], 2)
             if e in q['in_exams'] else '.' for e in exam_list
            ]
            for q in QUESTIONS.find() if q['name'][-2:] != '00'
        ]),
        columns = ['question', 'difficulty', 'time'] + exam_list
    )
    appeared = pd.DataFrame(np.array(
        [[int(type(e) == float) for e in data[q]] for q in exam_list]).T
    )
    data.insert(1, 'appearances', appeared.sum(axis=1))

    if candidates:
        data = data[(data['mock'] == '.') & (data[exam_list[-2]] == '.')]
        data = data.drop(labels=[exam_list[-2], 'mock'], axis=1)

    # Export dataframe
    data.to_csv(f'{path}/{filename}.csv', na_rep='NaN')
    print(f'Overview saved as:\n{path}/{filename}.csv')
