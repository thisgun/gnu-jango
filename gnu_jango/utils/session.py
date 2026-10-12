def get_session(key, request=None):
    # if request and (session in request) and (key in request.session):
    if request:
        return request.session.get(key)
    
    return None

def set_session(key, value, request=None):
    # if request and (session in request):
    if request:
        request.session[key] = value
        return True
    
    return False