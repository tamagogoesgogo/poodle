from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QScrollArea, QSplitter, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QStackedWidget, QSpinBox, QMenu
)
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QKeySequence, QShortcut
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except ImportError:
    _HAS_WEBENGINE = False

from poodle import config
from poodle import exam
import core
import gui.treeviews
import gui.panels
import gui.dialogs
import gui.notebooks
import gui.theming
import contextlib
import html
import io
import os
import sys
import tempfile
import threading
import numpy as np
import pandas as pd


# Qt does not take ownership of a window that has no parent widget, so Python
# drops its last reference the moment the handler that opened it returns and
# the window is destroyed before it can be seen. Every window registers itself
# here for as long as it is open.
_OPEN_WINDOWS = set()

# The database to start Poodle into once the GUI has closed, set by
# MainWindow.restart(); qt_overview() then relaunches. Only a session started
# by launch.py can be started again.
RESTART_INTO = None
CAN_RESTART = os.path.basename(sys.argv[0]) == 'launch.py'


class _PoodleWindow(QWidget):
    """Base for Poodle's top-level windows: stays alive while it is open."""

    def __init__(self):
        super().__init__()
        _OPEN_WINDOWS.add(self)

    def showEvent(self, event):
        _OPEN_WINDOWS.add(self)
        super().showEvent(event)

    def closeEvent(self, event):
        _OPEN_WINDOWS.discard(self)
        super().closeEvent(event)


def _poodle_databases() -> list:
    """Databases with a folder of their own under databases/."""
    base = f'{config.BASE_PATH}/databases'
    return sorted(
        name for name in os.listdir(base)
        if name.isalnum() and os.path.isfile(f'{base}/{name}/config.json')
    )


