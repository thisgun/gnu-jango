import os
import re


def get_list_dir(dirname, root_path):
    # directory = root_path + dirname

    directory = os.path.join(root_path, dirname)

    # root, dirs, files = os.walk(directory)
    # return [x[0] for x in os.walk(directory)]

    # https://stackoverflow.com/questions/1720421/how-do-i-concatenate-two-lists-in-python
    # https://stackoverflow.com/questions/141291/how-to-list-only-top-level-directories-in-python
    return [
        (name, name)
        for name in os.listdir(directory)
        if os.path.isdir(os.path.join(directory, name)) and re.match("^(?![_.]).+", name)
    ]
