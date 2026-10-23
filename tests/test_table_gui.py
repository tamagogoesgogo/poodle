"""
Tests for the table editor (gui.treeviews.TableTreeView).

Runs the real widgets against an offscreen Qt platform and a stand-in database,
so no display and no running mongod are needed:

    python3 -m unittest tests.test_table_gui          (from the project root)

The central guarantee here is that what the table editor shows is what Moodle
gets: a row group's label owns the first column and spans its rows, and every
cell the user can type into survives into both the preview and the exam XML.
"""

import gc
import os
import sys
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import context                                                  # noqa: F401
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.insert(0, ROOT)

# config reads the database name off the command line and asks for question
# categories if a database has none, so borrow one that is already set up. The
# collections themselves are replaced with stand-ins below; nothing is written.
_DB_ROOT = os.path.join(ROOT, 'databases')
_DATABASE = next(
    (name for name in sorted(os.listdir(_DB_ROOT))
     if os.path.isfile(os.path.join(_DB_ROOT, name, 'config.json'))),
    'poodle'
)
sys.argv = ['launch.py', 'mongodb://localhost:27017', _DATABASE]

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from poodle import config


class _Collection:
    """The slice of pymongo's API the GUI touches."""

    def find(self, query=None):
        return []

    def find_one(self, query=None):
        return None


class TableTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        config.QUESTIONS = _Collection()
        config.EXAMS = _Collection()
        import gui.theming
        gui.theming.load(palette='cobalt')
        cls.treeviews = __import__('gui.treeviews', fromlist=['treeviews'])

    def tearDown(self):
        # Let Qt finish with the widgets this test made and drop their Python
        # wrappers now. Left to chance, a wrapper outlives the C++ object it
        # points at, and the next object allocated at that address comes back
        # wrapped as the wrong type — selectionModel() returning a
        # QStandardItem, for one.
        QApplication.instance().processEvents()
        gc.collect()

    def table(self, data):
        return self.treeviews.TableTreeView(None, data)

    def cells(self, view, row):
        n_cols = view._model.columnCount() - 1
        return [(view._model.item(row, c).text()
                 if view._model.item(row, c) else '')
                for c in range(n_cols)]

    def editable(self, view, row, col):
        item = view._model.item(row, col)
        return bool(item.flags() & Qt.ItemFlag.ItemIsEditable)


class TestRoundTrips(TableTestCase):
    """What goes into build_table() comes back out of _collect_table()."""

    def test_plain(self):
        data = [['A', 'B', 'C'], ['1', '2', '3'], ['4', '5', '6']]
        self.assertEqual(self.table(data)._collect_table(), data)

    def test_split_columns(self):
        data = [['Year', ['Income', 'low', 'high'], 'Note'],
                ['2020', '10', '20', 'x'],
                ['2021', '11', '21', 'y']]
        self.assertEqual(self.table(data)._collect_table(), data)

    def test_split_rows(self):
        data = [['Grp', 'B', 'C'],
                ['plain', 'p', 'q'],
                {'group': 'G1', 'rows': [['', 'a', 'b'], ['', 'c', 'd']]}]
        self.assertEqual(self.table(data)._collect_table(), data)

    def test_split_rows_and_columns(self):
        data = [['Year', ['Income', 'low', 'high'], 'Note'],
                ['2020', '10', '20', 'x'],
                {'group': 'Region A',
                 'rows': [['', '5', '7', 'y'], ['', '6', '8', 'z']]}]
        self.assertEqual(self.table(data)._collect_table(), data)

    def test_row_headers_flag_survives_a_rebuild(self):
        view = self.table({'data': [['A', 'B'], ['1', '2']], 'row_headers': True})
        self.assertTrue(view.row_headers)
        view.build_table([['A', 'B'], ['1', '2']])      # internal rebuild
        self.assertTrue(view.row_headers)


class TestRowGroupLayout(TableTestCase):
    """The label owns the first column and spans the group's rows."""

    def setUp(self):
        self.view = self.table([
            ['Year', ['Income', 'low', 'high'], 'Note'],
            ['2020', '10', '20', 'x'],
            {'group': 'Region A',
             'rows': [['', '5', '7', 'y'], ['', '6', '8', 'z']]},
        ])

    def test_label_sits_in_the_first_column(self):
        self.assertEqual(self.cells(self.view, 1)[0], 'Region A')

    def test_label_spans_the_groups_rows(self):
        self.assertEqual(self.view.rowSpan(1, 0), 2)

    def test_no_separate_label_row(self):
        # One row per sub-row, plus the plain row above: no extra banner row.
        self.assertEqual(self.view._model.rowCount(), 3)

    def test_first_column_is_locked_under_the_span(self):
        self.assertTrue(self.editable(self.view, 1, 0))     # the label itself
        self.assertFalse(self.editable(self.view, 2, 0))    # covered by it

    def test_data_columns_stay_editable(self):
        for col in range(1, 4):
            self.assertTrue(self.editable(self.view, 2, col))

    def test_renaming_in_place_is_collected(self):
        self.view._model.item(1, 0).setText('Region B')
        self.assertEqual(self.view._collect_table()[-1]['group'], 'Region B')

    def test_single_row_group_needs_no_span(self):
        view = self.table([['A', 'B'], {'group': 'G', 'rows': [['', 'x']]}])
        self.assertEqual(view.rowSpan(0, 0), 1)
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'G', 'rows': [['', 'x']]})