class MainWindow(_PoodleWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Poodle — {config.DB.name}')
        self.resize(1350, 900)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notebook = gui.notebooks.MainNotebook(self)
        self.notebook.setCornerWidget(self._top_bar(), Qt.Corner.TopRightCorner)
        layout.addWidget(self.notebook, stretch=1)

        # Two control panels in a stacked widget; MainNotebook swaps them on tab
        # change. No fixed height: the panels size themselves to the text size.
        self.stacked_control = QStackedWidget()
        self.question_control = gui.panels.MainQuestionControlPanel(self)
        self.exam_control = gui.panels.MainExamControlPanel(self)
        self.stacked_control.addWidget(self.question_control)
        self.stacked_control.addWidget(self.exam_control)
        layout.addWidget(self.stacked_control)

        # Default active control panel (Questions tab is shown first)
        self.control = self.question_control

        # Text size from the keyboard, from whichever window has focus
        for sequence, handler in (
            ('Ctrl++', gui.theming.larger),
            ('Ctrl+=', gui.theming.larger),      # same key, unshifted
            ('Ctrl+-', gui.theming.smaller),
            ('Ctrl+0', gui.theming.reset),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self, handler)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)

    def _top_bar(self) -> QWidget:
        """Window-wide buttons, to the right of the Questions/Exams tabs."""
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 2, 4, 2)

        self.switch_btn = QPushButton(f'DB: {config.DB.name}')
        menu = QMenu(self.switch_btn)
        menu.aboutToShow.connect(lambda: self._fill_database_menu(menu))
        self.switch_btn.setMenu(menu)
        if CAN_RESTART:
            self.switch_btn.setToolTip('Switch to another database')
        else:
            self.switch_btn.setEnabled(False)
            self.switch_btn.setToolTip('Only available when Poodle was started '
                                       'with launch.sh')
        row.addWidget(self.switch_btn)

        update_btn = QPushButton('Update DB…')
        if 'localhost' in config.CONNECTION:
            update_btn.setToolTip(
                'Replace this database with a newer version, e.g. the .zip '
                'or folder received from the server'
            )
            update_btn.clicked.connect(lambda: DatabaseUpdateWindow(self).show())
        else:
            update_btn.setEnabled(False)
            update_btn.setToolTip('Only available for a local database')
        row.addWidget(update_btn)
        row.addSpacing(12)

        restart_btn = QPushButton('Restart')
        restart_btn.clicked.connect(lambda: self.restart())
        if CAN_RESTART:
            restart_btn.setToolTip(
                'Close Poodle and start it again, with code changes loaded'
            )
        else:
            restart_btn.setEnabled(False)
            restart_btn.setToolTip('Only available when Poodle was started '
                                   'with launch.sh')
        row.addWidget(restart_btn)

        quit_btn = QPushButton('Quit')
        quit_btn.setToolTip(
            'Close Poodle and return to the terminal.\n'
            'Start the GUI again with qt_overview()'
        )
        quit_btn.clicked.connect(self.close)
        row.addWidget(quit_btn)

        return bar

    def _fill_database_menu(self, menu: QMenu) -> None:
        # Filled each time it opens, so a database added meanwhile shows up
        menu.clear()
        for name in _poodle_databases():
            try:
                n = config.CLIENT[name].questions.estimated_document_count()
                label = f'{name}  ({n} questions)'
            except Exception:
                label = name
            action = menu.addAction(label)
            if name == config.DB.name:
                action.setCheckable(True)
                action.setChecked(True)
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda checked=False, db=name: self.restart(db)
                )

    def restart(self, db: str = None) -> None:
        """Close the GUI and start Poodle again, into db if one is given."""
        global RESTART_INTO
        RESTART_INTO = db or config.DB.name
        # close() is False when the user chose to keep other windows open
        if not self.close():
            RESTART_INTO = None

    def update_tables(self) -> None:
        self.notebook.question_table.reload()
        self.notebook.exam_table.reload()

    def closeEvent(self, event):
        # Closing the overview ends the GUI session. Qt keeps the application
        # running while ANY window is still open, and qt_overview() does not
        # return until it stops — so a stray question or preview window left
        # open would hold the terminal with no prompt to type quit() into.
        others = [w for w in _OPEN_WINDOWS if w is not self]
        if others:
            dialog = gui.dialogs.YesNoDialog(
                self,
                f'{len(others)} other Poodle window(s) are still open.',
                'Close them and return to the terminal? '
                'Unsaved changes in those windows will be lost.'
            )
            if not dialog._run():
                event.ignore()
                return
            for w in others:
                w.close()

        # With nothing else open, Qt's quitOnLastWindowClosed ends app.exec()
        # and qt_overview() hands the prompt back.
        super().closeEvent(event)


class QuestionWindow(_PoodleWindow):

    def __init__(self, parent, question_content: dict):
        super().__init__()
        self.setWindowTitle(question_content['name'])
        self.resize(1200, 800)
        self.parent_window = parent

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notebook = gui.notebooks.QuestionNotebook(self, question_content)
        layout.addWidget(self.notebook, stretch=1)

        self.control = gui.panels.QuestionControlPanel(self)
        layout.addWidget(self.control)


class TableWindow(_PoodleWindow):

    def __init__(self, parent, table_name: str, table: list):
        super().__init__()
        self.setWindowTitle(table_name)
        self.resize(800, 600)
        self.parent_window = parent
        self.table_key = table_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scroll_window = QScrollArea()
        self.scroll_window.setWidgetResizable(True)
        self.table = gui.treeviews.TableTreeView(self, table)
        self.scroll_window.setWidget(self.table)
        layout.addWidget(self.scroll_window, stretch=1)

        self.control = gui.panels.TableControlPanel(self)
        layout.addWidget(self.control)


class VariableFileWindow(_PoodleWindow):

    def __init__(self, parent, question_name: str, variables: list):
        super().__init__()
        self.setWindowTitle(question_name)
        self.resize(800, 600)
        self.parent_window = parent
        self.question_name = question_name
        self.variables = variables

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.textview = QPlainTextEdit()
        self.textview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.textview, stretch=1)

        self.control = gui.panels.VariableControlPanel(self)
        layout.addWidget(self.control)

        self.control.load_file()


