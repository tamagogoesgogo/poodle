from PySide6.QtWidgets import (
    QTableView, QAbstractItemView, QHeaderView,
    QApplication, QMenu, QSizePolicy
)
from PySide6.QtCore import Qt, QSortFilterProxyModel, QRect, QSize, QModelIndex
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QBrush, QColor,
    QKeySequence, QFont, QPainter, QPen
)
from poodle import config
from poodle import question
from poodle import exam
import core
import gui.windows
import gui.dialogs
import gui.theming
import copy
import http.server
import os
import re
import subprocess
import threading
import numpy as np
import pandas as pd


UNDO_DEPTH = 25             # how many table edits Ctrl+Z can step back through
NARROW_COLUMN_MIN = 48      # a column that only labels the rows stays slim
NARROW_COLUMN_MAX = 260     # but never takes over the table


# ---------------------------------------------------------------------------
# Question treeview
# ---------------------------------------------------------------------------

class _QuestionFilterProxy(QSortFilterProxyModel):

    def __init__(self, treeview):
        super().__init__()
        self._tv = treeview

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        try:
            search = self._tv.parent_window.control.search_entry.text()
            field = self._tv.parent_window.control.fields_combo.currentText()
        except AttributeError:
            return True

        if not search:
            return True

        model = self.sourceModel()

        def cell(col: int) -> str:
            item = model.item(source_row, col)
            return item.text() if item else ''

        numeric_fields = ['appearances', 'difficulty', 'time_est']

        if field == 'name':
            return bool(re.search(search, cell(0)))
        elif field in ('question', 'moodle_type', 'family_type'):
            q = config.QUESTIONS.find_one({'name': cell(0)})
            if q is None:
                return False
            return bool(re.search(search, q.get(field, '')))
        elif field in numeric_fields:
            col_idx = self._tv._col_names.index(field) if field in self._tv._col_names else -1
            if col_idx < 0:
                return True
            val = cell(col_idx)
            is_expression = bool(re.match(r'\s*([<>]=?|\!=)\s*\d+\.?\d*\s*$', search))
            if is_expression:
                try:
                    return eval(val + search)
                except Exception:
                    return True
            return val == search
        return True


def _column_types(df) -> list:
    """
    The Python type of each column: int, float, or str for anything else.
    Asked of pandas rather than compared with numpy dtypes, because pandas 3
    keeps text in its own string dtype instead of object, which the old
    comparison rejected with a TypeError, and the tables would not open.
    """
    types = []
    for c in df.columns:
        if df[c].isna().all():
            types.append(str)
        elif pd.api.types.is_integer_dtype(df[c]):
            types.append(int)
        elif pd.api.types.is_float_dtype(df[c]):
            types.append(float)
        else:
            types.append(str)
    return types


class QuestionTreeview(QTableView):

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent
        self._col_names = []
        self._model = QStandardItemModel()
        self._proxy = _QuestionFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()
        self.setAlternatingRowColors(True)

        self.build_table(*self.load_data())

    def load_data(self):
        def row_to_list(df):
            for row in df.values.tolist():
                yield [x for x in row[:4]] + [str(x) for x in row[4:]]

        exam_list = sorted(set(e['name'] for e in config.EXAMS.find()))
        df = pd.DataFrame(
            sorted([
                [q['name'], q['difficulty'], q['time_est']] +
                [round(q['in_exams'][e] / q['points'], 2)
                 if e in q['in_exams'] else '.'
                 for e in exam_list]
                for q in config.QUESTIONS.find()
                if q['name'][-2:] != '00'
            ]),
            columns=['question', 'difficulty', 'time_est'] + exam_list
        )
        transform = lambda x: int(type(x) == float)
        appearances = df[exam_list].map(transform).sum(axis=1) if exam_list else pd.Series(0, index=df.index)
        df.insert(1, 'appearances', appearances.astype('int64'))

        data = list(row_to_list(df))
        if df.empty:
            column_types = [str, int, int, int]
        else:
            column_types = _column_types(df)
        column_names = ['question', 'appearances', 'difficulty', 'time_est'] + list(df.columns)[4:]

        return data, column_types, column_names

    def build_table(self, data, col_types, col_names) -> None:
        self._col_names = col_names
        self._model.clear()
        self._model.setHorizontalHeaderLabels(col_names)
        for row in data:
            items = [QStandardItem(str(v)) for v in row]
            for item in items:
                item.setEditable(False)
            self._model.appendRow(items)

    def reload(self):
        data, col_types, col_names = self.load_data()
        self.build_table(data, col_types, col_names)

    def refilter(self):
        self._proxy.invalidateFilter()

    def _selected_name(self, action: str = '') -> str | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            if action:
                gui.dialogs.OKDialog(
                    self.parent_window, 'No question selected.',
                    f'Click a question in the list first, then {action}.'
                )._run()
            return None
        return self._proxy.data(indexes[0])

    def new_question(self) -> None:
        dialog = gui.dialogs.NewQuestionDialog(self.parent_window)
        question_content = dialog._run()
        if question_content:
            new_window = gui.windows.QuestionWindow(self.parent_window, question_content)
            new_window.notebook.question_grid.name_field.setReadOnly(False)
            new_window.notebook.question_grid.family_type_field.setReadOnly(False)
            new_window.show()

    def view_question(self) -> None:
        name = self._selected_name('press View')
        if name is None:
            return
        question_content = config.QUESTIONS.find_one({'name': name})
        question_content.pop('_id')
        gui.windows.QuestionWindow(self.parent_window, question_content).show()

    def delete_question(self) -> None:
        name = self._selected_name('press Delete')
        if name is None:
            return
        dialog = gui.dialogs.YesNoDialog(
            self.parent_window,
            f'Are you sure you want to delete question {name}?',
            'Changes are irreversible!'
        )
        if dialog._run():
            question.remove_question(name)
            self.parent_window.update_tables()

    def add_to_exam(self) -> None:
        if not hasattr(self.parent_window, 'exam_window'):
            dialog = gui.dialogs.NewExamDialog(self.parent_window)
            if not dialog._run():
                return
        name = self._selected_name('press Add to exam')
        if name is None:
            return
        self.parent_window.exam_window.add_question(name)

    def keyPressEvent(self, event):
        key = event.key()
        match key:
            case Qt.Key.Key_N:
                self.new_question()
            case Qt.Key.Key_V:
                self.view_question()
            case Qt.Key.Key_Return:
                self.view_question()
            case Qt.Key.Key_D:
                self.delete_question()
            case Qt.Key.Key_A:
                self.add_to_exam()
            case Qt.Key.Key_F:
                self.refilter()
            case Qt.Key.Key_Q:
                self.parent_window.close()
            case _:
                super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Exam treeview