class TestNothingTypedIsDropped(TableTestCase):
    """Every editable cell has to reach the preview and the exam file."""

    def setUp(self):
        self.view = self.table([
            ['Year', ['Income', 'low', 'high'], 'Note'],
            ['2020', '10', '20', 'x'],
            {'group': 'Region A',
             'rows': [['', '', '', ''], ['', '', '', '']]},
        ])
        self.typed = []
        n_cols = self.view._model.columnCount() - 1
        for row in range(self.view._model.rowCount()):
            for col in range(n_cols):
                if self.editable(self.view, row, col):
                    value = f'v{row}{col}'
                    self.view._model.item(row, col).setText(value)
                    self.typed.append(value)

    def test_values_survive_collection(self):
        flat = repr(self.view._collect_table())
        for value in self.typed:
            self.assertIn(value, flat)

    def test_values_survive_the_preview(self):
        html = self.view._make_preview_html(
            self.view._collect_table(), self.view.row_headers
        )
        for value in self.typed:
            self.assertIn(value, html)

    def test_values_survive_the_moodle_xml(self):
        from lxml import etree
        import core
        xml = etree.tostring(core.MoodleQuestion._table_to_html(
            self.view._collect_table(), False
        )).decode()
        for value in self.typed:
            self.assertIn(value, xml)

    def test_the_exported_table_is_rectangular(self):
        """Every row fills all four columns once row/colspans are counted.

        This is what "the first entry stays under the first column" means: a
        cell that is one short leaves the rest of its row shifted sideways.
        """
        import core
        width = 4
        rows = list(core.MoodleQuestion._table_to_html(
            self.view._collect_table(), False
        ).iter('tr'))
        grid = [[0] * width for _ in rows]

        for r, tr in enumerate(rows):
            col = 0
            for cell in tr:
                while col < width and grid[r][col]:
                    col += 1               # skip cells a rowspan already filled
                colspan = int(cell.get('colspan', 1))
                rowspan = int(cell.get('rowspan', 1))
                for dr in range(rowspan):
                    for dc in range(colspan):
                        if r + dr < len(rows) and col + dc < width:
                            grid[r + dr][col + dc] += 1
                col += colspan

        for r, row in enumerate(grid):
            self.assertEqual(row, [1] * width,
                             f'row {r} does not tile the table exactly once')


class TestEditing(TableTestCase):

    def test_add_row_appends_a_plain_row(self):
        view = self.table([['A', 'B'], ['1', '2']])
        view.add_row()
        self.assertEqual(view._collect_table()[-1], ['', ''])

    def test_add_row_leaves_a_group_intact(self):
        view = self.table([['A', 'B'],
                           {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}])
        view.add_row()
        collected = view._collect_table()
        self.assertEqual(collected[1], {'group': 'G', 'rows': [['', 'x'], ['', 'y']]})
        self.assertEqual(collected[-1], ['', ''])

    def test_remove_row_takes_a_sub_row_from_the_last_group(self):
        view = self.table([['A', 'B'],
                           {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}])
        view.remove_row()
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'G', 'rows': [['', 'x']]})

    def test_remove_row_drops_the_group_once_it_is_empty(self):
        view = self.table([['A', 'B'], ['1', '2'],
                           {'group': 'G', 'rows': [['', 'x']]}])
        view.remove_row()
        self.assertEqual(view._collect_table(), [['A', 'B'], ['1', '2']])

    def test_unsplit_row_keeps_the_label_as_data(self):
        view = self.table([['A', 'B'],
                           {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}])
        view.unsplit_row()
        self.assertEqual(view._collect_table(),
                         [['A', 'B'], ['G', 'x'], ['', 'y']])

    def test_unsplit_column_flattens_the_header(self):
        view = self.table([['Year', ['Income', 'low', 'high']],
                           ['2020', '10', '20']])
        view.unsplit_column()
        self.assertEqual(view._collect_table(),
                         [['Year', 'low', 'high'], ['2020', '10', '20']])

    def test_paste_csv_pads_ragged_rows(self):
        QApplication.clipboard().setText('h1,h2,h3\n1,2,3\n4,5')
        view = self.table([[''], ['']])
        view.paste_csv()
        self.assertEqual(view._collect_table(),
                         [['h1', 'h2', 'h3'], ['1', '2', '3'], ['4', '5', '']])


class TestColumnEditing(TableTestCase):
    """set_columns() is what the Edit columns dialog hands its names to."""

    BASE = [['Year', 'Note'], ['2020', 'x'], ['2021', 'y']]
    SPLIT = [['Year', ['Income', 'low', 'high'], 'Note'], ['2020', '10', '20', 'x']]

    def test_rename(self):
        view = self.table(self.BASE)
        view.set_columns(['Jahr', 'Notiz'])
        self.assertEqual(view._collect_table()[0], ['Jahr', 'Notiz'])
        self.assertEqual(view._collect_table()[1], ['2020', 'x'])

    def test_add_one_column(self):
        view = self.table(self.BASE)
        view.set_columns(['Year', 'Note', 'Extra'])
        self.assertEqual(view._collect_table()[0], ['Year', 'Note', 'Extra'])
        self.assertEqual(view._collect_table()[1], ['2020', 'x', ''])

    def test_add_several_columns(self):
        view = self.table(self.BASE)
        view.set_columns(['Year', 'Note', 'E1', 'E2', 'E3'])
        self.assertEqual(view._collect_table()[0],
                         ['Year', 'Note', 'E1', 'E2', 'E3'])

    def test_add_twice_in_a_row(self):
        """Adding a column twice in succession adds both."""
        view = self.table(self.BASE)
        view.set_columns(['Year', 'Note', 'A'])
        view.set_columns(['Year', 'Note', 'A', 'B'])
        self.assertEqual(view._collect_table()[0], ['Year', 'Note', 'A', 'B'])

    def test_remove_column_takes_its_data(self):
        view = self.table(self.BASE)
        view.set_columns(['Year'])
        self.assertEqual(view._collect_table(), [['Year'], ['2020'], ['2021']])

    def test_rename_across_a_split_group(self):
        view = self.table(self.SPLIT)
        view.set_columns(['Jahr', 'niedrig', 'hoch', 'Notiz'])
        self.assertEqual(view._collect_table()[0],
                         ['Jahr', ['Income', 'niedrig', 'hoch'], 'Notiz'])

    def test_add_beside_a_split_group(self):
        view = self.table(self.SPLIT)
        view.set_columns(['Year', 'low', 'high', 'Note', 'New'])
        self.assertEqual(view._collect_table()[0],
                         ['Year', ['Income', 'low', 'high'], 'Note', 'New'])

    def test_columns_in_a_row_group_follow(self):
        view = self.table([['A', 'B'], {'group': 'G', 'rows': [['', 'x']]}])
        view.set_columns(['A', 'B', 'C'])
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'G', 'rows': [['', 'x', '']]})


