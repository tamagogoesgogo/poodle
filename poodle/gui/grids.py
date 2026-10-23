from PySide6.QtWidgets import (
    QWidget, QFormLayout, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QLabel, QScrollArea
)
from PySide6.QtCore import Qt
import gui.theming
import gui.windows
from poodle import config
from poodle import question
import numpy as np


# ---------------------------------------------------------------------------
# Simple sub-grid widgets
# ---------------------------------------------------------------------------

class SimpleListGrid(QWidget):
    """Vertical list of QLineEdit entries with optional '+' button."""

    def __init__(self, list_field: list,
                 editable: bool = True,
                 add: bool = True,
                 output_type=str):
        super().__init__()
        self.output_type = output_type
        self._add_enabled = add
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._entries = []

        for item in list_field:
            self._append_entry(str(item), editable)

        if add:
            btn = QPushButton('+')
            btn.setFixedWidth(gui.theming.scaled(30))
            btn.clicked.connect(self._add_row)
            self._layout.addWidget(btn)

    def _append_entry(self, text: str = '', editable: bool = True):
        entry = QLineEdit(text)
        entry.setReadOnly(not editable)
        insert_pos = len(self._entries)
        self._layout.insertWidget(insert_pos, entry)
        self._entries.append(entry)
        return entry

    def _add_row(self):
        self._append_entry()

    def get_content(self) -> list:
        content = [e.text() for e in self._entries if e.text() != '']
        if isinstance(self.output_type, list):
            return [t(v) for t, v in zip(self.output_type, content)]
        return [self.output_type(v) for v in content]

    def overwrite(self, input_list: list):
        for e in self._entries:
            self._layout.removeWidget(e)
            e.deleteLater()
        self._entries = []
        for item in input_list:
            self._append_entry(str(item))


class SimpleDictGrid(QWidget):
    """Two-column grid: key entries (col 0) and value entries (col 1)."""

    def __init__(self, dict_field: dict,
                 editable: bool = True,
                 add: bool = True,
                 output_type: type = str):
        super().__init__()
        self.output_type = output_type
        self._editable = editable
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(10)
        self._layout.setVerticalSpacing(4)
        self._key_entries = []
        self._val_entries = []
        self._row_count = 0

        for key, value in dict_field.items():
            self._append_row(str(key), str(value), editable)

        if add:
            btn = QPushButton('+')
            btn.setFixedWidth(gui.theming.scaled(30))
            btn.clicked.connect(self._add_row)
            self._layout.addWidget(btn, self._row_count, 0)

    def _append_row(self, key: str = '', value: str = '', editable: bool = True):
        ke = QLineEdit(key)
        ke.setReadOnly(not editable)
        ve = QLineEdit(value)
        ve.setReadOnly(not editable)
        self._layout.addWidget(ke, self._row_count, 0)
        self._layout.addWidget(ve, self._row_count, 1)
        self._key_entries.append(ke)
        self._val_entries.append(ve)
        self._row_count += 1

    def _add_row(self):
        # Move the '+' button down one row first
        btn = self._layout.itemAtPosition(self._row_count, 0)
        if btn:
            self._layout.removeItem(btn)
            self._append_row(editable=self._editable)
            self._layout.addWidget(btn.widget(), self._row_count, 0)
        else:
            self._append_row(editable=self._editable)

    def get_content(self) -> dict:
        content = {}
        for ke, ve in zip(self._key_entries, self._val_entries):
            k = ke.text()
            if k:
                content[k] = self.output_type(ve.text())
        return content

    def overwrite(self, input_dict: dict):
        items = list(input_dict.items())
        for i, (k, v) in enumerate(items):
            if i < len(self._key_entries):
                self._key_entries[i].setText(str(k))
                self._val_entries[i].setText(str(v))