class ExamWindow(_PoodleWindow):

    def __init__(self, parent, exam_content: dict):
        super().__init__()
        self.setWindowTitle(exam_content['name'])
        self.resize(1200, 800)
        self.parent_window = parent

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.notebook = gui.notebooks.ExamNotebook(self, exam_content)
        layout.addWidget(self.notebook, stretch=1)

        self.control = gui.panels.ExamControlPanel(self)
        layout.addWidget(self.control)


class ExamCreationWindow(_PoodleWindow):

    def __init__(self, parent, exam_name: str):
        super().__init__()
        self.setWindowTitle(exam_name)
        self.resize(700, 600)
        self.parent_window = parent

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setSizes([350, 350])

        # ── Left pane: question list editor ──────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self.text_edit = QPlainTextEdit()
        left_layout.addWidget(self.text_edit, stretch=1)

        self.left_control = gui.panels.ExamCreationControlPanel(self)
        left_layout.addWidget(self.left_control)

        splitter.addWidget(left)

        # ── Right pane: statistics ────────────────────────────────────────
        right = QWidget()
        right_layout = QGridLayout(right)
        right_layout.setColumnStretch(1, 1)
        right_layout.setHorizontalSpacing(20)
        right_layout.setVerticalSpacing(10)
        right_layout.setContentsMargins(10, 10, 10, 10)

        right_layout.addWidget(QLabel('Estimated exam time:'), 0, 0)
        self.time_value = QLabel('')
        right_layout.addWidget(self.time_value, 0, 1)

        right_layout.addWidget(QLabel('Average estimated difficulty:'), 1, 0)
        self.difficulty_value = QLabel('')
        right_layout.addWidget(self.difficulty_value, 1, 1)

        right_layout.addWidget(QLabel('Maximum achievable points:'), 2, 0)
        self.points_value = QLabel('')
        right_layout.addWidget(self.points_value, 2, 1)

        splitter.addWidget(right)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter)

    def closeEvent(self, event):
        if hasattr(self.parent_window, 'exam_window'):
            delattr(self.parent_window, 'exam_window')
        super().closeEvent(event)

    def add_question(self, question_name: str) -> None:
        current = self.text_edit.toPlainText()
        if current == '':
            self.text_edit.setPlainText(question_name)
        else:
            self.text_edit.setPlainText(current + f'\n{question_name}')
        self.update_report(None)

    def update_report(self, button) -> None:
        question_list = self.text_edit.toPlainText().split()
        wrong_questions = [
            q for q in question_list
            if config.QUESTIONS.find_one({'name': q}) is None
        ]
        if wrong_questions:
            # Highlight wrong question names in the text
            text = self.text_edit.toPlainText()
            for q in wrong_questions:
                text = text.replace(q, f'[{q}?]')
            self.text_edit.setPlainText(text)
            gui.dialogs.OKDialog(
                self.parent_window,
                'Marked questions could not be found in database!'
            )._run()
            return 1

        time_est = sum(
            config.QUESTIONS.find_one({'name': q})['time_est']
            for q in question_list
        )
        self.time_value.setText(str(time_est))

        difficulty_avg = np.round(np.mean(
            [config.QUESTIONS.find_one({'name': q})['difficulty'] for q in question_list]
        ), 2)
        self.difficulty_value.setText(str(difficulty_avg))

        max_points = sum(
            config.QUESTIONS.find_one({'name': q})['points']
            for q in question_list
        )
        self.points_value.setText(str(max_points))

    def create_exam(self, button=None) -> None:
        if self.update_report(None) == 1:
            return
        question_list = self.text_edit.toPlainText().split()
        dialog = gui.dialogs.QuestionSelectionDialog(self.parent_window, self)
        dialog._run(question_list)