# ---------------------------------------------------------------------------

class _ExamFilterProxy(QSortFilterProxyModel):

    def __init__(self, treeview):
        super().__init__()
        self._tv = treeview

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        try:
            search = self._tv.parent_window.control.search_entry.text()
            field = self._tv.parent_window.control.fields_combo.currentText()
        except AttributeError:
            return True

        if not search:
            return True

        model = self.sourceModel()

        def cell(col: int) -> str:
            item = model.item(source_row, col)
            return item.text() if item else ''

        numeric_fields = ['points_max', 'points_avg', 'questions', 'difficulty', 'time_est']

        if field == 'name':
            return bool(re.search(search, cell(0)))
        elif field in numeric_fields:
            col_idx = self._tv._col_names.index(field) if field in self._tv._col_names else -1
            if col_idx < 0:
                return True
            val = cell(col_idx)
            is_expression = bool(re.match(r'\s*([<>]=?|\!=)\s*\d+\.?\d*\s*$', search))
            if is_expression:
                try:
                    return eval(val + search)
                except Exception:
                    return True
            return val == search
        return True


class ExamTreeview(QTableView):

    def __init__(self, parent):
        super().__init__()
        self.parent_window = parent
        self._col_names = []
        self._model = QStandardItemModel()
        self._proxy = _ExamFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self.setModel(self._proxy)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()
        self.setAlternatingRowColors(True)

        self.build_table(*self.load_data())

    def load_data(self):
        df = pd.DataFrame(
            sorted([[
                e['name'], e['points_max'], len(e['questions']),
                e['difficulty_avg'], e['time_est']
            ] for e in config.EXAMS.find()]),
            columns=['exam', 'points_max', 'questions', 'difficulty', 'time_est']
        )
        points_avg = []
        for e_name in df['exam']:
            # find_one() returns None for a question that has since been deleted.
            try:
                e = config.EXAMS.find_one({'name': e_name})
                avg = np.round(np.nansum([
                    x[1] * config.QUESTIONS.find_one({'name': x[0]})['points']
                    for x in e['questions_avgs'].items()
                ]), 2)
                points_avg.append(avg)
            except (KeyError, TypeError):
                points_avg.append(0.0)
        df.insert(2, 'points_avg', np.float64(points_avg))
        df = df.round(2)

        data = [row for row in df.values.tolist()]
        if df.empty:
            column_types = [str, float, float, int, float, float]
        else:
            column_types = _column_types(df)
        column_names = ['name', 'points_max', 'points_avg', 'questions', 'difficulty', 'time_est']

        return data, column_types, column_names

    def build_table(self, data, col_types, col_names) -> None:
        self._col_names = col_names
        self._model.clear()
        self._model.setHorizontalHeaderLabels(col_names)
        for row in data:
            items = [QStandardItem(str(v)) for v in row]
            for item in items:
                item.setEditable(False)
            self._model.appendRow(items)

    def reload(self):
        data, col_types, col_names = self.load_data()
        self.build_table(data, col_types, col_names)

    def refilter(self):
        self._proxy.invalidateFilter()

    def _selected_name(self, action: str = '') -> str | None:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            if action:
                gui.dialogs.OKDialog(
                    self.parent_window, 'No exam selected.',
                    f'Click an exam in the list first, then {action}.'
                )._run()
            return None
        return self._proxy.data(indexes[0])

    def new_exam(self) -> None:
        if not hasattr(self.parent_window, 'exam_window'):
            dialog = gui.dialogs.NewExamDialog(self.parent_window)
            dialog._run()
        else:
            gui.dialogs.OKDialog(
                self.parent_window, 'Exam creation already in progress!'
            )._run()

    def view_exam(self) -> None:
        name = self._selected_name('press View')
        if name is None:
            return
        exam_content = config.EXAMS.find_one({'name': name})
        exam_content.pop('_id')
        gui.windows.ExamWindow(self.parent_window, exam_content).show()

    def delete_exam(self) -> None:
        name = self._selected_name('press Delete')
        if name is None:
            return
        dialog = gui.dialogs.YesNoDialog(
            self.parent_window,
            f'Are you sure you want to delete exam {name}?',
            'Changes are irreversible!'
        )
        if dialog._run():
            exam.remove_exam(name)
            self.parent_window.update_tables()

    def evaluate_exam(self) -> None:
        name = self._selected_name('press Evaluate')
        if name is None:
            return
        gui.windows.ExamEvaluationWindow(self.parent_window, name).show()

    def keyPressEvent(self, event):
        key = event.key()
        match key:
            case Qt.Key.Key_N:
                self.new_exam()
            case Qt.Key.Key_V:
                self.view_exam()
            case Qt.Key.Key_Return:
                self.view_exam()
            case Qt.Key.Key_D:
                self.delete_exam()
            case Qt.Key.Key_E:
                self.evaluate_exam()
            case Qt.Key.Key_F:
                self.refilter()
            case Qt.Key.Key_Q:
                self.parent_window.close()
            case _:
                super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Grouped column header view
# ---------------------------------------------------------------------------