class DictListGrid(QWidget):
    """Key entry (col 0) paired with a SimpleListGrid (col 1) per row."""

    def __init__(self, dict_field: dict,
                 dict_editable: bool = True,
                 dict_add: bool = True,
                 list_editable: bool = True,
                 list_add: bool = True,
                 new_list_length: int = 1,
                 output_type=str):
        super().__init__()
        self.output_type = output_type
        self.new_list_length = new_list_length
        self.list_editable = list_editable
        self.list_add = list_add
        self._dict_editable = dict_editable
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(10)
        self._layout.setVerticalSpacing(4)
        self._key_entries = []
        self._list_grids = []
        self._row_count = 0

        for key, val_list in dict_field.items():
            self._append_row(key, val_list, dict_editable)

        if dict_add:
            btn = QPushButton('+')
            btn.setFixedWidth(gui.theming.scaled(30))
            btn.clicked.connect(self._add_row)
            self._layout.addWidget(btn, self._row_count, 0)

    def _append_row(self, key: str = '', val_list: list = None, editable: bool = True):
        if val_list is None:
            val_list = [''] * self.new_list_length
        ke = QLineEdit(key)
        ke.setReadOnly(not editable)
        lg = SimpleListGrid(val_list, self.list_editable, self.list_add, self.output_type)
        self._layout.addWidget(ke, self._row_count, 0)
        self._layout.addWidget(lg, self._row_count, 1)
        self._key_entries.append(ke)
        self._list_grids.append(lg)
        self._row_count += 1

    def _add_row(self):
        btn_item = self._layout.itemAtPosition(self._row_count, 0)
        if btn_item:
            btn = btn_item.widget()
            self._layout.removeWidget(btn)
            self._append_row(editable=self._dict_editable)
            self._layout.addWidget(btn, self._row_count, 0)
        else:
            self._append_row(editable=self._dict_editable)

    def get_content(self) -> dict:
        return {
            ke.text(): lg.get_content()
            for ke, lg in zip(self._key_entries, self._list_grids)
            if ke.text()
        }

    def overwrite(self, input_dict: dict):
        items = list(input_dict.items())
        for i, (k, v) in enumerate(items):
            if i < len(self._key_entries):
                self._key_entries[i].setText(str(k))
                self._list_grids[i].overwrite(v)


class DictButtonGrid(QWidget):
    """Key entry (col 0) paired with an action button (col 1) per row."""

    def __init__(self, parent, button_label: str, fn, arguments: tuple,
                 dict_field: dict, dict_editable: bool = True,
                 key_default: str = '', dict_add: bool = True):
        super().__init__()
        self._parent = parent
        self.button_label = button_label
        self.fn = fn
        self.arguments = arguments
        self.data = dict_field
        self._dict_editable = dict_editable
        self.key_default = key_default
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(10)
        self._layout.setVerticalSpacing(4)
        self._key_entries = []
        self._buttons = []
        self._row_count = 0

        for n, key in enumerate(dict_field.keys()):
            self._append_row(key, n, dict_editable)

        if dict_add:
            btn = QPushButton('+')
            btn.setFixedWidth(gui.theming.scaled(30))
            btn.clicked.connect(self._add_row)
            self._layout.addWidget(btn, self._row_count, 0)

    def _make_action_btn(self, row_idx: int) -> QPushButton:
        btn = QPushButton(self.button_label)
        btn.clicked.connect(lambda checked, r=row_idx: self.fn(r, self, self.data))
        return btn

    def _append_row(self, key: str = '', row_idx: int = 0, editable: bool = True):
        ke = QLineEdit(key)
        ke.setReadOnly(not editable)
        btn = self._make_action_btn(row_idx)
        self._layout.addWidget(ke, self._row_count, 0)
        self._layout.addWidget(btn, self._row_count, 1)
        self._key_entries.append(ke)
        self._buttons.append(btn)
        self._row_count += 1

    def _add_row(self):
        btn_item = self._layout.itemAtPosition(self._row_count, 0)
        if btn_item:
            plus_btn = btn_item.widget()
            self._layout.removeWidget(plus_btn)
        key = self.key_default + f'{self._row_count + 1:02d}' if self.key_default else ''
        self._append_row(key, self._row_count, self._dict_editable)
        self.data[key] = [[''], ['']]
        if btn_item:
            self._layout.addWidget(plus_btn, self._row_count, 0)

    def get_content(self) -> dict:
        return self.data

    def overwrite(self, input_dict: dict):
        self.data = input_dict
        for i, btn in enumerate(self._buttons):
            btn.clicked.disconnect()
            btn.clicked.connect(lambda checked, r=i: self.fn(r, self, self.data))


# ---------------------------------------------------------------------------
# Table utility grids
# ---------------------------------------------------------------------------

