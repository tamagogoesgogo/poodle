from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QSpinBox, QPushButton, QMessageBox,
    QFileDialog, QWidget, QScrollArea, QListView, QSplitter
)
from PySide6.QtCore import Qt, QUrl
from poodle import exam
from poodle import config
import gui.windows
import gui.grids
import gui.theming
import json
import os


def _network_places() -> list:
    """
    Network drives connected in the file manager, such as BoxUP over WebDAV.
    GNOME mounts them under /run/user/<uid>/gvfs, which Qt's own file dialog
    never shows by itself.
    """
    root = f'/run/user/{os.getuid()}/gvfs'
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [QUrl.fromLocalFile(os.path.join(root, name)) for name in names]


def _tidy_sidebar(dialog: QFileDialog) -> None:
    """Widen the sidebar and name network drives by their server."""
    sidebar = dialog.findChild(QListView, 'sidebar')
    splitter = dialog.findChild(QSplitter, 'splitter')
    if sidebar is None or splitter is None:
        return
    splitter.setSizes([gui.theming.scaled(190), gui.theming.scaled(600)])

    model = sidebar.model()

    def rename(*_):
        # The sidebar's rows are its URLs, in order
        for row, url in enumerate(dialog.sidebarUrls()):
            # e.g. dav:host=boxup.uni-potsdam.de,ssl=true,prefix=... → the host
            name = os.path.basename(url.toLocalFile())
            if '/gvfs/' not in url.toLocalFile() or 'host=' not in name:
                continue
            host = name.split('host=', 1)[1].split(',', 1)[0]
            index = model.index(row, 0)
            if index.data() != host:
                model.setData(index, host, Qt.ItemDataRole.DisplayRole)

    # Qt puts the folder's own name back whenever it refreshes the entry
    model.dataChanged.connect(rename)
    rename()


def choose_path(parent, title: str, folder: bool = False,
                name_filter: str = '') -> str:
    """
    Ask for a file, or a folder if folder is True, with connected network
    drives in the dialog's sidebar. Returns '' if the dialog is cancelled.
    """
    dialog = QFileDialog(parent, title)
    # Qt's own dialog is used anyway (viewing.py turns the platform theme
    # off); saying so keeps the sidebar ours to fill.
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    if folder:
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
    else:
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        if name_filter:
            dialog.setNameFilter(name_filter)
    dialog.setSidebarUrls(dialog.sidebarUrls() + _network_places())
    _tidy_sidebar(dialog)
    if dialog.exec():
        return dialog.selectedFiles()[0]
    return ''


class OKDialog:
    """Multi-purpose informational dialog."""

    def __init__(self, parent, text: str, secondary_text: str = ''):
        self._parent = parent
        self._text = text
        self._secondary = secondary_text

    def _run(self):
        msg = QMessageBox(self._parent)
        msg.setWindowTitle('Info')
        msg.setText(self._text)
        if self._secondary:
            msg.setInformativeText(self._secondary)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()


class YesNoDialog:
    """Multi-purpose confirmation dialog."""

    def __init__(self, parent, text: str, secondary_text: str = ''):
        self._parent = parent
        self._text = text
        self._secondary = secondary_text

    def _run(self) -> bool:
        msg = QMessageBox(self._parent)
        msg.setWindowTitle('Confirm')
        msg.setText(self._text)
        if self._secondary:
            msg.setInformativeText(self._secondary)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes


class QuestionSelectionDialog(QDialog):
    """Called by: ExamCreationWindow.create_exam()"""

    def __init__(self, parent, exam_window):
        super().__init__(parent)
        self.setWindowTitle('Confirm')
        self.parent_window = parent
        self.exam_window = exam_window

        layout = QVBoxLayout(self)
        label = QLabel(
            f'Are you sure you want to create {exam_window.windowTitle()} '
            'with the current question selection?'
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self, questions: list):
        if self.exec() == QDialog.DialogCode.Accepted:
            exam.create_exam(
                self.exam_window.windowTitle(), mode='gui', questions=questions
            )
            self.parent_window.update_tables()
            self.exam_window.close()