class _GroupedHeaderView(QHeaderView):
    """Two-row header: top row spans split-column groups, bottom row shows column names."""

    def __init__(self, parent=None):
        # Set all attributes before super().__init__() so Qt virtual calls are safe.
        self._has_groups = False
        self._flat = []
        self._group_starts = {}
        self._in_group = set()
        super().__init__(Qt.Orientation.Horizontal, parent)

    def load(self, split_header: list, flat_headers: list):
        """Update header data in-place — never recreate the header object."""
        self._flat = flat_headers
        self._has_groups = any(isinstance(h, list) for h in split_header)
        self._group_starts = {}
        self._in_group = set()
        flat_idx = 0
        for h in split_header:
            if isinstance(h, list):
                n = len(h) - 1
                self._group_starts[flat_idx] = (h[0], n)
                for j in range(n):
                    self._in_group.add(flat_idx + j)
                flat_idx += n
            else:
                flat_idx += 1
        self.viewport().update()
        # Tell the parent layout that our sizeHint() changed (height doubles when
        # groups are present) so the table reflows its geometry immediately.
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        try:
            s = super().sizeHint()
        except RuntimeError:
            return QSize(0, 24)
        if getattr(self, '_has_groups', False):
            return QSize(s.width(), s.height() * 2)
        return s

    def paintSection(self, painter, rect: QRect, logical_index: int):
        # For grouped headers, paintEvent() owns all drawing (two-pass approach
        # so group labels can span multiple columns without clip interference).
        # For non-grouped headers, defer to Qt's default.
        try:
            if not getattr(self, '_has_groups', False):
                super().paintSection(painter, rect, logical_index)
        except RuntimeError:
            pass  # C++ object deleted during widget destruction

    def paintEvent(self, event):
        # Guard the entire body: Qt can fire paint events while the C++ header
        # object is already being destroyed (destruction-time event flush).
        try:
            self._do_paint(event)
        except RuntimeError:
            pass

    def _do_paint(self, event):
        has_groups   = getattr(self, '_has_groups',   False)
        flat         = getattr(self, '_flat',         [])
        in_group     = getattr(self, '_in_group',     set())
        group_starts = getattr(self, '_group_starts', {})

        if not has_groups:
            super().paintEvent(event)
            return

        # Painted by hand, so the stylesheet cannot reach it: take the same
        # tokens style.qss uses, from whichever palette is current.
        bg_col     = gui.theming.color('raised')       # header section background
        fg_col     = gui.theming.color('accent_soft')  # column name text
        grp_bg_col = gui.theming.color('mantle')       # group label row background
        grp_fg_col = gui.theming.color('accent')       # group label text
        bdr_col    = gui.theming.color('surface')      # border / divider

        painter = QPainter(self.viewport())
        vp_h = self.viewport().height()
        half = vp_h // 2
        n    = self.count()

        base_font = painter.font()
        bold_font = QFont(base_font)
        bold_font.setBold(True)

        # ── Pass 1: backgrounds + sub-column names (bottom half of grouped cols) ──
        for i in range(n):
            x = self.sectionViewportPosition(i)
            w = self.sectionSize(i)
            if w == 0:
                continue
            painter.fillRect(x, 0, w, vp_h, bg_col)
            painter.setPen(fg_col)
            painter.setFont(base_font)
            name = flat[i] if i < len(flat) else ''
            if i in in_group:
                painter.drawText(
                    QRect(x + 4, half, w - 8, half),
                    Qt.AlignmentFlag.AlignCenter, name
                )
            else:
                painter.drawText(
                    QRect(x + 4, 0, w - 8, vp_h),
                    Qt.AlignmentFlag.AlignCenter, name
                )
            painter.setPen(QPen(bdr_col, 1))
            painter.drawLine(x + w - 1, 0, x + w - 1, vp_h - 1)

        # ── Pass 2: group labels spanning their full widths ───────────────────────
        for start_col, (label, span) in group_starts.items():
            gx = self.sectionViewportPosition(start_col)
            gw = sum(self.sectionSize(start_col + j) for j in range(span))
            painter.fillRect(gx, 0, gw, half, grp_bg_col)
            painter.setPen(grp_fg_col)
            painter.setFont(bold_font)
            painter.drawText(
                QRect(gx + 4, 0, gw - 8, half),
                Qt.AlignmentFlag.AlignCenter, label
            )
            painter.setPen(QPen(bdr_col, 1))
            painter.drawLine(gx, half, gx + gw - 1, half)

        # Bottom border of entire header
        painter.setPen(QPen(bdr_col, 1))
        painter.drawLine(0, vp_h - 1, self.viewport().width(), vp_h - 1)


# ---------------------------------------------------------------------------
# Table treeview (for question tables)
# ---------------------------------------------------------------------------