class _DropTargetWindow(_PoodleWindow):
    """Window that takes files or folders dropped from the file manager.

    Subclasses set self.drop_zone (a QLabel) and implement accept_files().
    """

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._highlight_drop_zone(True)

    def dragLeaveEvent(self, event):
        self._highlight_drop_zone(False)

    def dropEvent(self, event):
        self._highlight_drop_zone(False)
        paths = [
            url.toLocalFile() for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            event.acceptProposedAction()
            self.accept_files(paths)

    def _highlight_drop_zone(self, active: bool) -> None:
        self.drop_zone.setProperty('dragActive', active)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def accept_files(self, paths: list) -> None:
        raise NotImplementedError


class ExamEvaluationWindow(_DropTargetWindow):
    """Feeds Moodle's two JSON exports to exam.evaluate_exam().

    Both files can be dropped onto the window straight from the file manager;
    each is identified by its contents, so they can be dropped together and in
    either order.
    """

    def __init__(self, parent, exam_name: str):
        super().__init__()
        self.setWindowTitle(f'Evaluate {exam_name}')
        self.resize(620, 320)
        self.parent_window = parent
        self.exam_name = exam_name

        top_layout = QVBoxLayout(self)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(8)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel('Exam name'), 0, 0)
        self.name_field = QLineEdit(exam_name)
        self.name_field.setReadOnly(True)
        grid.addWidget(self.name_field, 0, 1)

        grid.addWidget(QLabel('Statistics'), 1, 0)
        self.stats_field = QLineEdit()
        self.stats_field.setPlaceholderText('Export from Moodle: Statistik')
        grid.addWidget(self.stats_field, 1, 1)
        stats_btn = QPushButton('Choose file')
        stats_btn.clicked.connect(lambda: self._choose_file(self.stats_field))
        grid.addWidget(stats_btn, 1, 2)

        grid.addWidget(QLabel('Grades'), 2, 0)
        self.grades_field = QLineEdit()
        self.grades_field.setPlaceholderText('Export from Moodle: Bewertung')
        grid.addWidget(self.grades_field, 2, 1)
        grades_btn = QPushButton('Choose file')
        grades_btn.clicked.connect(lambda: self._choose_file(self.grades_field))
        grid.addWidget(grades_btn, 2, 2)

        top_layout.addLayout(grid)

        self.drop_zone = QLabel(
            'Drop both JSON files exported from Moodle here\n'
            '(Statistik and Bewertung — in any order)'
        )
        self.drop_zone.setObjectName('DropZone')
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setMinimumHeight(gui.theming.scaled(90))
        top_layout.addWidget(self.drop_zone, stretch=1)

        self.status = QLabel('')
        self.status.setObjectName('DropStatus')
        self.status.setWordWrap(True)
        top_layout.addWidget(self.status)

        self.control = gui.panels.ExamEvaluationControlPanel(self)
        top_layout.addWidget(self.control)

    # ── Drag and drop ───────────────────────────────────────────────────────

    def accept_files(self, paths: list) -> None:
        """Sort dropped files into the right field by looking inside them."""
        lines = []
        for path in paths:
            try:
                kind, file_exam = exam.inspect_moodle_export(path)
            except Exception as e:
                lines.append(f'✗ {os.path.basename(path)} — unreadable '
                             f'({type(e).__name__}: {e})')
                continue

            if kind == 'stats':
                self.stats_field.setText(path)
                note = f'exam: {file_exam}'
                if file_exam != self.exam_name:
                    note = f'⚠ names {file_exam}, not {self.exam_name}'
                lines.append(f'✓ Statistics — {os.path.basename(path)} ({note})')
            elif kind == 'grades':
                self.grades_field.setText(path)
                lines.append(f'✓ Grades — {os.path.basename(path)}')
            else:
                lines.append(f'✗ {os.path.basename(path)} — not a Moodle '
                             'Statistik or Bewertung export')

        self.status.setText('\n'.join(lines))

    # ── Evaluation ──────────────────────────────────────────────────────────

    def _choose_file(self, entry: QLineEdit) -> None:
        dialog = gui.dialogs.EvaluationFilesDialog(self)
        selected = dialog._run()
        if selected:
            self.accept_files([selected])
            if not entry.text():
                entry.setText(selected)

    def evaluate(self, button=None) -> None:
        stats_file = self.stats_field.text()
        grades_file = self.grades_field.text()

        missing = [
            label for label, path in
            (('Statistics', stats_file), ('Grades', grades_file))
            if not path
        ]
        if missing:
            gui.dialogs.OKDialog(
                self, f'No {" or ".join(missing)} file selected.',
                'Drop both of Moodle\'s JSON exports onto this window, or pick '
                'them with Choose file.'
            )._run()
            return

        # evaluate_exam() would otherwise prompt on stdin, which nothing in the
        # GUI is reading.
        exam_dir = f'{config.BASE_PATH}/databases/{config.DB.name}/exams/'
        if self.exam_name not in os.listdir(exam_dir):
            proceed = gui.dialogs.YesNoDialog(
                self, f'{self.exam_name} was not found in the exams directory.',
                'Evaluate it anyway?'
            )._run()
            if not proceed:
                return

        # evaluate_exam() reports progress and skipped questions on stdout,
        # which no one sees when it runs from a button.
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                exam.evaluate_exam(
                    self.exam_name, stats_file, grades_file, mode='gui'
                )
        except Exception as e:
            gui.dialogs.OKDialog(
                self, f'{self.exam_name} could not be evaluated.',
                f'{type(e).__name__}: {e}\n\n{output.getvalue()}'.strip()
            )._run()
            return

        if hasattr(self.parent_window, 'update_tables'):
            self.parent_window.update_tables()

        gui.dialogs.OKDialog(
            self, f'{self.exam_name} successfully evaluated.',
            output.getvalue().strip()
        )._run()
        self.close()