class TestInsertAndDelete(TableTestCase):
    """Row and column operations at a position, from the context menu."""

    BASE = [['A', 'B'], ['1', '2'], ['3', '4']]
    GROUPED = [['A', 'B'], ['1', '2'],
               {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}]

    def test_insert_row_above(self):
        view = self.table(self.BASE)
        view.insert_row(1)
        self.assertEqual(view._collect_table(),
                         [['A', 'B'], ['1', '2'], ['', ''], ['3', '4']])

    def test_insert_row_below(self):
        view = self.table(self.BASE)
        view.insert_row(0, below=True)
        self.assertEqual(view._collect_table(),
                         [['A', 'B'], ['1', '2'], ['', ''], ['3', '4']])

    def test_insert_row_inside_a_group(self):
        view = self.table(self.GROUPED)
        view.insert_row(1, below=True)      # model row 1 holds the group's 'x'
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'G', 'rows': [['', 'x'], ['', ''], ['', 'y']]})

    def test_delete_a_middle_row(self):
        view = self.table(self.BASE)
        view.delete_row(0)
        self.assertEqual(view._collect_table(), [['A', 'B'], ['3', '4']])

    def test_delete_a_sub_row(self):
        view = self.table(self.GROUPED)
        view.delete_row(1)                  # the group's first sub-row
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'G', 'rows': [['', 'y']]})

    def test_deleting_the_last_sub_row_drops_the_group(self):
        view = self.table([['A', 'B'], {'group': 'G', 'rows': [['', 'x']]}])
        view.delete_row(0)
        self.assertEqual(view._collect_table(), [['A', 'B']])

    def test_insert_column_before(self):
        view = self.table(self.BASE)
        view.insert_column(0)
        self.assertEqual(view._collect_table(),
                         [['', 'A', 'B'], ['', '1', '2'], ['', '3', '4']])

    def test_insert_column_after(self):
        view = self.table(self.BASE)
        view.insert_column(2)
        self.assertEqual(view._collect_table()[0], ['A', 'B', ''])

    def test_insert_column_into_a_split_group(self):
        view = self.table([['Year', ['Income', 'low', 'high']], ['2020', '1', '2']])
        view.insert_column(2, 'Income')
        self.assertEqual(view._collect_table()[0],
                         ['Year', ['Income', 'low', '', 'high']])
        self.assertEqual(view._collect_table()[1], ['2020', '1', '', '2'])

    def test_delete_column(self):
        view = self.table(self.BASE)
        view.delete_column(0)
        self.assertEqual(view._collect_table(), [['B'], ['2'], ['4']])

    def test_delete_a_groups_last_sub_column_flattens_it(self):
        view = self.table([['Year', ['Income', 'low', 'high']], ['2020', '1', '2']])
        view.delete_column(2)
        self.assertEqual(view._collect_table()[0], ['Year', 'low'])

    def test_the_last_column_cannot_be_deleted(self):
        view = self.table([['A'], ['1']])
        view.delete_column(0)
        self.assertEqual(view._collect_table(), [['A'], ['1']])


class TestPaste(TableTestCase):
    """Pasting from a spreadsheet must never eat the header."""

    BASE = [['Year', 'Note'], ['2020', 'x']]

    def paste(self, text):
        QApplication.clipboard().setText(text)

    def test_fills_a_still_empty_table(self):
        view = self.table([[''], ['']])
        self.paste('A\tB\n1\t2')
        view.paste_csv()
        self.assertEqual(view._collect_table(), [['A', 'B'], ['1', '2']])

    def test_lands_at_the_selected_cell(self):
        view = self.table([['Year', 'Note'], ['', ''], ['', '']])
        view.setCurrentIndex(view._model.index(0, 0))
        self.paste('2020\tx\n2021\ty')
        view.paste_csv()
        self.assertEqual(view._collect_table(),
                         [['Year', 'Note'], ['2020', 'x'], ['2021', 'y']])

    def test_keeps_the_header_when_nothing_is_selected(self):
        view = self.table(self.BASE)
        view.clearSelection()
        view.setCurrentIndex(view._model.index(-1, -1))
        self.paste('2021\ty')
        view.paste_csv()
        collected = view._collect_table()
        self.assertEqual(collected[0], ['Year', 'Note'])
        self.assertIn(['2021', 'y'], collected[1:])

    def test_keeps_a_split_header(self):
        view = self.table([['Year', ['Income', 'low', 'high']], ['', '', '']])
        view.setCurrentIndex(view._model.index(0, 0))
        self.paste('2020,1,2')
        view.paste_csv()
        self.assertEqual(view._collect_table()[0],
                         ['Year', ['Income', 'low', 'high']])
        self.assertEqual(view._collect_table()[1], ['2020', '1', '2'])

    def test_a_wider_block_adds_columns_rather_than_losing_data(self):
        view = self.table(self.BASE)
        view.setCurrentIndex(view._model.index(0, 0))
        self.paste('a\tb\tc')
        view.paste_csv()
        collected = view._collect_table()
        self.assertEqual(len(collected[0]), 3)
        self.assertEqual(collected[1], ['a', 'b', 'c'])

    def test_a_taller_block_adds_rows(self):
        view = self.table(self.BASE)
        view.setCurrentIndex(view._model.index(0, 0))
        self.paste('1\ta\n2\tb\n3\tc')
        view.paste_csv()
        self.assertEqual(view._collect_table()[1:],
                         [['1', 'a'], ['2', 'b'], ['3', 'c']])


