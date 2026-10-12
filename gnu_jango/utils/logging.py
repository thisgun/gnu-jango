import json
import pickle
import os
import datetime
from django.conf import settings

# https://stackoverflow.com/questions/10252010/serializing-class-instance-to-json
# def serialize(obj):
#     """JSON serializer for objects not serializable by default json code"""

#     if isinstance(obj, date):
#         serial = obj.isoformat()
#         return serial

#     if isinstance(obj, time):
#         serial = obj.isoformat()
#         return serial

#     return obj.__dict__

def save_variable_as_text_file(variable):
    fileDir = os.path.join(settings.MEDIA_ROOT, 'log')
    fileName = str(datetime.date.today()) +  ".txt"
    
    # with open(fileName, 'wb') as file:
    #     pickle.dump(variable, file)
        
    # message_bytes = pickle.dumps(variable)
    # base64_bytes = base64.b64encode(message_bytes)
    # txt = base64_bytes.decode('ascii')
    # log_write(txt)

    with open(fileName, 'wb') as file:
        json.dump(variable.__dict__, file, indent=2)
    
def load_variable_from_text_file(filename):
    with open(filename, 'rb') as file:
        variable = pickle.load(file)
    return variable


def log_write(msg=None):
    fileDir = os.path.join(settings.MEDIA_ROOT, 'log')
    fileName = str(datetime.date.today()) +  ".txt"
    # print('디렉토리:', fileDir)
    try:
        if not os.path.isdir(fileDir):
            os.makedirs(os.path.join(fileDir))

        if os.path.isfile(os.path.join(fileDir, fileName)):
            fid = open(os.path.join(fileDir, fileName), mode='a', encoding='utf-8')
        else:
            fid = open(os.path.join(fileDir, fileName), mode='w', encoding='utf-8')

        fid.write('\n\n')
        fid.write(str(datetime.datetime.now())+"\n")
        fid.write(msg)
        fid.close()

    except OSError as e:
        pass
    
def log_save(exDict):
    dirname = 'logs'
    
    dir_path = os.path.join(settings.BASE_DIR, dirname)
    
    if not os.path.isdir(dir_path):
        # os.mkdir(os.path.join(settings.BASE_DIR, dirname))
        os.mkdir(dir_path)
        #os.makedirs(settings.BASE_DIR + dirname)
       
    with open(os.path.join(dir_path + '/text2.log'), 'w+b', encoding="utf-8", newline="\n") as file:
        if type(exDict) is not dict:
            exDict = dict(exDict)
            
        file.write(str(json.dumps(exDict))) # use `json.loads` to do the reverse
     
    # # save data
    # with open(os.path.join(dir_path + '/text.log'),'wb') as fw:
    #     pickle.dump(exDict, fw)
        
    # with open(os.path.join(dir_path + '/text.log'), 'wb') as file:
    #     if type(exDict) is not dict:
    #         exDict = dict(exDict)
            
    #     file.write(json.dumps(exDict)) # use `json.loads` to do the reverse