class _BackgroundTask(QObject):
    """
    Runs a function in a worker thread so the window stays responsive. The
    function gets a progress callable; both signals are delivered in the GUI
    thread, since this object lives there.
    """

    progress = Signal(object)
    finished = Signal(object, object)       # result, exception

    def __init__(self, function):
        super().__init__()
        self._function = function

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            result, error = self._function(self.progress.emit), None
        except Exception as e:
            result, error = None, e
        self.finished.emit(result, error)


class DatabaseUpdateWindow(_DropTargetWindow):
    """Replaces the database with a newer version received as a folder or
    .zip, through core.update_database(), and undoes the last such update.

    A dropped update is copied to a local temporary folder straight away, in
    the background: on a network drive such as BoxUP that is the slow part,
    and Update then works from the local copy.
    """

    _FOLDER_LABELS = {'img': 'Pictures', 'random_vars': 'Random variables',
                      'exams': 'Exam files'}

    def __init__(self, parent):
        super().__init__()
        self.setWindowTitle(f'Update database {config.DB.name}')
        self.resize(620, 360)
        self.parent_window = parent
        self.source = None          # the local copy of the update
        self._copy_dir = None       # TemporaryDirectory holding it
        self._task = None           # the running _BackgroundTask, if any

        top_layout = QVBoxLayout(self)
        top_layout.setContentsMargins(10, 10, 10, 10)
        top_layout.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel('Update'))
        self.source_field = QLineEdit()
        self.source_field.setReadOnly(True)
        self.source_field.setPlaceholderText(
            f'The {config.DB.name} folder or .zip you received'
        )
        row.addWidget(self.source_field, stretch=1)
        self.zip_btn = QPushButton('Choose .zip')
        self.zip_btn.clicked.connect(self._choose_zip)
        row.addWidget(self.zip_btn)
        self.choose_btn = QPushButton('Choose folder')
        self.choose_btn.clicked.connect(self._choose_folder)
        row.addWidget(self.choose_btn)
        top_layout.addLayout(row)

        self.drop_zone = QLabel(
            f'Drop the {config.DB.name} .zip or folder you received here\n'
            '(database, pictures and random variables are updated together)'
        )
        self.drop_zone.setObjectName('DropZone')
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setMinimumHeight(gui.theming.scaled(90))
        top_layout.addWidget(self.drop_zone, stretch=1)

        self.status = QLabel('')
        self.status.setObjectName('DropStatus')
        self.status.setWordWrap(True)
        top_layout.addWidget(self.status)

        self.control = gui.panels.DatabaseUpdateControlPanel(self)
        top_layout.addWidget(self.control)
        self._refresh_buttons()

    # ── Housekeeping ────────────────────────────────────────────────────────

    def _refresh_buttons(self) -> None:
        busy = self._task is not None
        self.setAcceptDrops(not busy)
        self.zip_btn.setEnabled(not busy)
        self.choose_btn.setEnabled(not busy)
        self.control.update_btn.setEnabled(not busy and self.source is not None)
        saved = core.last_update_backup()
        self.control.undo_btn.setEnabled(not busy and saved is not None)
        self.control.undo_btn.setToolTip(
            f'Go back to the state before the update of {os.path.basename(saved)}'
            if saved else 'No update to undo'
        )

    def _start(self, function, on_done) -> None:
        self._task = _BackgroundTask(function)
        self._task.progress.connect(self._show_progress)
        self._task.finished.connect(on_done)
        self._refresh_buttons()
        self._task.start()

    def _show_progress(self, copied) -> None:
        self.status.setText(f'Copying the update… {copied} file(s) so far.\n'
                            'From a network drive this takes about half a '
                            'second per file.')

    def _drop_copy(self) -> None:
        self.source = None
        if self._copy_dir is not None:
            self._copy_dir.cleanup()
            self._copy_dir = None

    def closeEvent(self, event):
        if self._task is not None:
            gui.dialogs.OKDialog(
                self, 'Please wait until the update has finished.'
            )._run()
            event.ignore()
            return
        self._drop_copy()
        super().closeEvent(event)

    # ── Choosing the update ─────────────────────────────────────────────────

    def _choose_folder(self) -> None:
        path = gui.dialogs.choose_path(self, 'Choose database folder', folder=True)
        if path:
            self.accept_files([path])

    def _choose_zip(self) -> None:
        path = gui.dialogs.choose_path(
            self, 'Choose database .zip', name_filter='Zip files (*.zip)'
        )
        if path:
            self.accept_files([path])

    def accept_files(self, paths: list) -> None:
        if self._task is not None:
            return
        path = paths[0]
        self._drop_copy()
        self.source_field.setText(path)
        self.status.setText('Reading the update…')
        self._copy_dir = tempfile.TemporaryDirectory(prefix='poodle-update-')
        dest = self._copy_dir.name

        def fetch_and_inspect(progress):
            copy = core.fetch_update(path, dest, progress=progress)
            return copy, core.inspect_update(copy)

        self._start(fetch_and_inspect, self._show_update)

    def _show_update(self, result, error) -> None:
        self._task = None
        if error is not None:
            self._drop_copy()
            self.status.setText(f'✗ Cannot update from this: {error}')
            self._refresh_buttons()
            return

        self.source, info = result
        counts = ', '.join(f'{c} {new} (now {old})'
                           for c, (new, old) in info['counts'].items())
        lines = ['The update will replace:',
                 f'✓ Database — version of {info["taken"]}: {counts}']
        for name, n in info['files'].items():
            label = f'{self._FOLDER_LABELS.get(name, name)} ({name}/)'
            if info['folder'] is None:
                lines.append(f'✗ {label} — not updated: only a backup was '
                             'dropped, drop the whole folder or .zip instead')
            elif n is None:
                lines.append(f'– {label} — not in the update, yours are kept')
            else:
                lines.append(f'✓ {label} — {n} file(s)')
        if info['newer_local']:
            lines.append(
                f'\n⚠ This version is OLDER than your newest backup '
                f'({info["newer_local"]}). Updating goes back to {info["taken"]}.'
            )
        self.status.setText('\n'.join(lines))
        self._refresh_buttons()

    # ── Updating ────────────────────────────────────────────────────────────

    def _others_closed(self) -> bool:
        """Open question or exam windows would save stale data over the update."""
        others = [w for w in _OPEN_WINDOWS
                  if w is not self and w is not self.parent_window]
        if not others:
            return True
        if not gui.dialogs.YesNoDialog(
            self, f'{len(others)} other Poodle window(s) are still open.',
            'They would show the old database. Close them and continue? '
            'Unsaved changes in those windows will be lost.'
        )._run():
            return False
        for w in others:
            w.close()
        return True

    def _finished(self, report, error) -> None:
        self._task = None
        self._refresh_buttons()
        if error is not None:
            self.status.setText('')
            gui.dialogs.OKDialog(self, 'Nothing was changed.', str(error))._run()
            return
        if hasattr(self.parent_window, 'update_tables'):
            self.parent_window.update_tables()
        gui.dialogs.OKDialog(self, report)._run()
        self.close()

    def apply_update(self, button=None) -> None:
        if self.source is None or self._task is not None:
            return
        if not gui.dialogs.YesNoDialog(
            self, f'Replace {config.DB.name} with the received version?',
            'The current state is saved first and can be brought back '
            'with Undo last update.'
        )._run() or not self._others_closed():
            return
        self.status.setText('Updating…')
        source = self.source
        self._start(lambda progress: core.update_database(source), self._finished)

    def undo(self, button=None) -> None:
        if self._task is not None:
            return
        if not gui.dialogs.YesNoDialog(
            self, 'Undo the last update?',
            f'{config.DB.name} goes back to how it was before it.'
        )._run() or not self._others_closed():
            return
        self.status.setText('Undoing the last update…')
        self._start(lambda progress: core.undo_last_update(), self._finished)