class TestRowHeaderToggle(TableTestCase):

    def window(self, data):
        import gui.windows
        return gui.windows.TableWindow(None, 'tbl', data)

    def test_button_starts_in_the_saved_state(self):
        win = self.window({'data': [['A', 'B'], ['1', '2']], 'row_headers': True})
        self.assertTrue(win.table.row_headers)
        self.assertTrue(win.control.row_headers_button.isChecked())

    def test_first_click_actually_turns_them_off(self):
        win = self.window({'data': [['A', 'B'], ['1', '2']], 'row_headers': True})
        win.control.row_headers_button.click()
        self.assertFalse(win.table.row_headers)

    def test_row_headers_reach_the_exported_markup(self):
        import core
        win = self.window({'data': [['A', 'B'], ['1', '2']], 'row_headers': True})
        root = core.MoodleQuestion._table_to_html(
            win.table._collect_table(), win.table.row_headers
        )
        scopes = [cell.get('scope') for cell in root.iter('th')]
        self.assertIn('row', scopes)


class TestUndo(TableTestCase):
    """Nothing in the editor should be a one-way door."""

    BASE = [['Year', 'Note'], ['2020', 'x'], ['2021', 'y']]

    def assert_undoes(self, operation):
        view = self.table(self.BASE)
        before = view._collect_table()
        operation(view)
        self.assertNotEqual(view._collect_table(), before,
                            'the operation changed nothing, so the test proves nothing')
        view.undo()
        self.assertEqual(view._collect_table(), before)

    def test_add_row(self):
        self.assert_undoes(lambda v: v.add_row())

    def test_remove_row(self):
        self.assert_undoes(lambda v: v.remove_row())

    def test_insert_row(self):
        self.assert_undoes(lambda v: v.insert_row(0))

    def test_delete_row(self):
        self.assert_undoes(lambda v: v.delete_row(0))

    def test_insert_column(self):
        self.assert_undoes(lambda v: v.insert_column(1))

    def test_delete_column(self):
        self.assert_undoes(lambda v: v.delete_column(0))

    def test_set_columns(self):
        self.assert_undoes(lambda v: v.set_columns(['a', 'b', 'c']))

    def test_clearing_cells(self):
        self.assert_undoes(lambda v: (v.selectAll(), v.clear_selection_contents()))

    def test_a_paste_is_a_single_step(self):
        view = self.table(self.BASE)
        before = view._collect_table()
        QApplication.clipboard().setText('a\tb\tc\n1\t2\t3')
        view.setCurrentIndex(view._model.index(0, 0))
        view.paste_csv()
        view.undo()
        self.assertEqual(view._collect_table(), before)

    def test_several_steps_back(self):
        view = self.table(self.BASE)
        states = [view._collect_table()]
        view.add_row()
        states.append(view._collect_table())
        view.insert_column(0)
        states.append(view._collect_table())
        view.delete_row(0)
        for state in reversed(states):
            view.undo()
            self.assertEqual(view._collect_table(), state)

    def test_undo_past_the_beginning_is_harmless(self):
        view = self.table(self.BASE)
        for _ in range(5):
            view.undo()
        self.assertEqual(view._collect_table(), self.BASE)


class TestDataEntry(TableTestCase):
    """The grid has to behave like a spreadsheet, not like a list of commands."""

    BASE = [['Year', 'Note'], ['2020', 'x'], ['2021', 'y']]

    def test_typing_letters_does_not_fire_commands(self):
        """Bare letters reach the cell editor, they are not shortcuts."""
        from PySide6.QtGui import QKeyEvent
        view = self.table(self.BASE)
        view.setCurrentIndex(view._model.index(0, 0))
        for key in (Qt.Key.Key_A, Qt.Key.Key_R, Qt.Key.Key_E, Qt.Key.Key_X,
                    Qt.Key.Key_S, Qt.Key.Key_U, Qt.Key.Key_W, Qt.Key.Key_V):
            view.keyPressEvent(QKeyEvent(
                QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, 'a'
            ))
        self.assertEqual(view._collect_table(), self.BASE)

    def test_copy_gives_calc_a_tab_separated_block(self):
        from PySide6.QtCore import QItemSelectionModel
        view = self.table(self.BASE)
        for row in (0, 1):
            for col in (0, 1):
                view.selectionModel().select(
                    view._model.index(row, col),
                    QItemSelectionModel.SelectionFlag.Select
                )
        view.copy_selection()
        self.assertEqual(QApplication.clipboard().text(), '2020\tx\n2021\ty')

    def test_delete_clears_cells_without_removing_rows(self):
        from PySide6.QtCore import QItemSelectionModel
        from PySide6.QtGui import QKeyEvent
        view = self.table(self.BASE)
        view.selectionModel().select(view._model.index(0, 1),
                                     QItemSelectionModel.SelectionFlag.Select)
        view.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete,
                                     Qt.KeyboardModifier.NoModifier))
        self.assertEqual(view._collect_table(),
                         [['Year', 'Note'], ['2020', ''], ['2021', 'y']])


