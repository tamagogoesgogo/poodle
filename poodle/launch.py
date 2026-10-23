from config import *
from core import *
from exam import *
from question import *
from viewing import *
from gui import *

import pymongo
import os
import time
import types


def list_functions():
    """
    Display a list of all available functions.

    -------------------
    Dependencies: types
    """

    all_functions = [f for f in globals().values() if type(f) == types.FunctionType]

    for f in all_functions:
        if (f.__module__ != 'core' and
            f.__name__ != 'pprint' and
            f.__name__ != 'list_functions'):

            print(f.__name__)


if __name__ == "__main__":
    # Report status
    print(f'Current database: {DB.name}\n')
    for c in DB.list_collection_names():
        print('Documents in collection %s: %d' % (c, DB.get_collection(c).count_documents({})))

    # Set by the Restart button: open the GUI again without being asked
    if os.environ.pop('POODLE_OPEN_GUI', None):
        print()
        qt_overview()
