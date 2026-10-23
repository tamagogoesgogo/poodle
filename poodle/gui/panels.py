from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QPushButton, QComboBox, QLineEdit, QMenu
)
from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from poodle import question
from poodle import config
from poodle import exam
import gui.dialogs
import gui.theming
import gui.windows
import json
import ast
import re


def _letters_icon(side: int, large: bool) -> QIcon:
    """"Aa" in the text colour, small or large, sitting on a common baseline."""
    ratio = 2   # drawn at double resolution so it stays sharp on HiDPI screens
    width = round(side * 1.5)
    pixmap = QPixmap(width * ratio, side * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QApplication.font()
    font.setBold(True)
    font.setPixelSize(max(6, round(side * (1.0 if large else 0.66))))
    painter.setFont(font)
    painter.setPen(gui.theming.color('text'))
    painter.drawText(QRectF(0, 0, width, side),
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                     'Aa')
    painter.end()

    return QIcon(pixmap)


class _ActionBar(QWidget):
    """Base class replacing Gtk.ActionBar: horizontal bar with left and right sections."""

    def __init__(self, parent_window=None):
        super().__init__()
        self.setObjectName('ActionBar')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.parent_window = parent_window
        self._main = QHBoxLayout(self)
        self._main.setContentsMargins(4, 2, 4, 2)
        self._left = QHBoxLayout()
        self._right = QHBoxLayout()
        self._main.addLayout(self._left)
        self._main.addStretch()
        self._main.addLayout(self._right)
        # A minimum rather than a fixed height: the bar has to grow with the
        # text size, and at the default size this is the height it always had.
        self.setMinimumHeight(44)

    def _pack_start(self, widget):
        self._left.addWidget(widget)

    def _pack_end(self, widget):
        self._right.addWidget(widget)

    def _pack_palette(self):
        """Add the colour-scheme picker (overview panels only)."""
        self._right.addSpacing(16)

        self.palette_button = QPushButton(self._palette_label())
        self.palette_button.setToolTip('Colour scheme')
        menu = QMenu(self.palette_button)
        for name, colors in gui.theming.PALETTES.items():
            action = menu.addAction(colors['label'])
            action.triggered.connect(
                lambda checked=False, n=name: gui.theming.set_palette(n)
            )
        self.palette_button.setMenu(menu)
        self._pack_end(self.palette_button)

        gui.theming.scale.palette_changed.connect(self._show_palette)

    def _palette_label(self) -> str:
        return gui.theming.PALETTES[gui.theming.palette_name()]['label']

    def _show_palette(self, name: str) -> None:
        self.palette_button.setText(gui.theming.PALETTES[name]['label'])

    def _pack_text_size(self):
        """Add the text-size stepper (overview panels only)."""
        self._right.addSpacing(16)

        self.smaller_btn = QPushButton()
        self.smaller_btn.setToolTip('Smaller text  (Ctrl+−)')
        self.smaller_btn.clicked.connect(gui.theming.smaller)
        self._pack_end(self.smaller_btn)

        self.text_size_button = QPushButton(str(gui.theming.size()))
        self.text_size_button.setToolTip(
            f'Text size in pixels. Press to reset to '
            f'{gui.theming.BASE_SIZE}  (Ctrl+0)'
        )
        self.text_size_button.setFlat(True)
        self.text_size_button.clicked.connect(gui.theming.reset)
        self._pack_end(self.text_size_button)

        self.larger_btn = QPushButton()
        self.larger_btn.setToolTip('Larger text  (Ctrl++)')
        self.larger_btn.clicked.connect(gui.theming.larger)
        self._pack_end(self.larger_btn)

        self._paint_zoom_icons()
        gui.theming.scale.changed.connect(self._show_text_size)
        gui.theming.scale.palette_changed.connect(self._paint_zoom_icons)

    def _paint_zoom_icons(self, *_) -> None:
        # Painted rather than set as text: the stylesheet gives every button
        # the same font size, and these two need to differ.
        side = gui.theming.scaled(18)
        for button, large in ((self.smaller_btn, False), (self.larger_btn, True)):
            button.setIcon(_letters_icon(side, large))
            button.setIconSize(QSize(round(side * 1.5), side))

    def _show_text_size(self, size: int) -> None:
        self.text_size_button.setText(str(size))

class MainQuestionControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.table = self.parent_window.notebook.question_table

        new_btn = QPushButton('New')
        new_btn.clicked.connect(self.table.new_question)
        self._pack_start(new_btn)

        view_btn = QPushButton('View')
        view_btn.clicked.connect(self.table.view_question)
        self._pack_start(view_btn)

        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self.table.delete_question)
        self._pack_start(del_btn)

        exam_btn = QPushButton('Add to exam')
        exam_btn.clicked.connect(self.table.add_to_exam)
        self._pack_start(exam_btn)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText('Search…')
        self._pack_end(self.search_entry)

        self.fields_combo = QComboBox()
        for f in ['name', 'question', 'moodle_type', 'family_type',
                  'appearances', 'difficulty', 'time_est']:
            self.fields_combo.addItem(f)
        self._pack_end(self.fields_combo)

        filter_btn = QPushButton('Filter')
        filter_btn.clicked.connect(self.table.refilter)
        self._pack_end(filter_btn)

        self._pack_palette()
        self._pack_text_size()


class MainExamControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.table = self.parent_window.notebook.exam_table

        new_btn = QPushButton('New')
        new_btn.clicked.connect(self.table.new_exam)
        self._pack_start(new_btn)

        view_btn = QPushButton('View')
        view_btn.clicked.connect(self.table.view_exam)
        self._pack_start(view_btn)

        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self.table.delete_exam)
        self._pack_start(del_btn)

        eval_btn = QPushButton('Evaluate')
        eval_btn.clicked.connect(self.table.evaluate_exam)
        self._pack_start(eval_btn)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText('Search…')
        self._pack_end(self.search_entry)

        self.fields_combo = QComboBox()
        for f in ['name', 'points_max', 'points_avg', 'questions', 'difficulty', 'time_est']:
            self.fields_combo.addItem(f)
        self._pack_end(self.fields_combo)

        filter_btn = QPushButton('Filter')
        filter_btn.clicked.connect(self.table.refilter)
        self._pack_end(filter_btn)

        self._pack_palette()
        self._pack_text_size()


class QuestionControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.main_window = self.parent_window.parent_window

        save_btn = QPushButton('Save')
        save_btn.clicked.connect(self.on_save_clicked)
        self._pack_start(save_btn)

        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self.on_delete_clicked)
        self._pack_end(del_btn)

    def _get_page(self):
        return self.parent_window.notebook.current_content_widget()

    def check_question(self, page):
        check_result = question.check_question(
            json.dumps(page.content, ensure_ascii=False), ignore_duplicates=True
        )
        if check_result:
            dialog = gui.dialogs.CheckQuestionDialog(self.parent_window, page, check_result)
            return dialog._run()

    def on_save_clicked(self):

        def save_question(page):
            dialog = gui.dialogs.YesNoDialog(
                self.parent_window,
                f'Are you sure you want to save {page.content["name"]}?'
            )
            if dialog._run():
                check_result = self.check_question(page)
                if not check_result:
                    config.QUESTIONS.insert_one(page.content)
                    self.main_window.update_tables()

        def overwrite_question(page):
            dialog = gui.dialogs.YesNoDialog(
                self.parent_window,
                f'Are you sure you want to overwrite {page.content["name"]}?',
                'Changes are irreversible!'
            )
            if dialog._run():
                check_result = self.check_question(page)
                if not check_result:
                    for k, v in page.content.items():
                        config.QUESTIONS.find_one_and_update(
                            {'name': page.content['name']},
                            {'$set': {k: v}}
                        )
                    self.main_window.update_tables()

        page = self._get_page()
        new_content = page.update_content()
        page.overwrite(new_content)
        question_name = page.content['name']
        db_question = config.QUESTIONS.find_one({'name': question_name})
        try:
            db_question.pop('_id')
            if page.content == db_question:
                gui.dialogs.OKDialog(
                    self.parent_window, 'Nothing to save.',
                    f'No changes were made to {question_name}.'
                )._run()
                return
        except AttributeError:
            pass
        if not db_question:
            save_question(page)
        else:
            overwrite_question(page)

    def on_delete_clicked(self):
        page = self._get_page()
        new_content = page.update_content()
        page.overwrite(new_content)
        question_name = page.content['name']
        db_question = config.QUESTIONS.find_one({'name': question_name})

        if not db_question:
            gui.dialogs.OKDialog(
                self.parent_window, 'Nothing to delete.',
                f"{question_name} doesn't exist in database!"
            )._run()
            return

        dialog = gui.dialogs.YesNoDialog(
            self.parent_window,
            f'Are you sure you want to delete {question_name}?',
            'Changes are irreversible!'
        )
        if dialog._run():
            config.QUESTIONS.delete_one({'name': question_name})
            self.main_window.update_tables()
            self.parent_window.close()


class TableControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.table = self.parent_window.table

        save_btn = QPushButton('Save')
        save_btn.setToolTip('Save the table into the question  (Ctrl+S)')
        save_btn.clicked.connect(self.table.save_table)
        self._pack_start(save_btn)

        undo_btn = QPushButton('Undo')
        undo_btn.setToolTip('Undo the last change to the table  (Ctrl+Z)')
        undo_btn.clicked.connect(self.table.undo)
        self._pack_start(undo_btn)

        preview_btn = QPushButton('Preview')
        preview_btn.clicked.connect(self.table.preview_table)
        self._pack_start(preview_btn)

        paste_btn = QPushButton('Paste CSV')
        paste_btn.setToolTip(
            'Paste from a spreadsheet at the selected cell  (Ctrl+V).\n'
            'Right-click a cell to insert or delete rows and columns.'
        )
        paste_btn.clicked.connect(self.table.paste_csv)
        self._pack_end(paste_btn)

        add_row_btn = QPushButton('Add row')
        add_row_btn.clicked.connect(self.table.add_row)
        self._pack_end(add_row_btn)

        rem_row_btn = QPushButton('Remove row')
        rem_row_btn.clicked.connect(self.table.remove_row)
        self._pack_end(rem_row_btn)

        edit_col_btn = QPushButton('Edit columns')
        edit_col_btn.clicked.connect(self.table.edit_columns)
        self._pack_end(edit_col_btn)

        span_col_btn = QPushButton('Span columns')
        span_col_btn.setToolTip(
            'Put one header across the selected columns.\n'
            'With nothing selected, adds a new spanned group of columns.'
        )
        span_col_btn.clicked.connect(self.table.span_columns)
        self._pack_end(span_col_btn)

        unspan_col_btn = QPushButton('Unspan columns')
        unspan_col_btn.setToolTip('Take a spanning column header apart again')
        unspan_col_btn.clicked.connect(self.table.unsplit_column)
        self._pack_end(unspan_col_btn)

        span_row_btn = QPushButton('Span rows')
        span_row_btn.setToolTip(
            'Put one header down the first column of the selected rows.\n'
            'With nothing selected, adds a new spanned group of rows.'
        )
        span_row_btn.clicked.connect(self.table.span_rows)
        self._pack_end(span_row_btn)

        unspan_row_btn = QPushButton('Unspan rows')
        unspan_row_btn.setToolTip('Take a spanning row header apart again')
        unspan_row_btn.clicked.connect(self.table.unsplit_row)
        self._pack_end(unspan_row_btn)

        merge_btn = QPushButton('Merge cells')
        merge_btn.setToolTip(
            'Join the selected cells of one row into a cell spanning them,\n'
            'for a figure that belongs to several columns at once.'
        )
        merge_btn.clicked.connect(self.table.merge_cells)
        self._pack_end(merge_btn)

        rename_btn = QPushButton('Rename spans')
        rename_btn.setToolTip(
            'Rename the spanning column headers.\n'
            'A spanning row header is renamed by typing in it.'
        )
        rename_btn.clicked.connect(self.table.rename_group_labels)
        self._pack_end(rename_btn)

        self.row_headers_button = QPushButton('Row headers')
        self.row_headers_button.setCheckable(True)
        # Set before connecting: a saved table may already have them on, and
        # a button that says otherwise makes the first click do nothing.
        self.row_headers_button.setChecked(self.table.row_headers)
        self.row_headers_button.toggled.connect(self.table.toggle_row_headers)
        self._pack_end(self.row_headers_button)


class VariableControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.textview = self.parent_window.textview
        self.path = (
            f'{config.BASE_PATH}/databases/{config.DB.name}/random_vars/' +
            f'rv_{self.parent_window.question_name}.py'
        )

        save_btn = QPushButton('Save')
        save_btn.clicked.connect(self.save_file)
        self._pack_start(save_btn)

        check_btn = QPushButton('Check code')
        check_btn.clicked.connect(lambda: self.parse_file(silent=False))
        self._pack_end(check_btn)

    def load_file(self):
        try:
            with open(self.path, 'r') as rf:
                self.textview.setPlainText(rf.read())
        except FileNotFoundError:
            variables = self.parent_window.variables
            template = (
                'from config import RANDOM_ARR_SIZE\n'
                'import numpy as np\n\n' +
                ' = \n'.join(variables) + ' = '
            )
            self.textview.setPlainText(template)

    def save_file(self):
        code = self.textview.toPlainText()
        if self.parse_file(silent=True):
            with open(self.path, 'w') as wf:
                wf.write(code)
            gui.dialogs.OKDialog(self.parent_window, 'File successfully saved.')._run()

    def parse_file(self, silent: bool = True) -> bool:
        code = self.textview.toPlainText()
        try:
            ast.parse(code)
        except SyntaxError as e:
            match = re.search(r'\d+(?=\))', str(e))
            line_number = match.group(0) if match else '?'
            gui.dialogs.OKDialog(
                self.parent_window,
                f'Syntax error found at line {line_number}!'
            )._run()
            return False
        if not silent:
            gui.dialogs.OKDialog(
                self.parent_window,
                'Syntax check successfully passed.',
                '(This does not guarantee successful compilation!)'
            )._run()
        return True


class ExamControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.main_window = self.parent_window.parent_window

        save_btn = QPushButton('Save')
        save_btn.clicked.connect(self.on_save_clicked)
        self._pack_start(save_btn)

        del_btn = QPushButton('Delete')
        del_btn.clicked.connect(self.on_delete_clicked)
        self._pack_end(del_btn)

    def _get_page(self):
        return self.parent_window.notebook.current_content_widget()

    def on_save_clicked(self):

        def save_exam(page):
            dialog = gui.dialogs.YesNoDialog(
                self.parent_window,
                f'Are you sure you want to save {page.content["name"]}?'
            )
            if dialog._run():
                exam.create_exam(
                    page.content['name'], mode='gui',
                    questions=page.content['questions']
                )
                self.main_window.update_tables()
                self.parent_window.close()
                new_window = gui.windows.ExamWindow(
                    self.parent_window.parent_window, page.content
                )
                new_window.show()

        def overwrite_exam(page):
            dialog = gui.dialogs.YesNoDialog(
                self.parent_window,
                f'Are you sure you want to overwrite {page.content["name"]}?',
                'Changes are irreversible!'
            )
            if dialog._run():
                exam.remove_exam(page.content['name'], message=False)
                exam.create_exam(
                    page.content['name'], mode='gui',
                    questions=page.content['questions'],
                    message=False
                )
                self.main_window.update_tables()
                self.parent_window.close()
                new_window = gui.windows.ExamWindow(
                    self.parent_window.parent_window, page.content
                )
                new_window.show()

        page = self._get_page()
        new_content = page.update_content()
        page.overwrite(new_content)
        exam_name = page.content['name']
        db_exam = config.EXAMS.find_one({'name': exam_name})
        try:
            db_exam.pop('_id')
            if page.content == db_exam:
                gui.dialogs.OKDialog(
                    self.parent_window, 'Nothing to save.',
                    f'No changes were made to {exam_name}.'
                )._run()
                return
        except AttributeError:
            pass
        if not db_exam:
            save_exam(page)
        else:
            overwrite_exam(page)

    def on_delete_clicked(self):
        page = self._get_page()
        new_content = page.update_content()
        page.overwrite(new_content)
        exam_name = page.content['name']
        db_exam = config.EXAMS.find_one({'name': exam_name})

        if not db_exam:
            gui.dialogs.OKDialog(
                self.parent_window, 'Nothing to delete.',
                f"{exam_name} doesn't exist in database!"
            )._run()
            return

        dialog = gui.dialogs.YesNoDialog(
            self.parent_window,
            f'Are you sure you want to delete {exam_name}?',
            'Changes are irreversible!'
        )
        if dialog._run():
            exam.remove_exam(exam_name)
            self.main_window.update_tables()
            self.parent_window.close()


class ExamCreationControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)

        create_btn = QPushButton('Create exam')
        create_btn.clicked.connect(self.parent_window.create_exam)
        self._pack_start(create_btn)

        update_btn = QPushButton('Update report')
        update_btn.clicked.connect(self.parent_window.update_report)
        self._pack_end(update_btn)


class ExamEvaluationControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)

        ok_btn = QPushButton('OK')
        ok_btn.clicked.connect(self.parent_window.evaluate)
        self._pack_start(ok_btn)

        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.parent_window.close)
        self._pack_end(cancel_btn)


class DatabaseUpdateControlPanel(_ActionBar):

    def __init__(self, parent_window):
        super().__init__(parent_window)

        self.update_btn = QPushButton('Update')
        self.update_btn.clicked.connect(self.parent_window.apply_update)
        self._pack_start(self.update_btn)

        self.undo_btn = QPushButton('Undo last update')
        self.undo_btn.clicked.connect(self.parent_window.undo)
        self._pack_start(self.undo_btn)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.parent_window.close)
        self._pack_end(close_btn)