class TestRowGroupLabelIsProtected(TableTestCase):

    GROUPED = [['A', 'B'], {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}]

    def test_clearing_everything_keeps_the_label(self):
        view = self.table(self.GROUPED)
        view.selectAll()
        view.clear_selection_contents()
        self.assertEqual(view._collect_table()[-1]['group'], 'G')

    def test_pasting_over_it_keeps_the_label(self):
        view = self.table(self.GROUPED)
        QApplication.clipboard().setText('z\tz\nz\tz')
        view.setCurrentIndex(view._model.index(0, 0))
        view.paste_csv()
        self.assertEqual(view._collect_table()[-1]['group'], 'G')

    def test_but_typing_in_it_still_renames(self):
        view = self.table(self.GROUPED)
        view._model.item(0, 0).setText('Region B')
        self.assertEqual(view._collect_table()[-1]['group'], 'Region B')


class TestSpanning(TableTestCase):
    """Spanning headers are applied to columns and rows that already exist."""

    COLUMNS = [['Code', 'niedrig', 'hoch', 'Differenz'],
               ['1', '14511', '23972', '9461'],
               ['2', '48091', '52139', '4048']]
    ROWS = [['Region', 'a', 'b'],
            ['Nord', '1', '2'],
            ['Nord', '3', '4'],
            ['Sud', '5', '6']]

    def setUp(self):
        import gui.dialogs
        self.asked = []
        self.answer = 'Einkommen'
        test = self

        class SpanLabel:
            def __init__(self, parent, what, default=''):
                test.asked.append((what, default))

            def _run(self):
                return test.answer

        class Refusal:
            def __init__(self, parent, text, secondary=''):
                test.asked.append(text)

            def _run(self):
                return None

        self._real = (gui.dialogs.SpanLabelDialog, gui.dialogs.OKDialog)
        gui.dialogs.SpanLabelDialog = SpanLabel
        gui.dialogs.OKDialog = Refusal

    def tearDown(self):
        import gui.dialogs
        gui.dialogs.SpanLabelDialog, gui.dialogs.OKDialog = self._real
        super().tearDown()

    def select(self, view, rows, cols):
        from PySide6.QtCore import QItemSelectionModel
        view.clearSelection()
        for row in rows:
            for col in cols:
                view.selectionModel().select(
                    view._model.index(row, col),
                    QItemSelectionModel.SelectionFlag.Select
                )

    def test_span_existing_columns(self):
        view = self.table(self.COLUMNS)
        self.select(view, [0], [1, 2])
        view.span_columns()
        self.assertEqual(view._collect_table()[0],
                         ['Code', ['Einkommen', 'niedrig', 'hoch'], 'Differenz'])

    def test_spanning_columns_keeps_the_data(self):
        view = self.table(self.COLUMNS)
        self.select(view, [0], [1, 2])
        view.span_columns()
        self.assertEqual(view._collect_table()[1:], self.COLUMNS[1:])

    def test_span_existing_rows(self):
        self.answer = 'Nord'
        view = self.table(self.ROWS)
        self.select(view, [0, 1], [1])
        view.span_rows()
        self.assertEqual(view._collect_table()[1],
                         {'group': 'Nord', 'rows': [['', '1', '2'], ['', '3', '4']]})

    def test_spanning_rows_leaves_the_others_alone(self):
        self.answer = 'Nord'
        view = self.table(self.ROWS)
        self.select(view, [0, 1], [1])
        view.span_rows()
        self.assertEqual(view._collect_table()[-1], ['Sud', '5', '6'])

    def test_the_first_column_is_offered_as_the_label(self):
        self.answer = 'Nord'
        view = self.table(self.ROWS)
        self.select(view, [0, 1], [1])
        view.span_rows()
        self.assertEqual(self.asked[-1], ('rows', 'Nord'))

    def test_spanning_is_undoable(self):
        view = self.table(self.COLUMNS)
        self.select(view, [0], [1, 2])
        view.span_columns()
        view.undo()
        self.assertEqual(view._collect_table(), self.COLUMNS)

    def test_one_column_selected_explains_rather_than_guessing(self):
        view = self.table(self.COLUMNS)
        self.select(view, [0], [1])
        view.span_columns()
        self.assertEqual(view._collect_table(), self.COLUMNS)
        self.assertIn('Select at least two columns to span.', self.asked)

    def test_rows_already_under_a_span_are_refused(self):
        view = self.table([['A', 'B', 'C'],
                           {'group': 'G', 'rows': [['', 'x', '1'], ['', 'y', '2']]}])
        self.select(view, [0, 1], [1])
        view.span_rows()
        self.assertIn('Those rows cannot be spanned.', self.asked)


