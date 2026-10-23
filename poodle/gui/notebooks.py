from PySide6.QtWidgets import QTabWidget, QScrollArea
from PySide6.QtGui import QTextCharFormat, QColor
import gui.treeviews
import gui.panels
import gui.grids
import gui.textviews
import gui.dialogs
import json
import re


class MainNotebook(QTabWidget):

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent

        # Questions tab
        self.question_table = gui.treeviews.QuestionTreeview(self.parent_window)
        q_scroll = QScrollArea()
        q_scroll.setWidget(self.question_table)
        q_scroll.setWidgetResizable(True)
        self.addTab(q_scroll, 'Questions')

        # Exams tab
        self.exam_table = gui.treeviews.ExamTreeview(self.parent_window)
        e_scroll = QScrollArea()
        e_scroll.setWidget(self.exam_table)
        e_scroll.setWidgetResizable(True)
        self.addTab(e_scroll, 'Exams')

        self.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int):
        # Switch the control panel shown in MainWindow
        if index == 0:
            self.parent_window.control = self.parent_window.question_control
        else:
            self.parent_window.control = self.parent_window.exam_control
        self.parent_window.stacked_control.setCurrentIndex(index)


class _SyncNotebook(QTabWidget):
    """Base for the two-tab editors: a form grid on tab 0, raw JSON on tab 1.

    Every switch copies the content of the tab being left into the tab being
    entered. The direction is determined solely by the destination index, so
    the very first switch syncs like any other one.
    """

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent
        self._last_idx = 0
        self._in_switch = False

    @property
    def _grid(self):
        return self.widget(0).widget()

    @property
    def _raw(self):
        return self.widget(1).widget()

    def current_content_widget(self):
        """Return the actual content widget of the currently visible tab."""
        return self.currentWidget().widget()

    def _abort(self, prev_idx: int, secondary_text: str) -> None:
        """Undo the tab switch and tell the user why it was refused."""
        self._in_switch = True
        self.setCurrentIndex(prev_idx)
        self._in_switch = False
        gui.dialogs.OKDialog(
            self.parent_window,
            'Aborted switching page due to following error:',
            secondary_text
        )._run()

    def _highlight_json_error(self, e) -> None:
        """Colour the line the JSON parser choked on red."""
        if re.match("Expecting ',' delimiter", e.args[0]):
            error_chars = e.doc.splitlines()[e.lineno - 2]
        else:
            error_chars = e.doc.splitlines()[e.lineno - 1]
        cursor = self._raw.document().find(error_chars)
        if not cursor.isNull():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor('red'))
            cursor.mergeCharFormat(fmt)

    def _on_tab_changed(self, new_idx: int) -> None:
        if self._in_switch:
            return
        prev_idx = self._last_idx
        if prev_idx == new_idx:
            return

        if new_idx == 0:  # arriving at form tab: read from Raw
            try:
                new_content = self._raw.update_content()
            except json.JSONDecodeError as e:
                self._abort(prev_idx, e.args[0])
                self._highlight_json_error(e)
                return
            try:
                self._grid.overwrite(new_content)
            except Exception as e:
                self._abort(prev_idx, f'{type(e).__name__}: {e}')
                return
        else:  # arriving at Raw tab: read from form tab
            try:
                new_content = self._grid.update_content()
            except Exception as e:
                self._abort(prev_idx, f'{type(e).__name__}: {e}')
                return
            new_content.pop('_id', None)
            self._raw.overwrite(new_content)

        self._last_idx = new_idx


class QuestionNotebook(_SyncNotebook):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent)

        # Question tab
        q_scroll = QScrollArea()
        q_scroll.setWidgetResizable(True)
        match question_content['moodle_type']:
            case 'multichoice':
                self.question_grid = gui.grids.MultiChoiceQuestionGrid(
                    self.parent_window, question_content)
            case 'numerical':
                self.question_grid = gui.grids.NumericalQuestionGrid(
                    self.parent_window, question_content)
            case 'shortanswer':
                self.question_grid = gui.grids.ShortanswerQuestionGrid(
                    self.parent_window, question_content)
            case 'essay':
                self.question_grid = gui.grids.EssayQuestionGrid(
                    self.parent_window, question_content)
            case 'matching':
                self.question_grid = gui.grids.MatchingQuestionGrid(
                    self.parent_window, question_content)
            case 'gapselect':
                self.question_grid = gui.grids.GapselectQuestionGrid(
                    self.parent_window, question_content)
            case 'ddimageortext':
                self.question_grid = gui.grids.DDImageOrTextQuestionGrid(
                    self.parent_window, question_content)
            case 'calculated':
                self.question_grid = gui.grids.CalculatedQuestionGrid(
                    self.parent_window, question_content)
            case _:
                raise ValueError(f"Unknown moodle_type: {question_content['moodle_type']}")
        q_scroll.setWidget(self.question_grid)
        self.addTab(q_scroll, 'Question')

        # Raw tab
        r_scroll = QScrollArea()
        r_scroll.setWidgetResizable(True)
        self.raw_page = gui.textviews.RawText(question_content)
        r_scroll.setWidget(self.raw_page)
        self.addTab(r_scroll, 'Raw')

        self.currentChanged.connect(self._on_tab_changed)


class ExamNotebook(_SyncNotebook):

    def __init__(self, parent, exam_content: dict):
        super().__init__(parent)

        # Exam tab
        e_scroll = QScrollArea()
        e_scroll.setWidgetResizable(True)
        self.exam_grid = gui.grids.ExamGrid(self.parent_window, exam_content)
        e_scroll.setWidget(self.exam_grid)
        self.addTab(e_scroll, 'Exam')

        # Raw tab
        r_scroll = QScrollArea()
        r_scroll.setWidgetResizable(True)
        self.raw_page = gui.textviews.RawText(exam_content)
        r_scroll.setWidget(self.raw_page)
        self.addTab(r_scroll, 'Raw')

        self.currentChanged.connect(self._on_tab_changed)
