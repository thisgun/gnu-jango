def index_exists_return(list, index, default=None):
    try:
        list[index]
        return list[index]
    except IndexError:
        return default