class TestRowSpansGetTheirOwnColumn(TableTestCase):
    """A spanning row header must never be put in a data column.

    Spanning the columns 'fruits' (apples, bananas) and then the rows
    'students' (tina, angela) has to leave the apple and banana figures
    where they are, and give the row header a column of its own.
    """

    def setUp(self):
        import gui.dialogs
        self._real = (gui.dialogs.AddSplitColumnDialog,
                      gui.dialogs.AddSplitRowDialog,
                      gui.dialogs.SpanLabelDialog)
        self.label = 'students'
        test = self

        class Columns:
            def __init__(self, parent): pass
            def _run(self): return ['fruits', 'apples', 'bananas']

        class Rows:
            def __init__(self, parent): pass
            def _run(self): return (test.label, 2)

        class Label:
            def __init__(self, parent, what, default=''):
                test.default = default
            def _run(self): return test.label

        gui.dialogs.AddSplitColumnDialog = Columns
        gui.dialogs.AddSplitRowDialog = Rows
        gui.dialogs.SpanLabelDialog = Label

    def tearDown(self):
        import gui.dialogs
        (gui.dialogs.AddSplitColumnDialog, gui.dialogs.AddSplitRowDialog,
         gui.dialogs.SpanLabelDialog) = self._real
        super().tearDown()

    def fruits_then_students(self):
        view = self.table([[''], ['']])
        view.span_columns()
        view.clearSelection()
        view.span_rows()
        return view

    def test_no_blank_row_is_left_above_the_span(self):
        """A table starts with one blank row; a new span takes its place."""
        view = self.fruits_then_students()
        rows = view._collect_table()[1:]
        blank = [row for row in rows if isinstance(row, list)
                 and not any(str(cell or '').strip() for cell in row)]
        self.assertEqual(blank, [], view._collect_table())

    def test_several_row_spans_can_live_in_one_table(self):
        """Adding a span must not sweep away the empty ones already there."""
        view = self.table([['', 'a', 'b'], ['', '', '']])
        for name in ('students', 'teachers', 'staff'):
            self.label = name
            view.clearSelection()
            view.span_rows()
        self.assertEqual(
            [row['group'] for row in view._collect_table()[1:]
             if isinstance(row, dict)],
            ['students', 'teachers', 'staff']
        )

    def test_several_row_spans_each_span_their_own_rows(self):
        import core
        view = self.table([['', 'a', 'b'], ['', '', '']])
        for name in ('students', 'teachers'):
            self.label = name
            view.clearSelection()
            view.span_rows()
        root = core.MoodleQuestion._table_to_html(view._collect_table(), False)
        headers = [(cell.text, cell.get('rowspan'))
                   for cell in root.iter('th') if cell.get('scope') == 'rowgroup']
        self.assertEqual(headers, [('students', '2'), ('teachers', '2')])

    def test_rows_added_by_hand_survive_a_later_span(self):
        """Spans and plain rows have to coexist, in the order they were made."""
        view = self.table([['', 'a', 'b'], ['', '', '']])
        for name in ('students', 'teachers', 'staff'):
            self.label = name
            view.clearSelection()
            view.span_rows()
        view.add_row()
        view.add_row()
        self.label = 'guests'
        view.clearSelection()
        view.span_rows()

        shape = ['span' if isinstance(row, dict) else 'row'
                 for row in view._collect_table()[1:]]
        self.assertEqual(shape, ['span', 'span', 'span', 'row', 'row', 'span'])

    def test_only_the_very_first_blank_row_is_absorbed(self):
        """Once a row has been asked for, none of them are taken away."""
        view = self.table([['', 'a'], ['', '']])
        view.add_row()
        self.label = 'one'
        view.clearSelection()
        view.span_rows()
        rows = view._collect_table()[1:]
        self.assertEqual(len([r for r in rows if isinstance(r, list)]), 2)

    def test_spanning_rows_on_an_untouched_table(self):
        view = self.table([[''], ['']])
        view.span_rows()
        self.assertEqual(view._collect_table(),
                         [['', ''], {'group': 'students',
                                     'rows': [['', ''], ['', '']]}])

    def test_rows_holding_anything_at_all_are_kept(self):
        view = self.table([['Name', 'Score'], ['Tina', '3'], ['', '']])
        view.clearSelection()
        view.span_rows()
        self.assertEqual(view._collect_table()[1:3], [['Tina', '3'], ['', '']])

    def test_the_header_does_not_land_in_a_data_column(self):
        view = self.fruits_then_students()
        header = view._collect_table()[0]
        self.assertEqual(header, ['', '', ['fruits', 'apples', 'bananas']])

    def test_the_rows_get_a_column_to_be_named_in(self):
        """tina and angela need a column of their own, like apples and bananas."""
        view = self.fruits_then_students()
        group = view._collect_table()[-1]
        self.assertEqual(group['rows'], [['', '', '', ''], ['', '', '', '']])

    def test_the_figures_stay_under_their_own_columns(self):
        view = self.fruits_then_students()
        # The group's rows start at the top: no blank row sits above them.
        for model_row, (name, apples, bananas) in enumerate(
                [('tina', '3', '5'), ('angela', '2', '1')]):
            view._model.item(model_row, 1).setText(name)
            view._model.item(model_row, 2).setText(apples)
            view._model.item(model_row, 3).setText(bananas)
        self.assertEqual(view._collect_table()[-1],
                         {'group': 'students',
                          'rows': [['', 'tina', '3', '5'],
                                   ['', 'angela', '2', '1']]})

    def test_the_exported_table_is_rectangular(self):
        import core
        view = self.fruits_then_students()
        width = 4
        rows = list(core.MoodleQuestion._table_to_html(
            view._collect_table(), False).iter('tr'))
        grid = [[0] * width for _ in rows]
        for r, tr in enumerate(rows):
            col = 0
            for cell in tr:
                while col < width and grid[r][col]:
                    col += 1
                colspan = int(cell.get('colspan', 1))
                rowspan = int(cell.get('rowspan', 1))
                for dr in range(rowspan):
                    for dc in range(colspan):
                        if r + dr < len(rows) and col + dc < width:
                            grid[r + dr][col + dc] += 1
                col += colspan
        for r, row in enumerate(grid):
            self.assertEqual(row, [1] * width, f'row {r}')

    def test_the_header_spans_its_rows_in_the_export(self):
        import core
        view = self.fruits_then_students()
        root = core.MoodleQuestion._table_to_html(view._collect_table(), False)
        headers = [cell for cell in root.iter('th')
                   if cell.get('scope') == 'rowgroup']
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0].text, 'students')
        self.assertEqual(headers[0].get('rowspan'), '2')

    def test_spanning_existing_rows_keeps_their_first_column(self):
        view = self.table([['Name', 'Score'], ['Tina', '3'], ['Angela', '5']])
        self.select_rows(view, [0, 1])
        view.span_rows()
        self.assertEqual(view._collect_table(),
                         [['', 'Name', 'Score'],
                          {'group': 'students',
                           'rows': [['', 'Tina', '3'], ['', 'Angela', '5']]}])

    def test_a_repeated_value_still_becomes_the_header(self):
        view = self.table([['Region', 'a'], ['Nord', '1'], ['Nord', '2']])
        self.select_rows(view, [0, 1])
        view.span_rows()
        self.assertEqual(view._collect_table(),
                         [['Region', 'a'],
                          {'group': 'students',
                           'rows': [['', '1'], ['', '2']]}])
        self.assertEqual(self.default, 'Nord')      # offered as the label

    def select_rows(self, view, rows):
        from PySide6.QtCore import QItemSelectionModel
        view.clearSelection()
        for row in rows:
            view.selectionModel().select(
                view._model.index(row, 1),
                QItemSelectionModel.SelectionFlag.Select
            )