class NewQuestionDialog(QDialog):
    """Called by: QuestionTreeview.new_question()"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Create new question:')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Create new question:'))

        self.name_entry = QLineEdit()
        self.name_entry.setPlaceholderText('Question name')
        layout.addWidget(self.name_entry)

        self.moodle_types = QComboBox()
        for mt in config.KEY_TYPES.keys():
            if mt != 'general' and mt != 'optional':
                self.moodle_types.addItem(mt)
        layout.addWidget(self.moodle_types)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            question_content = {
                k: self._default_fill('general', k, v)
                for k, v in config.KEY_TYPES['general'].items()
            }
            name = self.name_entry.text().strip()
            question_content['name'] = name if name else 'New question'
            question_content['moodle_type'] = self.moodle_types.currentText()
            question_content.update({
                k: self._default_fill(question_content['moodle_type'], k, v)
                for k, v in config.KEY_TYPES[question_content['moodle_type']].items()
            })
            return question_content
        return None

    def _default_fill(self, moodle_type: str, field_name: str, output_type: type):
        if output_type == str:
            return ''
        elif output_type == int:
            return 0
        elif output_type == float:
            return 0.0
        elif output_type == list:
            if moodle_type == 'essay' and field_name == 'answer_files':
                return ['', '']
            elif moodle_type == 'calculated' and field_name == 'tolerance':
                return ['', '', '']
            else:
                return ['']
        elif output_type == dict:
            return {}


class NewExamDialog(QDialog):
    """Called by: QuestionTreeview.add_to_exam()"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('New exam')
        self.parent_window = parent

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Please enter exam name:'))

        self.name_entry = QLineEdit()
        layout.addWidget(self.name_entry)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self) -> bool:
        self.parent_window.exam_window = None
        if self.exec() == QDialog.DialogCode.Accepted:
            self.exam_name = self.name_entry.text()
            self.parent_window.exam_window = gui.windows.ExamCreationWindow(
                self.parent_window, self.exam_name
            )
            self.parent_window.exam_window.show()
            return True
        else:
            try:
                delattr(self.parent_window, 'exam_window')
            except AttributeError:
                pass
            return False


class EditColumnsDialog(QDialog):
    """Called by: TableTreeView.edit_columns()"""

    def __init__(self, parent, table):
        super().__init__(parent)
        self.setWindowTitle('Edit columns below:')
        self.parent_window = parent
        self.table = table

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Edit columns below:'))

        n_data_cols = table._model.columnCount() - 1
        column_titles = [
            (table._model.horizontalHeaderItem(i).text()
             if table._model.horizontalHeaderItem(i) else '')
            for i in range(n_data_cols)
        ]
        self.column_grid = gui.grids.TableColumnGrid(parent, column_titles)
        scroll = QScrollArea()
        scroll.setWidget(self.column_grid)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(400, 300)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            self.table.set_columns(self.column_grid.get_entries())


class CheckQuestionDialog:
    """Called by: QuestionControlPanel.check_question_dialog()"""

    def __init__(self, parent, page, check_result):
        self._parent = parent
        self._text = f'{page.content["name"]} has formatting errors:'
        self._secondary = json.dumps(check_result, ensure_ascii=False, indent=4)
        self.check_result = check_result

    def _run(self):
        msg = QMessageBox(self._parent)
        msg.setWindowTitle('Formatting errors')
        msg.setText(self._text)
        msg.setInformativeText(self._secondary)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        return self.check_result