class TableColumnGrid(QWidget):
    """Editable list of column title entries used in EditColumnsDialog."""

    def __init__(self, parent, column_titles: list):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._entries = []

        for title in column_titles:
            entry = QLineEdit(title)
            self._layout.addWidget(entry)
            self._entries.append(entry)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('+')
        add_btn.clicked.connect(self._add_row)
        rem_btn = QPushButton('-')
        rem_btn.clicked.connect(self._remove_row)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rem_btn)
        self._layout.addLayout(btn_row)

    def _add_row(self):
        entry = QLineEdit()
        self._layout.insertWidget(len(self._entries), entry)
        self._entries.append(entry)
        entry.show()

    def _remove_row(self):
        if len(self._entries) > 1:
            entry = self._entries.pop()
            self._layout.removeWidget(entry)
            entry.deleteLater()

    def get_entries(self) -> list:
        return [e.text() for e in self._entries]


# ---------------------------------------------------------------------------
# Main question / exam grids
# ---------------------------------------------------------------------------

class GeneralQuestionGrid(QWidget):
    """Base form for all question types."""

    def __init__(self, parent, question_content: dict):
        super().__init__()
        self.parent_window = parent
        self.content = question_content
        self._fields = {}

        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setVerticalSpacing(12)
        self._layout.setHorizontalSpacing(30)

        self.name_field = QLineEdit(self.content['name'])
        self.name_field.setReadOnly(True)
        self._layout.addRow('name', self.name_field)
        self._fields['name'] = self.name_field

        self.moodle_type_field = QLineEdit(self.content['moodle_type'])
        self.moodle_type_field.setReadOnly(True)
        self._layout.addRow('moodle_type', self.moodle_type_field)
        self._fields['moodle_type'] = self.moodle_type_field

        self.question_field = QPlainTextEdit(self.content['question'])
        self.question_field.setMinimumHeight(gui.theming.scaled(100))
        self._layout.addRow('question', self.question_field)
        self._fields['question'] = self.question_field

        self.points_field = QLineEdit(str(self.content['points']))
        self._layout.addRow('points', self.points_field)
        self._fields['points'] = self.points_field

        self.difficulty_field = QLineEdit(str(self.content['difficulty']))
        self._layout.addRow('difficulty', self.difficulty_field)
        self._fields['difficulty'] = self.difficulty_field

        self.time_est_field = QLineEdit(str(self.content['time_est']))
        self._layout.addRow('time_est', self.time_est_field)
        self._fields['time_est'] = self.time_est_field

        self.family_type_field = QLineEdit(self.content['family_type'])
        self.family_type_field.setReadOnly(True)
        self._layout.addRow('family_type', self.family_type_field)
        self._fields['family_type'] = self.family_type_field

        self.in_exams_field = SimpleDictGrid(
            self.content['in_exams'], editable=False, add=False, output_type=float
        )
        self._layout.addRow('in_exams', self.in_exams_field)
        self._fields['in_exams'] = self.in_exams_field

    def preview_html(self):
        content = self.question_field.toPlainText()
        dataset_items, note = [], ''

        # A calculated question's {var} placeholders are filled by Moodle from
        # the question's variable file; run it so the preview shows numbers.
        if hasattr(self, 'vars_field'):
            variables = [v for v in self.vars_field.get_content() if v]
            if variables:
                try:
                    dataset_items = question.dataset_items(
                        self.name_field.text(), variables
                    )
                except Exception as e:
                    note = (
                        f'Showing {{placeholders}} unchanged: the variable file '
                        f'rv_{self.name_field.text()}.py could not be read — '
                        f'{type(e).__name__}: {e}'
                    )

        new_window = gui.windows.HTMLPreviewWindow(
            self.parent_window, content, dataset_items, note
        )
        new_window.show()

    def check_optional(self):
        if 'img_files' not in self.content:
            btn = QPushButton('Add img_files')
            btn.clicked.connect(lambda: self.build_optional('img_files', ['']))
            self._layout.addRow('', btn)
            self._img_files_button = btn
        else:
            self.build_optional('img_files', self.content['img_files'])

        if 'tables' not in self.content:
            btn = QPushButton('Add tables')
            btn.clicked.connect(lambda: self.build_optional('tables', {}))
            self._layout.addRow('', btn)
            self._tables_button = btn
        else:
            self.build_optional('tables', self.content['tables'])

    def build_optional(self, field: str, content):
        if field == 'img_files':
            if hasattr(self, '_img_files_button'):
                self._layout.removeRow(self._img_files_button)
                del self._img_files_button
            self.img_files_field = SimpleListGrid(content)
            self._layout.addRow('img_files', self.img_files_field)
            self._fields['img_files'] = self.img_files_field

        elif field == 'tables':
            if hasattr(self, '_tables_button'):
                self._layout.removeRow(self._tables_button)
                del self._tables_button
            self.tables_field = DictButtonGrid(
                self, 'Show/edit', self.show_table, (), content, False, 'tbl'
            )
            self._layout.addRow('tables', self.tables_field)
            self._fields['tables'] = self.tables_field

    def show_table(self, row_idx: int, grid, data: dict):
        tbl_name = grid._key_entries[row_idx].text()
        tbl = data[tbl_name]
        new_window = gui.windows.TableWindow(self.parent_window, tbl_name, tbl)
        new_window.show()

    def update_content(self) -> dict:
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit):
                try:
                    t = config.KEY_TYPES['general'][key]
                except KeyError:
                    try:
                        t = config.KEY_TYPES['optional'][key]
                    except KeyError:
                        t = config.KEY_TYPES[self.moodle_type_field.text()][key]
                if isinstance(t, tuple):
                    t = t[0]
                self.content[key] = t(widget.text())
            elif isinstance(widget, QPlainTextEdit):
                self.content[key] = widget.toPlainText()
            else:
                self.content[key] = widget.get_content()
        return self.content

    def overwrite(self, question_content: dict):
        self.content = question_content
        for key, value in question_content.items():
            if key not in self._fields:
                continue
            widget = self._fields[key]
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(str(value))
            else:
                try:
                    widget.overwrite(value)
                except (AttributeError, TypeError, ValueError) as e:
                    raise TypeError(f"field '{key}': {e}") from e


class MultiChoiceQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleListGrid(self.content['correct_answers'])
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.false_answers_field = SimpleListGrid(self.content['false_answers'])
        self._layout.insertRow(5, 'false_answers', self.false_answers_field)
        self._fields['false_answers'] = self.false_answers_field

        self.single_field = QLineEdit(str(self.content['single']))
        self._layout.insertRow(6, 'single', self.single_field)
        self._fields['single'] = self.single_field

        self.check_optional()


class NumericalQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleListGrid(
            self.content['correct_answers'], add=False, output_type=float
        )
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.tolerance_field = QLineEdit(str(self.content['tolerance']))
        self._layout.insertRow(5, 'tolerance', self.tolerance_field)
        self._fields['tolerance'] = self.tolerance_field

        self.check_optional()


class ShortanswerQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleListGrid(self.content['correct_answers'])
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.usecase_field = QLineEdit(str(self.content['usecase']))
        self._layout.insertRow(5, 'usecase', self.usecase_field)
        self._fields['usecase'] = self.usecase_field

        self.check_optional()


class EssayQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.answer_files_field = SimpleListGrid(
            self.content['answer_files'], add=False, output_type=int
        )
        self._layout.insertRow(4, 'answer_files', self.answer_files_field)
        self._fields['answer_files'] = self.answer_files_field

        self.check_optional()


class MatchingQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleDictGrid(self.content['correct_answers'])
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.false_answers_field = SimpleListGrid(self.content['false_answers'])
        self._layout.insertRow(5, 'false_answers', self.false_answers_field)
        self._fields['false_answers'] = self.false_answers_field

        self.check_optional()


class GapselectQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = DictListGrid(self.content['correct_answers'])
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.false_answers_field = DictListGrid(self.content['false_answers'])
        self._layout.insertRow(5, 'false_answers', self.false_answers_field)
        self._fields['false_answers'] = self.false_answers_field

        self.check_optional()


class DDImageOrTextQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleListGrid(self.content['correct_answers'])
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.drops_field = DictListGrid(
            self.content['drops'], list_add=False, new_list_length=2, output_type=int
        )
        self._layout.insertRow(5, 'drops', self.drops_field)
        self._fields['drops'] = self.drops_field

        self.check_optional()