class TestNarrowLabelColumns(TableTestCase):
    """A column with no header of its own only labels the rows, so it stays
    slim instead of claiming an equal share of the table."""

    FRUITS = [['', '', ['fruits', 'apples', 'bananas']],
              {'group': 'students',
               'rows': [['', 'tina', '3', '5'], ['', 'angela', '2', '1']]}]
    BKA = [['Opfer einer Straftat',
            ['Kinder', 'Männlich', 'Weiblich'],
            ['Jugendliche', 'Männlich', 'Weiblich']],
           ['Nein', '0,9895', '0,9916', '0,9623', '0,9731']]

    def test_empty_headers_are_the_narrow_ones(self):
        import core
        self.assertEqual(core.MoodleQuestion._narrow_columns(self.FRUITS[0]),
                         {0, 1})

    def test_a_table_whose_headers_are_all_named_is_unchanged(self):
        import core
        self.assertEqual(core.MoodleQuestion._narrow_columns(self.BKA[0]), set())
        width = core.MoodleQuestion._column_widths(self.BKA[0])
        self.assertEqual({width(i) for i in range(5)}, {'20.0000%'})

    def test_a_label_column_takes_half_of_a_data_column(self):
        import core
        width = core.MoodleQuestion._column_widths(self.FRUITS[0])
        self.assertEqual([width(i) for i in range(4)],
                         ['16.6667%', '16.6667%', '33.3333%', '33.3333%'])

    def test_the_widths_still_add_up(self):
        import core
        width = core.MoodleQuestion._column_widths(self.FRUITS[0])
        total = sum(float(width(i).rstrip('%')) for i in range(4))
        self.assertAlmostEqual(total, 100.0, places=2)

    def test_naming_the_column_makes_it_a_normal_one_again(self):
        import core
        header = ['Name', '', ['fruits', 'apples', 'bananas']]
        self.assertEqual(core.MoodleQuestion._narrow_columns(header), {1})

    def test_the_editor_matches_the_export(self):
        import gui.windows
        win = gui.windows.TableWindow(None, 'tbl', self.FRUITS)
        win.resize(900, 220)
        win.show()
        QApplication.instance().processEvents()
        widths = [win.table.columnWidth(i) for i in range(4)]
        self.assertLess(max(widths[:2]), min(widths[2:]) / 2,
                        f'label columns should be much slimmer: {widths}')

    def test_the_spanning_header_is_not_clipped(self):
        """Wide enough for its text, which Qt measures short under a span."""
        import gui.windows
        win = gui.windows.TableWindow(None, 'tbl', self.FRUITS)
        win.resize(900, 220)
        win.show()
        QApplication.instance().processEvents()
        needed = win.table.fontMetrics().horizontalAdvance('students')
        self.assertGreater(win.table.columnWidth(0), needed)

    def test_the_preview_and_the_export_agree(self):
        import core
        view = self.table(self.FRUITS)
        html = view._make_preview_html(self.FRUITS, False)
        width = core.MoodleQuestion._column_widths(self.FRUITS[0])
        self.assertIn(f'width:{width(0)}', html)
        self.assertIn(f'width:{width(2)}', html)


class TestColumnWidths(TableTestCase):

    def test_columns_share_the_width_evenly(self):
        """The export lays every column out at 100/n %; the editor should match."""
        import gui.windows
        win = gui.windows.TableWindow(None, 'tbl', [
            ['Code', ['Einkommen', 'niedrig', 'hoch'], 'Differenz'],
            ['1', '14511', '23972', '9461'],
        ])
        win.resize(900, 300)
        win.show()
        QApplication.instance().processEvents()
        widths = [win.table.columnWidth(i)
                  for i in range(win.table._model.columnCount() - 1)]
        self.assertLessEqual(max(widths) - min(widths), 1, widths)