class TableTreeView(QTableView):

    def __init__(self, parent, table):
        super().__init__()
        self.parent_window = parent
        self._model = QStandardItemModel()
        self.split_header = []
        self.row_headers = False

        self._undo_stack = []
        self._suspend_snapshots = False

        self.setModel(self._model)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        # A block can be selected, copied, cleared and pasted over, the way a
        # spreadsheet behaves — this is a data-entry grid, not a list.
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed |
            QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().hide()
        self.setShowGrid(True)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.build_table(table)
        # The group and sub-row colours are brushed onto the model's items, so
        # they only change when the rows are rebuilt.
        gui.theming.scale.palette_changed.connect(self._restyle)

    def _restyle(self) -> None:
        self.build_table(self._collect_table())

    def _snapshot(self) -> None:
        """Remember the table before a change, so Ctrl+Z can bring it back.

        Operations built out of other operations (a paste adds rows and
        columns) record one step, not one per part.
        """
        if self._suspend_snapshots:
            return
        self._undo_stack.append(copy.deepcopy(self._collect_table()))
        del self._undo_stack[:-UNDO_DEPTH]

    def undo(self) -> None:
        if self._undo_stack:
            self.build_table(self._undo_stack.pop())

    def build_table(self, table):
        if isinstance(table, dict):
            self.row_headers = table.get('row_headers', False)
            table = table['data']
        # For plain-list calls (internal rebuilds) keep the existing row_headers value.

        self.split_header = table[0]

        # Flatten headers
        flat_headers = []
        for h in table[0]:
            if isinstance(h, list):
                flat_headers.extend(h[1:])
            else:
                flat_headers.append(h)

        n_cols = len(flat_headers)

        # Model has n_cols data columns + 1 hidden meta column.
        # Un-hide everything first — the view's hidden-column bitmap persists
        # across model rebuilds, so a column that was the old meta at index N
        # stays hidden even when it becomes a data column at the same index.
        for i in range(self._model.columnCount()):
            self.setColumnHidden(i, False)
        self.clearSpans()
        self._model.clear()
        self._model.setColumnCount(n_cols + 1)
        self._model.setHorizontalHeaderLabels(flat_headers + ['__meta__'])

        # From the palette, not fixed light greys: the sub-row background used
        # to be near-white under light themed text, which was unreadable.
        group_bg   = QBrush(gui.theming.color('surface_alt'))
        group_fg   = QBrush(gui.theming.color('text'))
        sub_bg     = QBrush(gui.theming.color('raised'))
        bold_font  = QFont()
        bold_font.setBold(True)
        no_edit    = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

        for item in table[1:]:
            if isinstance(item, dict) and 'group' in item:
                # The label occupies the first column and spans the group's
                # rows, exactly as it is written to Moodle. The sub-rows'
                # remaining columns hold the data; their first column belongs
                # to the label, so it is not offered for editing.
                label = item['group']
                sub_rows = item['rows'] or [[''] * n_cols]
                first_row = self._model.rowCount()

                for index, sub in enumerate(sub_rows):
                    padded = list(sub) + [''] * max(0, n_cols - len(sub))
                    label_item = QStandardItem(label if index == 0 else '')
                    label_item.setBackground(group_bg)
                    label_item.setForeground(group_fg)
                    label_item.setFont(bold_font)
                    if index:
                        label_item.setFlags(no_edit)   # hidden under the span
                    row_items = [label_item]
                    for value in padded[1:n_cols]:
                        data_item = QStandardItem(
                            '' if value is None else str(value)
                        )
                        data_item.setBackground(sub_bg)
                        if value is None:
                            data_item.setFlags(no_edit)
                        row_items.append(data_item)
                    row_items.append(QStandardItem(
                        ('group:' if index == 0 else 'sub:') + label
                    ))
                    self._model.appendRow(row_items)

                if len(sub_rows) > 1:
                    self.setSpan(first_row, 0, len(sub_rows), 1)
            else:
                padded = list(item) + [''] * max(0, n_cols - len(item))
                row_items = []
                for value in padded[:n_cols]:
                    cell = QStandardItem('' if value is None else str(value))
                    if value is None:
                        cell.setFlags(no_edit)      # covered by a merged cell
                    row_items.append(cell)
                row_items.append(QStandardItem(''))
                self._model.appendRow(row_items)

        # Merged cells span their covered columns
        for model_row, (row, start) in enumerate(self._model_rows(table[1:])):
            for _, span, col in self._row_cells(row, start):
                if span > 1 and col + span <= n_cols:
                    self.setSpan(model_row, col, 1, span)

        # Create header once; update in-place on subsequent calls to avoid
        # destroying a Qt-owned object while it may still be painting.
        if not hasattr(self, '_header'):
            self._header = _GroupedHeaderView(self)
            self.setHorizontalHeader(self._header)
            # Equal widths, like the exported table, which lays every column
            # out at 100/n %. With stretchLastSection the final column took all
            # the spare width and the table looked lopsided next to its export.
            self._header.setStretchLastSection(False)
            self._header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._header.load(table[0], flat_headers)

        # A column with no header of its own only labels the rows, so it is
        # kept to its contents while the rest share the width — the same
        # proportions the exported table is given.
        narrow = core.MoodleQuestion._narrow_columns(table[0])
        metrics = self.fontMetrics()
        for index in range(n_cols):
            if index not in narrow:
                self._header.setSectionResizeMode(
                    index, QHeaderView.ResizeMode.Stretch
                )
                continue
            # Measured here rather than left to resizeToContents, which skips
            # the cells a spanning row header covers and would clip its text.
            widest = max(
                [metrics.horizontalAdvance(
                    self._model.item(row, index).text()
                    if self._model.item(row, index) else ''
                ) for row in range(self._model.rowCount())] or [0]
            )
            self._header.setSectionResizeMode(
                index, QHeaderView.ResizeMode.Interactive
            )
            self._header.resizeSection(
                index, min(NARROW_COLUMN_MAX, max(NARROW_COLUMN_MIN, widest + 28))
            )

        self.setColumnHidden(n_cols, True)

    # ── Shape of the table ──────────────────────────────────────────────────
    #
    # A header is a list whose entries are either a column name or a split
    # group ['Label', 'sub', 'sub', ...]. These helpers convert between that
    # and a flat [(name, group_label_or_None), ...] list, which is what the
    # column operations below work on.

    @staticmethod
    def _flatten_header(header: list) -> list:
        flat = []
        for item in header:
            if isinstance(item, list):
                flat.extend((sub, item[0]) for sub in item[1:])
            else:
                flat.append((item, None))
        return flat

    @staticmethod
    def _structure_header(flat: list) -> list:
        header = []
        for name, group in flat:
            if group is not None and header and isinstance(header[-1], list) \
                    and header[-1][0] == group:
                header[-1].append(name)
            elif group is not None:
                header.append([group, name])
            else:
                header.append(name)
        # A group down to one column is no longer a split
        return [h[1] if isinstance(h, list) and len(h) == 2 else h for h in header]

    @classmethod
    def _map_rows(cls, rows: list, fn) -> list:
        """Apply fn to every data row, reaching inside row groups."""
        mapped = []
        for row in rows:
            if isinstance(row, dict) and 'group' in row:
                mapped.append({'group': row['group'],
                               'rows': [fn(sub) for sub in row['rows']]})
            else:
                mapped.append(fn(row))
        return mapped

    def _column_names(self) -> list:
        return [name for name, _ in
                self._flatten_header(self._collect_table()[0])]

    def set_columns(self, names: list) -> None:
        """Rename, add and remove columns, keeping the split groups intact.

        Names map onto the existing columns in order: extra names become new
        columns at the end, missing ones remove the last columns and their data.
        """
        self._snapshot()
        current = self._collect_table()
        old_flat = self._flatten_header(current[0])

        new_flat = [
            (name, old_flat[i][1] if i < len(old_flat) else None)
            for i, name in enumerate(names)
        ]
        new_header = self._structure_header(new_flat)
        width = len(new_flat)

        self.build_table([new_header] + self._map_rows(
            current[1:], lambda row: (list(row) + [''] * width)[:width]
        ))

    def insert_column(self, at: int, group=None) -> None:
        self._snapshot()
        current = self._collect_table()
        flat = self._flatten_header(current[0])
        at = max(0, min(at, len(flat)))
        flat.insert(at, ('', group))

        def insert_cell(row):
            row = list(row)
            row.insert(at, '')
            return row

        self.build_table([self._structure_header(flat)] +
                         self._map_rows(current[1:], insert_cell))

    def delete_column(self, at: int) -> None:
        self._snapshot()
        current = self._collect_table()
        flat = self._flatten_header(current[0])
        if not 0 <= at < len(flat) or len(flat) == 1:
            return                      # a table keeps at least one column
        flat.pop(at)

        def drop_cell(row):
            row = list(row)
            if at < len(row):
                row.pop(at)
            return row

        self.build_table([self._structure_header(flat)] +
                         self._map_rows(current[1:], drop_cell))

    def _locate(self, model_row: int):
        """Which collected entry a model row belongs to, and which sub-row."""
        n_cols = self._model.columnCount() - 1
        total = self._model.rowCount()

        def meta_of(row):
            item = self._model.item(row, n_cols)
            return item.text() if item else ''

        entry, row = 0, 0
        while row < total:
            if meta_of(row).startswith('group:'):
                size = 1
                while row + size < total and meta_of(row + size).startswith('sub:'):
                    size += 1
                if model_row < row + size:
                    return entry, model_row - row
                row += size
            else:
                if model_row == row:
                    return entry, None
                row += 1
            entry += 1
        return None, None

    def insert_row(self, model_row: int, below: bool = False) -> None:
        """Insert an empty row by a model row — inside a group if it lands in one."""
        self._snapshot()
        current = self._collect_table()
        width = len(self._flatten_header(current[0]))
        entry, sub = self._locate(model_row)

        if entry is None:                       # past the last row
            current.append([''] * width)
        elif sub is None:
            # current[0] is the header, so entry n lives at index n + 1
            current.insert(entry + 1 + int(below), [''] * width)
        else:
            current[entry + 1]['rows'].insert(sub + int(below), [''] * width)
        self.build_table(current)

    def delete_row(self, model_row: int) -> None:
        self._snapshot()
        current = self._collect_table()
        entry, sub = self._locate(model_row)
        if entry is None:
            return

        if sub is None:
            current.pop(entry + 1)
        else:
            group = current[entry + 1]
            group['rows'].pop(sub)
            if not group['rows']:
                current.pop(entry + 1)
        self.build_table(current)

    def merge_cells(self, button=None) -> None:
        """Join the selected cells of one row into a cell spanning them.

        A Fallzahl that belongs to both columns of its group is written once,
        across both, instead of leaving the second column blank.
        """
        indexes = [i for i in self.selectedIndexes()
                   if i.column() < self._model.columnCount() - 1]
        rows = {i.row() for i in indexes}
        columns = sorted({i.column() for i in indexes})

        if len(rows) != 1 or len(columns) < 2:
            gui.dialogs.OKDialog(
                self.parent_window, 'Select the cells to merge first.',
                'Merging joins two or more cells next to each other in the '
                'same row, so the text spans them.'
            )._run()
            return

        model_row = rows.pop()
        first, last = columns[0], columns[-1]
        if self._meta(model_row).startswith('group:') and first == 0:
            gui.dialogs.OKDialog(
                self.parent_window, 'That column holds the row header.',
                'Merge the cells beside it instead.'
            )._run()
            return

        self._snapshot()
        current = self._collect_table()
        ordered = self._model_rows(current[1:])
        row, _ = ordered[model_row]
        for column in range(first + 1, last + 1):
            row[column] = None
        self.build_table(current)

    def unmerge_cells(self, button=None) -> None:
        """Split a merged cell back into one cell per column."""
        indexes = self.selectedIndexes()
        if not indexes:
            return

        self._snapshot()
        current = self._collect_table()
        ordered = self._model_rows(current[1:])
        for model_row in {i.row() for i in indexes}:
            row, _ = ordered[model_row]
            for column, value in enumerate(row):
                if value is None:
                    row[column] = ''
        self.build_table(current)

    def _show_context_menu(self, position) -> None:
        index = self.indexAt(position)
        menu = QMenu(self)

        if index.isValid():
            row, col = index.row(), index.column()
            group = self._flatten_header(self._collect_table()[0])[col][1]
            menu.addAction('Insert row above', lambda: self.insert_row(row))
            menu.addAction('Insert row below',
                           lambda: self.insert_row(row, below=True))
            menu.addAction('Delete this row', lambda: self.delete_row(row))
            menu.addSeparator()
            menu.addAction('Insert column before',
                           lambda: self.insert_column(col, group))
            menu.addAction('Insert column after',
                           lambda: self.insert_column(col + 1, group))
            menu.addAction('Delete this column', lambda: self.delete_column(col))
            menu.addSeparator()
            menu.addAction('Merge selected cells', self.merge_cells)
            menu.addAction('Unmerge cells', self.unmerge_cells)
        else:
            menu.addAction('Add row', self.add_row)

        menu.exec(self.viewport().mapToGlobal(position))

    def _collect_table(self) -> list:
        n_cols = self._model.columnCount() - 1
        flat_titles = [
            (self._model.horizontalHeaderItem(i).text()
             if self._model.horizontalHeaderItem(i) else '')
            for i in range(n_cols)
        ]

        # Reconstruct split header from self.split_header
        reconstructed_header = []
        flat_idx = 0
        for h in self.split_header:
            if isinstance(h, list):
                n_sub = len(h) - 1
                reconstructed_header.append([h[0]] + flat_titles[flat_idx:flat_idx + n_sub])
                flat_idx += n_sub
            else:
                reconstructed_header.append(flat_titles[flat_idx])
                flat_idx += 1

        def cell(row: int, col: int) -> str:
            item = self._model.item(row, col)
            return item.text() if item else ''

        def cells(row: int, first: int) -> list:
            """A row's cells, with None where a merged cell covers them."""
            values, col = [], first
            while col < n_cols:
                span = self.columnSpan(row, col)
                values.append(cell(row, col))
                values.extend([None] * (span - 1))
                col += span
            return values

        def meta_of(row: int) -> str:
            return cell(row, n_cols)

        result_rows = []
        row = 0
        total_rows = self._model.rowCount()
        while row < total_rows:
            if meta_of(row).startswith('group:'):
                # The label is read from its cell, not from the meta column, so
                # that renaming it in place is picked up. Column 0 of every
                # sub-row belongs to that label and is stored empty.
                label = cell(row, 0)
                sub_rows = [[''] + cells(row, 1)]
                row += 1
                while row < total_rows and meta_of(row).startswith('sub:'):
                    sub_rows.append([''] + cells(row, 1))
                    row += 1
                result_rows.append({'group': label, 'rows': sub_rows})
            else:
                result_rows.append(cells(row, 0))
                row += 1

        return [reconstructed_header] + result_rows

    def save_table(self, button=None):
        output_table = self._collect_table()
        key = self.parent_window.table_key
        # parent_window is TableWindow; its parent_window is QuestionWindow
        question_window = self.parent_window.parent_window
        question_grid = question_window.notebook.question_grid
        if self.row_headers:
            question_grid.tables_field.data[key] = {
                'data': output_table,
                'row_headers': True,
            }
        else:
            question_grid.tables_field.data[key] = output_table
        question_window.control.on_save_clicked()

    def edit_columns(self, button=None):
        dialog = gui.dialogs.EditColumnsDialog(self.parent_window, self)
        dialog._run()

    def _selected_columns(self) -> list:
        return sorted({index.column() for index in self.selectedIndexes()
                       if index.column() < self._model.columnCount() - 1})

    def _selected_rows(self) -> list:
        return sorted({index.row() for index in self.selectedIndexes()})

    def span_columns(self, button=None):
        """Put one header across the selected columns.

        With nothing useful selected, fall back to creating a new spanned
        group of empty columns.
        """
        columns = self._selected_columns()
        if not columns:
            self.add_split_column()         # nothing selected: a new group
            return
        if len(columns) < 2:
            gui.dialogs.OKDialog(
                self.parent_window, 'Select at least two columns to span.',
                'Drag across the columns that belong under one header, then '
                'press Span columns. With nothing selected, a new spanned '
                'group of columns is added instead.'
            )._run()
            return

        current = self._collect_table()
        flat = self._flatten_header(current[0])
        first, last = columns[0], columns[-1]

        label = gui.dialogs.SpanLabelDialog(
            self.parent_window, 'columns', flat[first][1] or ''
        )._run()
        if not label:
            return

        self._snapshot()
        for column in range(first, last + 1):
            flat[column] = (flat[column][0], label)
        self.build_table([self._structure_header(flat)] + current[1:])

    def _free_leading_columns(self, header: list) -> int:
        """How many columns at the left no spanning column header covers."""
        free = 0
        for _, group in self._flatten_header(header):
            if group is not None:
                break
            free += 1
        return free

    def _ensure_label_column(self, table: list, rows: list = None) -> list:
        """Make room at the left for a spanning row header.

        A spanning row header lives in the first column, which mirrors the way
        a spanning column header lives in the first header row. So that column
        has to be free: if a column span already covers it, a label such as
        'students' would otherwise land in the 'apples' column and push its
        figures aside.

        A new group of empty rows also needs somewhere to name those rows —
        the counterpart of the sub-column names under a spanning column header
        — so it takes two columns at the left: one for the header, one for the
        row names. Spanning rows that already exist takes only the header
        column, since those rows carry their own values already.
        """
        free = self._free_leading_columns(table[0])

        if rows is None:
            missing = max(0, 2 - free)              # header + row names
        else:
            values = {str(row[0]).strip() for row in rows
                      if row and row[0] is not None}
            # One value repeated down a free first column is the header itself
            consumable = free >= 1 and len(values - {''}) <= 1
            missing = 0 if consumable else 1

        if not missing:
            return table

        added = [('', None)] * missing
        return [self._structure_header(added + self._flatten_header(table[0]))] + \
            self._map_rows(table[1:], lambda row: [''] * missing + list(row))

    def span_rows(self, button=None):
        """Put one header down the first column across the selected rows."""
        rows = self._selected_rows()
        if not rows:
            self.add_split_row()            # nothing selected: a new group
            return
        if len(rows) < 2:
            gui.dialogs.OKDialog(
                self.parent_window, 'Select at least two rows to span.',
                'Drag down the rows that belong under one header, then press '
                'Span rows. With nothing selected, a new spanned group of '
                'rows is added instead.'
            )._run()
            return

        entries = []
        for row in range(rows[0], rows[-1] + 1):
            entry, sub = self._locate(row)
            if entry is None or sub is not None:
                gui.dialogs.OKDialog(
                    self.parent_window, 'Those rows cannot be spanned.',
                    'Some of them already sit under a spanning header. '
                    'Unspan that one first.'
                )._run()
                return
            entries.append(entry)

        current = self._collect_table()
        first, last = entries[0], entries[-1]

        widened = self._ensure_label_column(current, current[first + 1:last + 2])
        if widened is current:
            # Column 0 is free: offer what is written there as the label,
            # since it is about to become the header.
            default = str(current[first + 1][0] or '')
        else:
            current, default = widened, ''

        label = gui.dialogs.SpanLabelDialog(
            self.parent_window, 'rows', default
        )._run()
        if not label:
            return

        self._snapshot()
        spanned = {
            'group': label,
            'rows': [[''] + list(row)[1:] for row in current[first + 1:last + 2]],
        }
        self.build_table(
            [current[0]] + current[1:first + 1] + [spanned] + current[last + 2:]
        )

    def add_split_column(self, button=None):
        dialog = gui.dialogs.AddSplitColumnDialog(self.parent_window)
        split_def = dialog._run()
        if split_def is None:
            return

        self._snapshot()
        current_data = self._collect_table()
        n_sub = len(split_def) - 1
        header = current_data[0]

        if len(header) == 1 and header[0] == '':
            new_header = [split_def]
            new_rows = [
                [''] * n_sub for item in current_data[1:]
                if isinstance(item, list)
            ]
        else:
            new_header = list(header) + [split_def]
            new_rows = []
            for item in current_data[1:]:
                if isinstance(item, dict) and 'group' in item:
                    new_rows.append({
                        'group': item['group'],
                        'rows': [sub + [''] * n_sub for sub in item['rows']],
                    })
                else:
                    new_rows.append(list(item) + [''] * n_sub)

        self.build_table([new_header] + new_rows)

    def unsplit_column(self, button=None):
        split_groups = [
            (i, h) for i, h in enumerate(self.split_header)
            if isinstance(h, list)
        ]
        if not split_groups:
            return

        if len(split_groups) == 1:
            group_idx = split_groups[0][0]
        else:
            names = [h[0] for _, h in split_groups]
            dialog = gui.dialogs.UnsplitColumnDialog(self.parent_window, names)
            chosen = dialog._run()
            if chosen is None:
                return
            group_idx = split_groups[chosen][0]

        self._snapshot()
        current_data = self._collect_table()
        new_header = []
        for i, h in enumerate(current_data[0]):
            if i == group_idx and isinstance(h, list):
                new_header.extend(h[1:])
            else:
                new_header.append(h)

        self.build_table([new_header] + current_data[1:])

    def rename_group_labels(self, button=None):
        split_groups = [
            (i, h) for i, h in enumerate(self.split_header)
            if isinstance(h, list)
        ]
        if not split_groups:
            return

        names = [h[0] for _, h in split_groups]
        dialog = gui.dialogs.RenameGroupLabelsDialog(self.parent_window, names)
        new_names = dialog._run()
        if new_names is None:
            return

        self._snapshot()
        current_data = self._collect_table()
        new_header = list(current_data[0])
        for (idx, old_h), new_name in zip(split_groups, new_names):
            new_header[idx] = [new_name] + old_h[1:]

        self.build_table([new_header] + current_data[1:])

    def toggle_row_headers(self, checked: bool):
        self.row_headers = checked

    def add_split_row(self, button=None):
        dialog = gui.dialogs.AddSplitRowDialog(self.parent_window)
        result = dialog._run()
        if result is None:
            return
        label, n_sub = result
        self._snapshot()
        # The header needs the first column to itself; if a spanning column
        # header already covers that column, one is added for it.
        current = self._ensure_label_column(self._collect_table())
        # Count flat data columns so sub-rows have the right width.
        n_flat = sum(len(h) - 1 if isinstance(h, list) else 1 for h in current[0])
        new_group = {
            'group': label,
            'rows': [[''] * n_flat for _ in range(n_sub)],
        }
        # The group takes the place of the single blank row a table is born
        # with, instead of sitting under it. Only that one: a row the user
        # asked for is kept even while it is still empty, and so is every span
        # already in the table.
        existing = current[1:]
        if len(existing) == 1 and self._is_untouched_row(existing[0]):
            existing = []
        self.build_table([current[0]] + existing + [new_group])

    def unsplit_row(self, button=None):
        self._snapshot()
        current = self._collect_table()
        groups = [
            item['group']
            for item in current[1:]
            if isinstance(item, dict) and 'group' in item
        ]
        if not groups:
            return

        if len(groups) == 1:
            chosen_label = groups[0]
        else:
            dialog = gui.dialogs.UnsplitColumnDialog(
                self.parent_window, groups, 'Select row group to unsplit:'
            )
            chosen = dialog._run()
            if chosen is None:
                return
            chosen_label = groups[chosen]

        new_data = [current[0]]
        for item in current[1:]:
            if isinstance(item, dict) and item.get('group') == chosen_label:
                # Flatten sub-rows into plain rows. Their first column was the
                # group label's; the label moves into it rather than being lost.
                for index, sub in enumerate(item['rows']):
                    plain = list(sub)
                    plain[0] = chosen_label if index == 0 else ''
                    new_data.append(plain)
            else:
                new_data.append(item)
        self.build_table(new_data)

    @staticmethod
    def _clipboard_rows() -> list:
        """Clipboard text as a rectangular block, tab- or comma-separated."""
        text = QApplication.clipboard().text()
        if not text:
            return []

        rows = []
        for line in text.strip().split('\n'):
            line = line.rstrip('\r')
            if '\t' in line:
                rows.append(line.split('\t'))
            else:
                rows.append([c.strip().strip('"') for c in line.split(',')])

        width = max(len(row) for row in rows)
        return [row + [''] * (width - len(row)) for row in rows]

    @staticmethod
    def _is_untouched_row(row) -> bool:
        """A plain row with nothing in it — not a span, which is structure."""
        return (isinstance(row, list)
                and not any(str('' if cell is None else cell).strip()
                            for cell in row))

    @staticmethod
    def _is_blank(table: list) -> bool:
        """A table nobody has put anything into yet."""
        for row in table:
            for cell in (row['rows'] if isinstance(row, dict) else [row]):
                if any(str(value).strip() for value in cell):
                    return False
        return True

    def paste_csv(self, button=None):
        """Paste at the selected cell, or fill a still-empty table outright.

        Pasting into a table that already has a header must not throw that
        header away, so the block lands at the selection and grows the table
        only as far as it needs to.
        """
        rows = self._clipboard_rows()
        if not rows:
            return

        self._snapshot()
        current = self._collect_table()
        if self._is_blank(current):
            self.row_headers = False
            self.build_table(rows)
            return

        self._suspend_snapshots = True
        try:
            self._paste_at_selection(rows)
        finally:
            self._suspend_snapshots = False

    def _paste_at_selection(self, rows: list) -> None:

        index = self.currentIndex()
        start_row = index.row() if index.isValid() else self._model.rowCount()
        start_col = index.column() if index.isValid() else 0

        width = start_col + len(rows[0])
        if width > self._model.columnCount() - 1:
            self.set_columns(
                self._column_names() +
                [''] * (width - (self._model.columnCount() - 1))
            )
        while self._model.rowCount() < start_row + len(rows):
            self.add_row()

        for r, line in enumerate(rows):
            for c, value in enumerate(line):
                item = self._writable(start_row + r, start_col + c)
                if item:                    # skips a row group's label column
                    item.setText(value)

        self.build_table(self._collect_table())

    def preview_table(self, button=None):
        html_bytes = self._make_preview_html(
            self._collect_table(), self.row_headers
        ).encode('utf-8')

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(('127.0.0.1', 0), _Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        subprocess.Popen(['xdg-open', f'http://127.0.0.1:{port}'])

    @staticmethod
    def _model_rows(rows):
        """Every data row in model order as (row, first_data_column).

        A row group's first column holds its spanning header, so its cells
        start one column in.
        """
        ordered = []
        for row in rows:
            if isinstance(row, dict) and 'group' in row:
                ordered.extend((sub, 1) for sub in row['rows'])
            else:
                ordered.append((row, 0))
        return ordered

    @staticmethod
    def _row_cells(row, start=0):
        """Walk a row as (value, colspan, index) — the exporter's own rule."""
        return core.MoodleQuestion._row_cells(row, start)

    def _make_preview_html(self, data: list, row_headers: bool) -> str:
        widths = core.MoodleQuestion._column_widths(data[0])
        has_split_cols = any(isinstance(h, list) for h in data[0])
        base = 'border:1px solid #888; padding:6px; text-align:center;'
        th_s = base + ' font-weight:bold; background:#f0f0f0;'
        td_even = base + ' background:#ffffff;'
        td_odd = base + ' background:#f0f0f0;'
        th_rowgroup = base + ' font-weight:bold; background:#c0c0c0; vertical-align:middle;'
        td_sub = base + ' background:#dde8ff;'

        rows_html = []
        sub_headers = []
        tr_cells = []
        flat_index = 0
        for h in data[0]:
            if isinstance(h, list):
                n_sub = len(h) - 1
                w = widths(flat_index, n_sub)
                tr_cells.append(
                    f'<th colspan="{n_sub}" style="{th_s} width:{w};">{h[0]}</th>'
                )
                sub_headers.extend((sub, flat_index + offset)
                                   for offset, sub in enumerate(h[1:]))
                flat_index += n_sub
            else:
                w = widths(flat_index)
                rs = ' rowspan="2"' if has_split_cols else ''
                va = ' vertical-align:middle;' if has_split_cols else ''
                tr_cells.append(f'<th{rs} style="{th_s}{va} width:{w};">{h}</th>')
                flat_index += 1
        rows_html.append(f'<tr>{"".join(tr_cells)}</tr>')

        if has_split_cols:
            rows_html.append(
                '<tr>' +
                ''.join(f'<th style="{th_s} width:{widths(i)};">{sh}</th>'
                        for sh, i in sub_headers) +
                '</tr>'
            )

        reg_row_idx = 0
        for item in data[1:]:
            w = widths(0)       # column 0, where a spanning row header sits
            if isinstance(item, dict) and 'group' in item:
                label = item['group']
                sub_rows = item['rows']
                n_sub = len(sub_rows)
                for si, sub_row in enumerate(sub_rows):
                    tr_cells = []
                    if si == 0:
                        tr_cells.append(
                            f'<th rowspan="{n_sub}" scope="rowgroup"'
                            f' style="{th_rowgroup} width:{w};">{label}</th>'
                        )
                    for value, span, index in self._row_cells(sub_row, 1):
                        cw = widths(index, span)
                        cs = f' colspan="{span}"' if span > 1 else ''
                        tr_cells.append(
                            f'<td{cs} style="{td_sub} width:{cw};">{value}</td>'
                        )
                    rows_html.append(f'<tr>{"".join(tr_cells)}</tr>')
            else:
                td_s = td_even if reg_row_idx % 2 == 0 else td_odd
                reg_row_idx += 1
                tr_cells = []
                for value, span, index in self._row_cells(item):
                    cw = widths(index, span)
                    cs = f' colspan="{span}"' if span > 1 else ''
                    if row_headers and index == 0:
                        tr_cells.append(
                            f'<th{cs} scope="row" style="{th_s} width:{cw};">{value}</th>'
                        )
                    else:
                        tr_cells.append(
                            f'<td{cs} style="{td_s} width:{cw};">{value}</td>'
                        )
                rows_html.append(f'<tr>{"".join(tr_cells)}</tr>')

        table = (
            '<table style="table-layout:fixed;width:100%;border-collapse:collapse;">\n'
            + '\n'.join(rows_html) +
            '\n</table>'
        )
        return (
            '<!DOCTYPE html>\n<html><head><meta charset="utf-8">\n'
            '<title>Table Preview</title>\n'
            '<style>body{font-family:sans-serif;padding:20px;}'
            'table{margin-top:10px;}</style>\n'
            f'</head><body>\n{table}\n</body></html>'
        )

    def add_row(self, button=None):
        # Rebuilt rather than appended to, so the row groups' spans stay right.
        self._snapshot()
        current = self._collect_table()
        self.build_table(current + [[''] * (self._model.columnCount() - 1)])

    def remove_row(self, button=None):
        """Remove the last row — from a row group, its last sub-row."""
        self._snapshot()
        current = self._collect_table()
        if len(current) < 2:
            return

        last = current[-1]
        if isinstance(last, dict) and len(last['rows']) > 1:
            last['rows'] = last['rows'][:-1]
        else:
            current = current[:-1]
        self.build_table(current)

    def copy_selection(self) -> None:
        """Put the selected block on the clipboard, tab-separated for Calc."""
        indexes = [i for i in self.selectedIndexes()
                   if i.column() < self._model.columnCount() - 1]
        if not indexes:
            return

        top = min(i.row() for i in indexes)
        left = min(i.column() for i in indexes)
        block = [[''] * (max(i.column() for i in indexes) - left + 1)
                 for _ in range(max(i.row() for i in indexes) - top + 1)]
        for index in indexes:
            block[index.row() - top][index.column() - left] = index.data() or ''

        QApplication.clipboard().setText(
            '\n'.join('\t'.join(row) for row in block)
        )

    def _writable(self, row: int, col: int):
        """The item at row/col if data may be written into it.

        A row group's label is editable so it can be renamed by typing, but a
        bulk clear or paste must not quietly take the group's name away.
        """
        item = self._model.item(row, col)
        if not item or not item.flags() & Qt.ItemFlag.ItemIsEditable:
            return None
        if col == 0 and self._meta(row).startswith('group:'):
            return None
        return item

    def _meta(self, row: int) -> str:
        item = self._model.item(row, self._model.columnCount() - 1)
        return item.text() if item else ''

    def clear_selection_contents(self) -> None:
        self._snapshot()
        for index in self.selectedIndexes():
            item = self._writable(index.row(), index.column())
            if item:
                item.setText('')

    def keyPressEvent(self, event):
        """Only modified keys are commands, so plain typing edits the cell.

        Bare letters are left to the cell editor: in a grid of data, a word
        typed into a cell must not fire Add row or Edit columns.
        """
        key = event.key()
        ctrl = event.modifiers() & Qt.KeyboardModifier.ControlModifier

        if ctrl:
            match key:
                case Qt.Key.Key_S:
                    self.save_table(None)
                    return
                case Qt.Key.Key_V:
                    self.paste_csv(None)
                    return
                case Qt.Key.Key_C:
                    self.copy_selection()
                    return
                case Qt.Key.Key_Z:
                    self.undo()
                    return
                case Qt.Key.Key_P:
                    self.preview_table(None)
                    return

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.clear_selection_contents()
            return

        super().keyPressEvent(event)