class HTMLPreviewWindow(_PoodleWindow):
    """Shows a question's text the way Moodle will render it.

    For a calculated question, dataset_items holds one entry per item Moodle
    draws from — each mapping variable name to the value written into the exam
    file — so the text can be read with real numbers in place of {var}.
    """

    def __init__(self, parent, content: str,
                 dataset_items: list = None, note: str = ''):
        super().__init__()
        self.setWindowTitle('HTML Preview')
        self.resize(1050, 700)
        self.parent_window = parent
        self._content = content
        self._items = dataset_items or []
        self._note = note

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not _HAS_WEBENGINE:
            label = QLabel(
                'WebEngine not available.\n'
                'Install PySide6-WebEngine to enable HTML preview.'
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return

        self._webview = QWebEngineView()
        # The page is Moodle's HTML, not Qt widgets, so the stylesheet cannot
        # reach it; zoom it like a browser instead, and follow later changes.
        self._webview.setZoomFactor(gui.theming.factor())
        gui.theming.scale.changed.connect(
            lambda: self._webview.setZoomFactor(gui.theming.factor())
        )

        # Moodle draws one dataset item per attempt, so let the user page
        # through them and see how the text reads with different values.
        if self._items:
            bar = QWidget()
            bar.setObjectName('ActionBar')
            bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            bar_layout = QHBoxLayout(bar)
            bar_layout.setContentsMargins(8, 4, 8, 4)
            bar_layout.addWidget(QLabel('Dataset item'))
            self.item_spin = QSpinBox()
            self.item_spin.setRange(1, len(self._items))
            self.item_spin.valueChanged.connect(self.render)
            bar_layout.addWidget(self.item_spin)
            bar_layout.addWidget(QLabel(f'of {len(self._items)}'))
            bar_layout.addStretch()
            layout.addWidget(bar)

        layout.addWidget(self._webview, stretch=1)
        self.render()

    def render(self) -> None:
        self._webview.setHtml(self._build_page(self._substitute()))

    def _substitute(self) -> str:
        """The question text with the selected dataset item's values filled in."""
        body = self._content
        if self._items:
            for name, value in self._items[self.item_spin.value() - 1].items():
                body = body.replace('{%s}' % name, value)
        return body

    def _build_page(self, body: str) -> str:
        note = ''
        if self._note:
            note = (
                '<p style="font-family:sans-serif; font-size:13px;'
                ' background:#fae4e8; border:1px solid #c01030; color:#8c0a24;'
                ' border-radius:4px; padding:10px 12px;">'
                f'{html.escape(self._note)}</p>'
            )
        return (
            '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
            '<title>Question preview</title>\n'
            '<style>body{font-family:sans-serif; font-size:15px;'
            ' line-height:1.5; padding:24px; max-width:46em;}</style>\n'
            f'</head><body>\n{note}{body}\n</body></html>'
        )