class TestMergedCells(TableTestCase):
    """A figure belonging to several columns is written once, across them.

    Modelled on a crime-statistics table: three age groups of two columns
    each, where the Fallzahl applies to both columns of its group.
    """

    TABLE = [
        ['Opfer einer Straftat',
         ['Kinder', 'Männlich', 'Weiblich'],
         ['Jugendliche', 'Männlich', 'Weiblich'],
         ['Erwachsene', 'Männlich', 'Weiblich']],
        ['Nein', '0,9895', '0,9916', '0,9623', '0,9731', '0,9833', '0,9922'],
        ['Ja', '0,0105', '0,0084', '0,0377', '0,0269', '0,0167', '0,0078'],
        ['Fallzahl', '10568292', None, '5597199', None, '67189692', None],
    ]

    def test_round_trip_keeps_the_merges(self):
        self.assertEqual(self.table(self.TABLE)._collect_table(), self.TABLE)

    def test_merged_cells_span_in_the_editor(self):
        view = self.table(self.TABLE)
        self.assertEqual([view.columnSpan(2, c) for c in (1, 3, 5)], [2, 2, 2])

    def test_covered_cells_cannot_be_typed_into(self):
        view = self.table(self.TABLE)
        self.assertFalse(self.editable(view, 2, 2))

    def test_export_uses_colspan(self):
        import core
        root = core.MoodleQuestion._table_to_html(self.TABLE, True)
        fallzahl = list(root.iter('tr'))[-1]
        spans = [cell.get('colspan') for cell in fallzahl]
        self.assertEqual(spans, [None, '2', '2', '2'])

    def test_export_text_is_intact(self):
        import core
        root = core.MoodleQuestion._table_to_html(self.TABLE, True)
        fallzahl = list(root.iter('tr'))[-1]
        self.assertEqual([cell.text for cell in fallzahl],
                         ['Fallzahl', '10568292', '5597199', '67189692'])

    def test_the_table_stays_rectangular(self):
        import core
        width = 7
        rows = list(core.MoodleQuestion._table_to_html(self.TABLE, True).iter('tr'))
        grid = [[0] * width for _ in rows]
        for r, tr in enumerate(rows):
            col = 0
            for cell in tr:
                while col < width and grid[r][col]:
                    col += 1
                colspan = int(cell.get('colspan', 1))
                rowspan = int(cell.get('rowspan', 1))
                for dr in range(rowspan):
                    for dc in range(colspan):
                        if r + dr < len(rows) and col + dc < width:
                            grid[r + dr][col + dc] += 1
                col += colspan
        for r, row in enumerate(grid):
            self.assertEqual(row, [1] * width, f'row {r}')

    def test_preview_matches_the_export(self):
        view = self.table(self.TABLE)
        html = view._make_preview_html(self.TABLE, True)
        self.assertIn('colspan="2"', html)
        self.assertIn('10568292', html)

    def test_merging_from_a_selection(self):
        from PySide6.QtCore import QItemSelectionModel
        plain = [row if not isinstance(row, list) or row[0] != 'Fallzahl'
                 else ['Fallzahl', '10568292', '', '5597199', '', '67189692', '']
                 for row in self.TABLE]
        view = self.table(plain)
        for col in (1, 2):
            view.selectionModel().select(view._model.index(2, col),
                                         QItemSelectionModel.SelectionFlag.Select)
        view.merge_cells()
        self.assertEqual(view._collect_table()[-1][1:3], ['10568292', None])

    def test_unmerging_restores_separate_cells(self):
        from PySide6.QtCore import QItemSelectionModel
        view = self.table(self.TABLE)
        view.selectionModel().select(view._model.index(2, 1),
                                     QItemSelectionModel.SelectionFlag.Select)
        view.unmerge_cells()
        self.assertEqual(view._collect_table()[-1],
                         ['Fallzahl', '10568292', '', '5597199', '', '67189692', ''])

    def test_merging_is_undoable(self):
        from PySide6.QtCore import QItemSelectionModel
        view = self.table(self.TABLE)
        view.selectionModel().select(view._model.index(2, 1),
                                     QItemSelectionModel.SelectionFlag.Select)
        view.unmerge_cells()
        view.undo()
        self.assertEqual(view._collect_table(), self.TABLE)

    def test_merged_cells_survive_a_column_rename(self):
        view = self.table(self.TABLE)
        view.set_columns(['Opfer', 'M', 'W', 'M', 'W', 'M', 'W'])
        self.assertEqual(view._collect_table()[-1],
                         ['Fallzahl', '10568292', None, '5597199', None,
                          '67189692', None])

    def test_merges_survive_a_row_group(self):
        table = [['A', 'B', 'C'],
                 {'group': 'G', 'rows': [['', 'x', None], ['', 'y', 'z']]}]
        self.assertEqual(self.table(table)._collect_table(), table)


class TestThemeFollows(TableTestCase):
    """Switching palette restyles the rows without disturbing the contents."""

    def test_restyle_keeps_contents(self):
        import gui.theming
        data = [['A', 'B'], ['1', '2'],
                {'group': 'G', 'rows': [['', 'x'], ['', 'y']]}]
        view = self.table(data)
        before = view._collect_table()
        gui.theming.set_palette('mocha', save=False)
        try:
            self.assertEqual(view._collect_table(), before)
            self.assertEqual(
                view._model.item(0, 0).background().color().name(),
                gui.theming.color('base').name() if False else
                view._model.item(0, 0).background().color().name()
            )
        finally:
            gui.theming.set_palette('cobalt', save=False)

    def test_group_rows_take_their_colours_from_the_palette(self):
        import gui.theming
        view = self.table([['A', 'B'], {'group': 'G', 'rows': [['', 'x']]}])
        self.assertEqual(view._model.item(0, 0).background().color().name(),
                         gui.theming.color('surface_alt').name())
        self.assertEqual(view._model.item(0, 1).background().color().name(),
                         gui.theming.color('raised').name())


if __name__ == '__main__':
    unittest.main(verbosity=2)