class CalculatedQuestionGrid(GeneralQuestionGrid):

    def __init__(self, parent, question_content: dict):
        super().__init__(parent, question_content)

        preview_btn = QPushButton('Preview HTML')
        preview_btn.clicked.connect(self.preview_html)
        self._layout.insertRow(3, '', preview_btn)

        self.correct_answers_field = SimpleListGrid(
            self.content['correct_answers'], add=False
        )
        self._layout.insertRow(4, 'correct_answers', self.correct_answers_field)
        self._fields['correct_answers'] = self.correct_answers_field

        self.vars_field = SimpleListGrid(self.content['vars'])
        self._layout.insertRow(5, 'vars', self.vars_field)
        self._fields['vars'] = self.vars_field

        self.tolerance_field = SimpleListGrid(
            self.content['tolerance'], add=False, output_type=[float, str, int]
        )
        self._layout.insertRow(6, 'tolerance', self.tolerance_field)
        self._fields['tolerance'] = self.tolerance_field

        self.check_optional()

        file_btn = QPushButton('Edit variable creation')
        file_btn.clicked.connect(self.edit_var_file)
        self._layout.addRow('', file_btn)

    def edit_var_file(self):
        self.update_content()
        new_window = gui.windows.VariableFileWindow(
            self.parent_window,
            self.content['name'],
            self.vars_field.get_content()
        )
        new_window.show()


# ---------------------------------------------------------------------------
# Exam grid
# ---------------------------------------------------------------------------

class ExamGrid(QWidget):

    def __init__(self, parent, exam_content: dict):
        super().__init__()
        self.parent_window = parent
        self.content = exam_content
        self._fields = {}

        self._layout = QFormLayout(self)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setVerticalSpacing(12)
        self._layout.setHorizontalSpacing(30)

        self.name_field = QLineEdit(self.content['name'])
        self.name_field.setReadOnly(True)
        self._layout.addRow('name', self.name_field)
        self._fields['name'] = self.name_field

        self.points_max_field = QLineEdit(str(self.content['points_max']))
        self.points_max_field.setReadOnly(True)
        self._layout.addRow('points_max', self.points_max_field)
        self._fields['points_max'] = self.points_max_field

        self.points_avg_field = QLineEdit(str(self._calc_points_avg(exam_content)))
        self.points_avg_field.setReadOnly(True)
        self._layout.addRow('points_avg', self.points_avg_field)
        self._fields['points_avg'] = self.points_avg_field

        self.n_questions_field = QLineEdit(str(len(exam_content['questions'])))
        self.n_questions_field.setReadOnly(True)
        self._layout.addRow('n_questions', self.n_questions_field)
        self._fields['n_questions'] = self.n_questions_field

        self.difficulty_avg_field = QLineEdit(str(exam_content['difficulty_avg']))
        self.difficulty_avg_field.setReadOnly(True)
        self._layout.addRow('difficulty_avg', self.difficulty_avg_field)
        self._fields['difficulty_avg'] = self.difficulty_avg_field

        self.time_est_field = QLineEdit(str(exam_content['time_est']))
        self.time_est_field.setReadOnly(True)
        self._layout.addRow('time_est', self.time_est_field)
        self._fields['time_est'] = self.time_est_field

        # An evaluated exam carries per-question averages; show those instead of
        # the plain question list. The widget is registered under the key it
        # actually displays, so update_content() can never write the averages
        # dict over the exam's list of question names.
        if 'questions_avgs' in exam_content:
            self._questions_key = 'questions_avgs'
            self.questions_field = SimpleDictGrid(
                exam_content['questions_avgs'], editable=False, add=False, output_type=float
            )
        else:
            self._questions_key = 'questions'
            self.questions_field = SimpleListGrid(exam_content['questions'])
        self._layout.addRow(self._questions_key, self.questions_field)
        self._fields[self._questions_key] = self.questions_field

    def update_content(self) -> dict:
        for key, widget in self._fields.items():
            if isinstance(widget, QLineEdit):
                t = config.EXAM_TYPES.get(key, str)
                if isinstance(t, tuple):
                    t = t[0]
                try:
                    self.content[key] = t(widget.text())
                except (ValueError, TypeError):
                    pass
            else:
                self.content[key] = widget.get_content()
        return self.content

    def overwrite(self, exam_content: dict):
        self.content = exam_content
        for key, value in exam_content.items():
            if key not in self._fields:
                continue
            widget = self._fields[key]
            if isinstance(widget, QLineEdit):
                widget.setText(str(value))
            else:
                try:
                    widget.overwrite(value)
                except (AttributeError, TypeError, ValueError) as e:
                    raise TypeError(f"field '{key}': {e}") from e

    def _calc_points_avg(self, exam_content: dict) -> float:
        # find_one() returns None for a question that has since been deleted.
        try:
            avg = np.round(np.nansum([
                x[1] * config.QUESTIONS.find_one({'name': x[0]})['points']
                for x in exam_content['questions_avgs'].items()
            ]), 2)
        except (KeyError, TypeError):
            avg = 0.0
        return avg