class AddSplitColumnDialog(QDialog):
    """Called by: TableTreeView.add_split_column()"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Add split column:')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Add split column:'))

        row0 = QHBoxLayout()
        row0.addWidget(QLabel('Group label:'))
        self.entry_group = QLineEdit()
        row0.addWidget(self.entry_group)
        layout.addLayout(row0)

        self.sub_layout = QVBoxLayout()
        self.sub_entries = []
        for default in ('Sub1', 'Sub2'):
            self._add_sub_entry(default)
        layout.addLayout(self.sub_layout)

        btn_row = QHBoxLayout()
        add_btn = QPushButton('+ sub-column')
        add_btn.clicked.connect(lambda: self._add_sub_entry(''))
        rem_btn = QPushButton('- sub-column')
        rem_btn.clicked.connect(self._remove_sub_entry)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(rem_btn)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_sub_entry(self, default=''):
        row_widget = QWidget()
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(f'Sub-column {len(self.sub_entries) + 1}:')
        lbl.setMinimumWidth(gui.theming.scaled(130))
        entry = QLineEdit(default)
        row.addWidget(lbl)
        row.addWidget(entry)
        self.sub_entries.append(entry)
        self.sub_layout.addWidget(row_widget)

    def _remove_sub_entry(self):
        if len(self.sub_entries) <= 2:
            return
        self.sub_entries.pop()
        item = self.sub_layout.takeAt(self.sub_layout.count() - 1)
        if item and item.widget():
            item.widget().deleteLater()

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            group = self.entry_group.text() or 'Group'
            subs = [
                e.text() or f'Sub{i + 1}'
                for i, e in enumerate(self.sub_entries)
            ]
            return [group] + subs
        return None


class SpanLabelDialog(QDialog):
    """Called by: TableTreeView.span_columns() and span_rows()"""

    def __init__(self, parent, what: str, default: str = ''):
        super().__init__(parent)
        self.setWindowTitle(f'Span {what}')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Header spanning the selected {what}:'))

        self.entry = QLineEdit(default)
        self.entry.selectAll()
        layout.addWidget(self.entry)

        if what == 'rows':
            note = QLabel('The first column of those rows becomes the header.')
            note.setWordWrap(True)
            layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.entry.text().strip()
        return None


class UnsplitColumnDialog(QDialog):
    """Called by: TableTreeView.unsplit_column() and unsplit_row()."""

    def __init__(self, parent, group_names: list,
                 text: str = 'Select group to unsplit:'):
        super().__init__(parent)
        self.setWindowTitle('Select group')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(text))

        self.combo = QComboBox()
        for name in group_names:
            self.combo.addItem(name)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.combo.currentIndex()
        return None


class RenameGroupLabelsDialog(QDialog):
    """Called by: TableTreeView.rename_group_labels()"""

    def __init__(self, parent, group_names: list):
        super().__init__(parent)
        self.setWindowTitle('Rename group labels:')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Rename group labels:'))

        grid = QGridLayout()
        self.entries = []
        for i, name in enumerate(group_names):
            lbl = QLabel(f'Group {i + 1}:')
            entry = QLineEdit(name)
            self.entries.append(entry)
            grid.addWidget(lbl, i, 0)
            grid.addWidget(entry, i, 1)
        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            return [e.text() for e in self.entries]
        return None


class AddSplitRowDialog(QDialog):
    """Called by: TableTreeView.add_split_row()"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Add split row group:')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Add split row group:'))

        row0 = QHBoxLayout()
        lbl0 = QLabel('Group label:')
        lbl0.setMinimumWidth(gui.theming.scaled(140))
        self.entry_group = QLineEdit()
        row0.addWidget(lbl0)
        row0.addWidget(self.entry_group)
        layout.addLayout(row0)

        row1 = QHBoxLayout()
        lbl1 = QLabel('Number of sub-rows:')
        lbl1.setMinimumWidth(gui.theming.scaled(140))
        self.spin = QSpinBox()
        self.spin.setMinimum(2)
        self.spin.setMaximum(20)
        self.spin.setValue(2)
        row1.addWidget(lbl1)
        row1.addWidget(self.spin)
        layout.addLayout(row1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _run(self):
        if self.exec() == QDialog.DialogCode.Accepted:
            label = self.entry_group.text() or 'Group'
            n_sub = self.spin.value()
            return (label, n_sub)
        return None


class EvaluationFilesDialog:
    """File chooser for evaluation inputs."""

    def __init__(self, parent):
        self._parent = parent

    def _run(self) -> str:
        return choose_path(self._parent, 'Select file')
